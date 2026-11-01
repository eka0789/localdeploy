"""API dependencies: session auth, RBAC, CSRF protection, rate limiting, auditing."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db, utcnow
from ..core.security import hash_token, new_session_token
from ..models.user import AuditLog, User, UserSession

SESSION_COOKIE = "ld_session"
CSRF_COOKIE = "ld_csrf"
CSRF_HEADER = "X-CSRF-Token"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


# ---------------------------------------------------------------------------
# Rate limiting (in-memory sliding window; per process)
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record a hit and return False when the limit is exceeded."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            cutoff = now - window_seconds
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


login_limiter = RateLimiter()
api_limiter = RateLimiter()

# Prometheus counters: {route_template: {status_code: count}}
metrics_registry: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_metrics_lock = threading.Lock()


def record_metrics(route_template: str, status_code: int) -> None:
    with _metrics_lock:
        metrics_registry[route_template][str(status_code)] += 1


# ---------------------------------------------------------------------------
# Auditing
# ---------------------------------------------------------------------------

def record_audit(
    db: Session,
    user: User | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: dict | None = None,
    request: Request | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else None,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            detail=detail or {},
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent", "")[:400] if request else None,
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_user_session(db: Session, user: User, request: Request) -> str:
    token = new_session_token()
    from datetime import timedelta

    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:400],
        expires_at=utcnow() + timedelta(minutes=settings.session_ttl_minutes),
    )
    db.add(session)
    user.last_login_at = utcnow()
    db.commit()
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def set_csrf_cookie(response: Response, token: str) -> str:
    response.set_cookie(
        key=CSRF_COOKIE, value=token, httponly=False, samesite="lax",
        secure=settings.is_production, max_age=3600 * 12, path="/",
    )
    return token


def _bearer_or_cookie_token(request: Request) -> str | None:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return cookie
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _user_for_api_token(db: Session, token: str) -> User | None:
    """Resolve a personal access token (ldt_…) to its user."""
    from ..models.user import ApiToken

    if not token.startswith("ldt_"):
        return None
    row = (
        db.query(ApiToken)
        .filter(ApiToken.token_hash == hash_token(token), ApiToken.revoked_at.is_(None))
        .first()
    )
    if row is None:
        return None
    row.last_used_at = utcnow()
    db.commit()
    user = db.query(User).get(row.user_id)
    if user is None or user.deleted_at is not None or not user.is_active:
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _bearer_or_cookie_token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    # Personal access tokens (CI/CD) take precedence when prefixed ldt_
    if token.startswith("ldt_"):
        user = _user_for_api_token(db, token)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API token")
        request.state.auth_via = "api_token"  # CSRF does not apply to bearer auth
        return user

    session_row = (
        db.query(UserSession)
        .filter(UserSession.token_hash == hash_token(token), UserSession.revoked_at.is_(None))
        .first()
    )
    if session_row is None or session_row.expires_at < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = db.query(User).get(session_row.user_id)
    if user is None or user.deleted_at is not None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    request.state.session_row = session_row
    return user


def require_permission(permission: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        perms = user.permissions
        if "admin" in (user.role.name if user.role else "") or "*" in perms:
            return user
        if permission not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission}")
        return user

    return dependency


async def verify_csrf(request: Request, user: User = Depends(get_current_user)) -> None:
    """Double-submit cookie CSRF check on state-changing requests.

    Skipped for Bearer API-token auth — CSRF attacks ride on ambient cookie
    credentials, which bearer tokens are not.
    """
    if request.method in SAFE_METHODS:
        return
    if getattr(request.state, "auth_via", None) == "api_token":
        return
    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get(CSRF_HEADER)
    if not cookie_token or not header_token or cookie_token != header_token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def hash_token_ws_auth(token: str) -> str:
    """WS endpoints authenticate with the same session cookie; reuse the token hash."""
    return hash_token(token)
