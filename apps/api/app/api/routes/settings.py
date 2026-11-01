"""Server settings and audit log access."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...models.infrastructure import ServerSetting
from ...models.user import AuditLog, User
from ..deps import get_current_user, record_audit, require_permission, verify_csrf
from ..schemas import SettingsUpdate

router = APIRouter(prefix="/api", tags=["settings"])

DEFAULT_SETTINGS = {
    "networking.mode": {"value": {"mode": "public-ip"}, "description": "Active public networking mode"},
    "security.session_ttl_minutes": {"value": {"minutes": 10080}, "description": "Session lifetime"},
    "deployments.concurrency": {"value": {"workers": 2}, "description": "Parallel deployment workers"},
}


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stored = {s.key: {"value": s.value, "description": s.description, "updated_at": s.updated_at.isoformat()}
              for s in db.query(ServerSetting).all()}
    merged = {}
    for key, default in DEFAULT_SETTINGS.items():
        merged[key] = stored.get(key, {"value": default["value"],
                                       "description": default["description"],
                                       "updated_at": None})
    merged.update({k: v for k, v in stored.items() if k not in merged})
    return {"settings": merged,
            "server": {"version": "1.0.0", "environment": "configured via .env"}}


@router.put("/settings", dependencies=[Depends(verify_csrf)])
def update_settings(payload: SettingsUpdate, request: Request,
                    user: User = Depends(require_permission("settings.write")),
                    db: Session = Depends(get_db)):
    for item in payload.settings:
        setting = db.query(ServerSetting).filter_by(key=item.key).first()
        if setting is None:
            setting = ServerSetting(key=item.key, value=item.value)
            db.add(setting)
        else:
            setting.value = item.value
    db.commit()
    record_audit(db, user, "settings.update", "settings", None,
                 {"keys": [s.key for s in payload.settings]}, request)
    return get_settings(user, db)


@router.get("/audit-logs")
def audit_logs(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
               action: str | None = None,
               user: User = Depends(require_permission("settings.read")), db: Session = Depends(get_db)):
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        query = query.filter(AuditLog.action == action)
    total = query.count()
    rows = query.offset(offset).limit(limit).all()
    return {
        "total": total,
        "logs": [{
            "id": str(r.id), "username": r.username, "action": r.action,
            "resource_type": r.resource_type, "resource_id": r.resource_id,
            "detail": r.detail, "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat(),
        } for r in rows],
    }
