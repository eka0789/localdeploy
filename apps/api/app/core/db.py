"""Database engine, session management and first-run bootstrap."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# Enforce foreign keys in SQLite.
if engine.url.get_backend_name() == "sqlite":

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utcnow() -> datetime:
    """Naive UTC timestamp — SQLite returns naive datetimes, so everything
    (storage and comparisons) is normalized to naive UTC everywhere."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def purge_expired_sessions(db: Session) -> int:
    """Delete expired user sessions. Returns number of rows removed."""
    from ..models.user import UserSession  # local import avoids cycles

    deleted = (
        db.query(UserSession)
        .filter(UserSession.expires_at < utcnow())
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def bootstrap(db: Session) -> None:
    """Create schema and seed baseline data (roles, permissions, first admin, settings).

    Used for fresh installs; schema upgrades afterwards go through Alembic.
    """
    from .security import hash_password
    from ..models.user import (AuditLog, Permission, Role, User, UserSession,  # noqa: F401
                               role_permissions)

    Base.metadata.create_all(bind=engine)

    if db.query(Role).count() == 0:
        for key, label in [
            ("applications.read", "View applications"),
            ("applications.write", "Create and modify applications"),
            ("applications.deploy", "Trigger deployments"),
            ("projects.read", "View projects"),
            ("projects.write", "Manage projects"),
            ("domains.read", "View domains"),
            ("domains.write", "Manage domains"),
            ("databases.read", "View database instances"),
            ("databases.write", "Manage database instances"),
            ("docker.read", "View Docker resources"),
            ("docker.write", "Manage Docker resources"),
            ("monitoring.read", "View monitoring"),
            ("logs.read", "View logs"),
            ("backups.read", "View backups"),
            ("backups.write", "Create and restore backups"),
            ("networking.read", "View networking"),
            ("networking.write", "Manage networking"),
            ("settings.read", "View settings"),
            ("settings.write", "Change settings"),
            ("users.write", "Manage users"),
        ]:
            db.add(Permission(key=key, label=label))

        admin = Role(name="admin", description="Full access", is_system=True)
        viewer = Role(name="viewer", description="Read-only access", is_system=True)
        db.add_all([admin, viewer])
        db.flush()

        perms = db.query(Permission).all()
        admin.permissions.extend(perms)
        viewer.permissions.extend(p for p in perms if p.key.endswith(".read"))

    if db.query(User).count() == 0:
        admin_role = db.scalar(select(Role).where(Role.name == "admin"))
        db.add(
            User(
                username=settings.first_admin_username,
                email=settings.first_admin_email,
                password_hash=hash_password(settings.first_admin_password),
                role_id=admin_role.id if admin_role else None,
                must_change_password=True,
            )
        )

    # Cleanup pass for expired sessions on boot.
    purge_cutoff = utcnow() - timedelta(minutes=settings.session_ttl_minutes)
    db.query(UserSession).filter(UserSession.created_at < purge_cutoff).delete(
        synchronize_session=False
    )

    db.commit()
