"""External database connections (Supabase, Neon, Turso, Atlas, Upstash, …)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...core.security import encrypt_secret
from ...models.application import Application
from ...models.infrastructure import ApplicationDatabaseLink, DatabaseConnection
from ...models.user import User
from ...services import db_connections
from ..deps import get_current_user, record_audit, require_permission, verify_csrf

router = APIRouter(prefix="/api/db-connections", tags=["db-connections"])


# ---------------------------------------------------------------- schemas

class ConnectionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    provider: str = "generic"
    url: str | None = Field(default=None, max_length=1000)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=500)
    database_name: str | None = Field(default=None, max_length=255)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    extra_secrets: dict[str, str] = {}
    notes: str | None = Field(default=None, max_length=2000)


class ConnectionUpdate(BaseModel):
    url: str | None = None
    username: str | None = None
    password: str | None = None
    database_name: str | None = None
    host: str | None = None
    port: int | None = None
    extra_secrets: dict[str, str] | None = None
    notes: str | None = None


class LinkCreate(BaseModel):
    connection_id: str
    application_id: str
    env_mapping: dict[str, str] = {}


# ---------------------------------------------------------------- routes

@router.get("/providers")
def list_providers(user: User = Depends(get_current_user)):
    return [{
        "key": p.key,
        "label": p.label,
        "engine": p.engine,
        "url_scheme": p.url_scheme,
        "fields": p.fields,
        "default_env": p.default_env,
        "docs": p.docs,
    } for p in db_connections.PROVIDERS.values()]


@router.get("")
def list_connections(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(DatabaseConnection)
            .filter(DatabaseConnection.deleted_at.is_(None))
            .order_by(DatabaseConnection.created_at).all())
    return [db_connections.redacted_view(r) for r in rows]


@router.post("", status_code=201, dependencies=[Depends(verify_csrf)])
def create_connection(payload: ConnectionCreate, request: Request,
                      user: User = Depends(require_permission("databases.write")),
                      db: Session = Depends(get_db)):
    if db.query(DatabaseConnection).filter_by(name=payload.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "A connection with this name already exists")
    preset = db_connections.get_preset(payload.provider)
    connection = DatabaseConnection(
        name=payload.name,
        provider=payload.provider,
        engine=preset.engine,
        username=payload.username,
        database_name=payload.database_name,
        host=payload.host,
        port=payload.port,
        password_encrypted=encrypt_secret(payload.password) if payload.password else None,
        url_encrypted=encrypt_secret(payload.url) if payload.url else None,
        extra_secrets={k: encrypt_secret(v) for k, v in (payload.extra_secrets or {}).items() if v},
        notes=payload.notes,
    )
    # derive host/port from the URL when not given explicitly
    if payload.url and not connection.host:
        parsed = db_connections.parse_connection_url(payload.url)
        connection.host = parsed.get("host")
        connection.port = parsed.get("port")
        connection.database_name = connection.database_name or parsed.get("database")
        connection.username = connection.username or parsed.get("username")
    db.add(connection)
    db.commit()
    db.refresh(connection)
    record_audit(db, user, "db_connections.create", "database_connection", str(connection.id),
                 {"name": connection.name, "provider": connection.provider}, request)
    return db_connections.redacted_view(connection)


@router.put("/{connection_id}", dependencies=[Depends(verify_csrf)])
def update_connection(connection_id: uuid.UUID, payload: ConnectionUpdate, request: Request,
                      user: User = Depends(require_permission("databases.write")),
                      db: Session = Depends(get_db)):
    connection = db.query(DatabaseConnection).filter(
        DatabaseConnection.id == connection_id, DatabaseConnection.deleted_at.is_(None)).first()
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    if payload.url is not None:
        connection.url_encrypted = encrypt_secret(payload.url) if payload.url else None
        parsed = db_connections.parse_connection_url(payload.url or "")
        if parsed.get("host"):
            connection.host = parsed["host"]
            connection.port = parsed.get("port")
    if payload.password is not None:
        connection.password_encrypted = encrypt_secret(payload.password) if payload.password else None
    if payload.username is not None:
        connection.username = payload.username
    if payload.database_name is not None:
        connection.database_name = payload.database_name
    if payload.host is not None:
        connection.host = payload.host
    if payload.port is not None:
        connection.port = payload.port
    if payload.extra_secrets is not None:
        merged = {k: v for k, v in (connection.extra_secrets or {}).items()}
        for k, v in payload.extra_secrets.items():
            merged[k] = encrypt_secret(v) if v else None
            if not v:
                merged.pop(k, None)
        connection.extra_secrets = {k: v for k, v in merged.items() if v}
    if payload.notes is not None:
        connection.notes = payload.notes
    db.commit()
    record_audit(db, user, "db_connections.update", "database_connection", str(connection.id), {}, request)
    return db_connections.redacted_view(connection)


@router.delete("/{connection_id}", dependencies=[Depends(verify_csrf)])
def delete_connection(connection_id: uuid.UUID, request: Request,
                      user: User = Depends(require_permission("databases.write")),
                      db: Session = Depends(get_db)):
    from ...core.db import utcnow

    connection = db.query(DatabaseConnection).filter(
        DatabaseConnection.id == connection_id, DatabaseConnection.deleted_at.is_(None)).first()
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    connection.deleted_at = utcnow()
    db.commit()
    record_audit(db, user, "db_connections.delete", "database_connection", str(connection.id),
                 {"name": connection.name}, request)
    return {"ok": True}


@router.post("/{connection_id}/test")
def test_connection(connection_id: uuid.UUID,
                    user: User = Depends(require_permission("databases.write")),
                    db: Session = Depends(get_db)):
    connection = db.query(DatabaseConnection).filter(
        DatabaseConnection.id == connection_id, DatabaseConnection.deleted_at.is_(None)).first()
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    test_status, error = db_connections.test_connection(connection)
    connection.last_tested_at = utcnow()
    connection.last_test_status = test_status
    connection.last_error = error
    db.commit()
    return {"status": test_status, "error": error,
            "tested_at": connection.last_tested_at.isoformat()}


# ---------------------------------------------------------------- links

@router.get("/links/{application_id}")
def list_links(application_id: uuid.UUID, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    links = db.query(ApplicationDatabaseLink).filter_by(application_id=application_id).all()
    out = []
    for link in links:
        connection = db.get(DatabaseConnection, link.connection_id)
        if connection is None:
            continue
        out.append({
            "link_id": str(link.id),
            "connection": db_connections.redacted_view(connection),
            "env_mapping": link.env_mapping or {},
            "env_keys": sorted((link.env_mapping or {}).keys()),
        })
    return out


@router.post("/links", status_code=201, dependencies=[Depends(verify_csrf)])
def create_link(payload: LinkCreate, request: Request,
                user: User = Depends(require_permission("applications.write")),
                db: Session = Depends(get_db)):
    app = db.query(Application).filter(Application.id == uuid.UUID(payload.application_id),
                                       Application.deleted_at.is_(None)).first()
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    connection = db.query(DatabaseConnection).filter(
        DatabaseConnection.id == uuid.UUID(payload.connection_id),
        DatabaseConnection.deleted_at.is_(None)).first()
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")

    existing = db.query(ApplicationDatabaseLink).filter_by(
        application_id=app.id, connection_id=connection.id).first()
    if existing:
        existing.env_mapping = payload.env_mapping or existing.env_mapping
        db.commit()
        link = existing
    else:
        link = ApplicationDatabaseLink(
            application_id=app.id, connection_id=connection.id,
            env_mapping=payload.env_mapping or db_connections.get_preset(connection.provider).default_env,
        )
        db.add(link)
    db.commit()
    record_audit(db, user, "db_connections.link", "application", str(app.id),
                 {"connection": connection.name, "env_keys": sorted((link.env_mapping or {}).keys())}, request)
    return {"ok": True, "link_id": str(link.id), "env_mapping": link.env_mapping}


@router.delete("/links/{application_id}/{connection_id}", dependencies=[Depends(verify_csrf)])
def delete_link(application_id: uuid.UUID, connection_id: uuid.UUID, request: Request,
                user: User = Depends(require_permission("applications.write")),
                db: Session = Depends(get_db)):
    link = db.query(ApplicationDatabaseLink).filter_by(
        application_id=application_id, connection_id=connection_id).first()
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    db.delete(link)
    db.commit()
    record_audit(db, user, "db_connections.unlink", "application", str(application_id), {}, request)
    return {"ok": True}
