"""User management (admin)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...core.security import hash_password, password_policy_error
from ...models.user import Role, User
from ..deps import get_current_user, record_audit, require_permission, verify_csrf
from ..schemas import RoleOut, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


def _user_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


@router.get("", response_model=list[UserOut], dependencies=[Depends(verify_csrf)])
def list_users(user: User = Depends(require_permission("users.write")), db: Session = Depends(get_db)):
    users = db.query(User).filter(User.deleted_at.is_(None)).order_by(User.created_at).all()
    return [_user_out(u) for u in users]


@router.get("/roles", response_model=list[RoleOut], dependencies=[Depends(verify_csrf)])
def list_roles(user: User = Depends(require_permission("users.write")), db: Session = Depends(get_db)):
    return db.query(Role).order_by(Role.name).all()


@router.post("", response_model=UserOut, status_code=201, dependencies=[Depends(verify_csrf)])
def create_user(payload: UserCreate, request: Request,
                admin: User = Depends(require_permission("users.write")), db: Session = Depends(get_db)):
    if error := password_policy_error(payload.password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error)
    if db.query(User).filter((User.username == payload.username) | (User.email == payload.email),
                             User.deleted_at.is_(None)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already exists")
    role = db.query(Role).get(uuid.UUID(payload.role_id)) if payload.role_id else None
    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role_id=role.id if role else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    record_audit(db, admin, "users.create", "user", str(user.id), {"username": user.username}, request)
    return _user_out(user)


@router.put("/{user_id}", response_model=UserOut, dependencies=[Depends(verify_csrf)])
def update_user(user_id: uuid.UUID, payload: UserUpdate, request: Request,
                admin: User = Depends(require_permission("users.write")), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if payload.email is not None:
        user.email = payload.email.lower()
    if payload.role_id is not None:
        role = db.query(Role).get(uuid.UUID(payload.role_id))
        if role is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Role not found")
        user.role_id = role.id
    if payload.is_active is not None:
        if user.id == admin.id and not payload.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate yourself")
        user.is_active = payload.is_active
    if payload.password:
        if error := password_policy_error(payload.password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, error)
        user.password_hash = hash_password(payload.password)
    db.commit()
    record_audit(db, admin, "users.update", "user", str(user.id), {"fields": list(payload.model_dump(exclude_unset=True))}, request)
    return _user_out(user)


@router.delete("/{user_id}", dependencies=[Depends(verify_csrf)])
def delete_user(user_id: uuid.UUID, request: Request,
                admin: User = Depends(require_permission("users.write")), db: Session = Depends(get_db)):
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete yourself")
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user.deleted_at = utcnow()
    user.is_active = False
    db.commit()
    record_audit(db, admin, "users.delete", "user", str(user.id), {"username": user.username}, request)
    return {"ok": True}
