"""Authentication routes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...core.security import hash_token, password_policy_error, verify_password
from ...core.config import settings as app_settings
from ..deps import (
    CSRF_COOKIE,
    clear_session_cookie,
    create_user_session,
    get_client_ip,
    get_current_user,
    login_limiter,
    record_audit,
    verify_csrf,
    set_csrf_cookie,
    set_session_cookie,
)
from ...core.security import new_csrf_token
from ..schemas import ChangePasswordRequest, LoginRequest, UserOut
from ...models.user import User, UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    if not login_limiter.check(f"login:{ip}:{payload.username}",
                               app_settings.login_rate_limit_attempts,
                               app_settings.login_rate_limit_window_seconds):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts. Try again later.")

    user = db.query(User).filter(User.username == payload.username, User.deleted_at.is_(None)).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")

    token = create_user_session(db, user, request)
    csrf = set_csrf_cookie(response, new_csrf_token())
    set_session_cookie(response, token)
    login_limiter.reset(f"login:{ip}:{payload.username}")
    record_audit(db, user, "auth.login", "user", str(user.id), {}, request)

    return {
        "user": UserOut.model_validate(user),
        "csrf_token": csrf,
    }


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    session_row = getattr(request.state, "session_row", None)
    if session_row:
        session_row.revoked_at = utcnow()
        db.commit()
    clear_session_cookie(response)
    response.delete_cookie(CSRF_COOKIE, path="/")
    record_audit(db, user, "auth.logout", "user", str(user.id), {}, request)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.get("/csrf")
def csrf(response: Response):
    token = set_csrf_cookie(response, new_csrf_token())
    return {"csrf_token": token}


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, request: Request,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if error := password_policy_error(payload.new_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error)
    from ...core.security import hash_password

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    # invalidate other sessions (keep the current one)
    session_row = getattr(request.state, "session_row", None)
    query = db.query(UserSession).filter(UserSession.user_id == user.id,
                                         UserSession.revoked_at.is_(None))
    if session_row is not None:
        query = query.filter(UserSession.id != session_row.id)
    query.update({"revoked_at": utcnow()}, synchronize_session=False)
    db.commit()
    record_audit(db, user, "auth.change_password", "user", str(user.id), {}, request)
    return {"ok": True}


# ------------------------------------------------------------------ API tokens

@router.get("/tokens")
def list_tokens(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ...models.user import ApiToken

    tokens = (db.query(ApiToken)
              .filter(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
              .order_by(ApiToken.created_at.desc()).all())
    return [{
        "id": str(t.id), "name": t.name, "prefix": t.token_prefix,
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        "created_at": t.created_at.isoformat(),
    } for t in tokens]


@router.post("/tokens", status_code=201, dependencies=[Depends(verify_csrf)])
def create_token(payload: dict, request: Request,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a personal access token - plaintext shown exactly once."""
    from ...core.security import hash_token, new_session_token
    from ...models.user import ApiToken

    name = str(payload.get("name", "")).strip() or "API token"
    token = "ldt_" + new_session_token()
    row = ApiToken(
        user_id=user.id, name=name,
        token_hash=hash_token(token),
        token_prefix=token[:12],
    )
    db.add(row)
    db.commit()
    record_audit(db, user, "auth.token_create", "api_token", str(row.id), {"name": name}, request)
    return {
        "id": str(row.id), "name": name, "token": token,  # shown exactly once
        "created_at": row.created_at.isoformat(),
        "usage": (
            f'curl -X POST "{app_settings.public_base_url}/api/applications/<APP_ID>/deploy" '
            f'-H "Authorization: Bearer {token}"'
        ),
    }


@router.delete("/tokens/{token_id}", dependencies=[Depends(verify_csrf)])
def revoke_token(token_id: uuid.UUID, request: Request,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ...models.user import ApiToken

    row = db.query(ApiToken).filter(ApiToken.id == token_id, ApiToken.user_id == user.id).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found")
    row.revoked_at = utcnow()
    db.commit()
    record_audit(db, user, "auth.token_revoke", "api_token", str(row.id), {"name": row.name}, request)
    return {"ok": True}
