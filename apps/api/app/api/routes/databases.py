"""Database instance provisioning & management (PostgreSQL/MySQL/MariaDB/Redis/MongoDB)."""
from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.db import get_db, utcnow
from ...core.security import encrypt_secret
from ...models.infrastructure import DatabaseInstance
from ...models.user import User
from ...services import db_provisioner
from ...services.docker_client import DockerUnavailableError, docker_service
from ..deps import get_current_user, record_audit, require_permission, verify_csrf
from ..schemas import DatabaseCreate, DatabaseOut

router = APIRouter(prefix="/api/databases", tags=["databases"])

_engine_ports = {"postgresql": 5432, "mysql": 3306, "mariadb": 3306, "redis": 6379, "mongodb": 27017}


def _get_instance(db: Session, instance_id: uuid.UUID) -> DatabaseInstance:
    instance = db.query(DatabaseInstance).filter(
        DatabaseInstance.id == instance_id, DatabaseInstance.deleted_at.is_(None)
    ).first()
    if instance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Database instance not found")
    return instance


def _health_worker(instance_id: str) -> None:
    """Wait for the freshly provisioned container and record health."""
    from ...core.db import SessionLocal

    session = SessionLocal()
    try:
        instance = session.query(DatabaseInstance).get(instance_id)
        if instance is None:
            return
        healthy = db_provisioner.wait_healthy(instance)
        instance.status = "running" if healthy else "error"
        instance.last_health_at = utcnow()
        if not healthy:
            instance.last_error = "Container did not become healthy within 90s"
        session.commit()
    finally:
        session.close()


@router.get("", response_model=list[DatabaseOut])
def list_databases(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    instances = (db.query(DatabaseInstance)
                 .filter(DatabaseInstance.deleted_at.is_(None))
                 .order_by(DatabaseInstance.created_at).all())
    # live status refresh (cheap: single inspect per instance)
    for instance in instances:
        container = docker_service.get_container(instance.container_name) if docker_service.available else None
        if container is not None:
            container.reload()
            instance.status = "running" if container.status == "running" else container.status
        elif instance.status == "running":
            instance.status = "stopped"
    db.commit()
    return instances


@router.post("", response_model=DatabaseOut, status_code=202, dependencies=[Depends(verify_csrf)])
def create_database(payload: DatabaseCreate, request: Request,
                    user: User = Depends(require_permission("databases.write")),
                    db: Session = Depends(get_db)):
    import re as _re

    if not _re.match(r"^[a-z0-9][a-z0-9-]{1,78}$", payload.name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Name must be lowercase letters/digits/dashes (2-80 chars)")
    if db.query(DatabaseInstance).filter_by(name=payload.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "A database with this name already exists")

    password = payload.password or db_provisioner.generate_password()
    version = payload.version or {"postgresql": "16-alpine", "mysql": "8.0", "mariadb": "11",
                                  "redis": "7-alpine", "mongodb": "7"}.get(payload.engine, "latest")
    instance = DatabaseInstance(
        name=payload.name,
        engine=payload.engine,
        image=f"_{payload.engine}",  # set below via spec
        version=version,
        username=payload.username or "localdeploy",
        password_encrypted=encrypt_secret(password),
        database_name=payload.database_name or payload.username or "localdeploy",
        port=_engine_ports.get(payload.engine, 5432),
        published_port=payload.published_port,
        container_name=f"ld-db-{payload.name}",
        volume_name=f"ld-db-{payload.name}-data",
        status="creating",
    )
    spec = db_provisioner.engine_spec(instance.engine, version, password,
                                      instance.username, instance.database_name or "")
    instance.image = spec.image

    db.add(instance)
    db.commit()
    db.refresh(instance)

    if docker_service.available:
        try:
            db_provisioner.provision(instance)
            db.commit()
            import threading

            threading.Thread(target=_health_worker, args=(str(instance.id),), daemon=True).start()
        except (DockerUnavailableError, Exception) as exc:
            instance.status = "error"
            instance.last_error = str(exc)[:500]
            db.commit()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Provisioning failed: {exc}")
    else:
        instance.status = "error"
        instance.last_error = "Docker Engine is not reachable on this host"
        db.commit()

    record_audit(db, user, "databases.create", "database", str(instance.id),
                 {"name": instance.name, "engine": instance.engine}, request)
    return instance


@router.get("/{instance_id}", response_model=DatabaseOut)
def get_database(instance_id: uuid.UUID, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    return _get_instance(db, instance_id)


@router.post("/{instance_id}/start", dependencies=[Depends(verify_csrf)])
def start_database(instance_id: uuid.UUID, request: Request,
                   user: User = Depends(require_permission("databases.write")),
                   db: Session = Depends(get_db)):
    instance = _get_instance(db, instance_id)
    try:
        db_provisioner.action(instance, "start")
    except DockerUnavailableError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    instance.status = "running"
    instance.last_health_at = utcnow()
    db.commit()
    record_audit(db, user, "databases.start", "database", str(instance.id), {}, request)
    return {"ok": True, "status": instance.status}


@router.post("/{instance_id}/stop", dependencies=[Depends(verify_csrf)])
def stop_database(instance_id: uuid.UUID, request: Request,
                  user: User = Depends(require_permission("databases.write")),
                  db: Session = Depends(get_db)):
    instance = _get_instance(db, instance_id)
    try:
        db_provisioner.action(instance, "stop")
    except DockerUnavailableError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    instance.status = "stopped"
    db.commit()
    record_audit(db, user, "databases.stop", "database", str(instance.id), {}, request)
    return {"ok": True, "status": instance.status}


@router.post("/{instance_id}/restart", dependencies=[Depends(verify_csrf)])
def restart_database(instance_id: uuid.UUID, request: Request,
                     user: User = Depends(require_permission("databases.write")),
                     db: Session = Depends(get_db)):
    instance = _get_instance(db, instance_id)
    try:
        db_provisioner.action(instance, "restart")
    except DockerUnavailableError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    instance.status = "running"
    db.commit()
    record_audit(db, user, "databases.restart", "database", str(instance.id), {}, request)
    return {"ok": True, "status": instance.status}


@router.delete("/{instance_id}", dependencies=[Depends(verify_csrf)])
def delete_database(instance_id: uuid.UUID, request: Request,
                    user: User = Depends(require_permission("databases.write")),
                    db: Session = Depends(get_db)):
    instance = _get_instance(db, instance_id)
    name = instance.name
    remove_volume = bool(request.query_params.get("remove_volume", "false").lower() == "true")
    try:
        db_provisioner.remove(instance, remove_volume=remove_volume)
    except DockerUnavailableError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    instance.deleted_at = utcnow()
    instance.status = "deleted"
    db.commit()
    record_audit(db, user, "databases.delete", "database", str(instance.id),
                 {"name": name, "remove_volume": remove_volume}, request)
    return {"ok": True}


@router.get("/{instance_id}/connection")
def database_connection(instance_id: uuid.UUID,
                        user: User = Depends(require_permission("databases.read")),
                        db: Session = Depends(get_db)):
    instance = _get_instance(db, instance_id)
    return db_provisioner.connection_info(instance)


@router.post("/{instance_id}/health")
def database_health(instance_id: uuid.UUID,
                    user: User = Depends(require_permission("databases.write")),
                    db: Session = Depends(get_db)):
    instance = _get_instance(db, instance_id)
    if not docker_service.available:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Docker Engine is not reachable")
    healthy = db_provisioner.wait_healthy(instance, timeout_seconds=15)
    instance.status = "running" if healthy else instance.status
    instance.last_health_at = utcnow()
    db.commit()
    return {"healthy": healthy, "status": instance.status}


# ------------------------------------------------------------------ backups

@router.post("/{instance_id}/backups", status_code=202, dependencies=[Depends(verify_csrf)])
def create_backup(instance_id: uuid.UUID, request: Request,
                  user: User = Depends(require_permission("backups.write")),
                  db: Session = Depends(get_db)):
    from ...models.deployment import BackupRecord
    from ...services import backups as backup_service

    instance = _get_instance(db, instance_id)
    filename = f"{instance.name}-{utcnow().strftime('%Y%m%d-%H%M%S')}.sql"
    record = BackupRecord(
        target_type="database", target_id=str(instance.id), target_name=instance.name,
        file_path=str(backup_service.backup_file_path(filename)), status="running",
        created_by_name=user.username,
    )
    db.add(record)
    db.commit()

    def _run(record_id: str) -> None:
        from ...core.db import SessionLocal

        session = SessionLocal()
        try:
            rec = session.query(BackupRecord).get(record_id)
            inst = session.query(DatabaseInstance).get(instance_id)
            path = backup_service.backup_database(inst, filename)
            backup_service.finalize_record(rec, path)
            session.commit()
        except Exception as exc:
            rec = session.query(BackupRecord).get(record_id)
            rec.status = "failed"
            rec.error_message = str(exc)[:1000]
            session.commit()
        finally:
            session.close()

    import threading

    threading.Thread(target=_run, args=(str(record.id),), daemon=True).start()
    record_audit(db, user, "backups.create_database", "database", str(instance.id), {}, request)
    return {"backup_id": str(record.id), "status": record.status}


@router.get("/{instance_id}/backups")
def list_backups(instance_id: uuid.UUID, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    from ...models.deployment import BackupRecord

    instance = _get_instance(db, instance_id)
    records = (db.query(BackupRecord)
               .filter(BackupRecord.target_type == "database",
                       BackupRecord.target_id == str(instance.id))
               .order_by(BackupRecord.created_at.desc()).all())
    return [{
        "id": str(r.id), "status": r.status, "file": r.file_path.split("\\")[-1].split("/")[-1],
        "file_size_bytes": r.file_size_bytes, "checksum": r.checksum,
        "error_message": r.error_message, "created_at": r.created_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    } for r in records]


@router.post("/{instance_id}/restore", status_code=202, dependencies=[Depends(verify_csrf)])
def restore_backup(instance_id: uuid.UUID, payload: dict, request: Request,
                   user: User = Depends(require_permission("backups.write")),
                   db: Session = Depends(get_db)):
    from ...models.deployment import BackupRecord
    from ...services import backups as backup_service

    instance = _get_instance(db, instance_id)
    backup_id = payload.get("backup_id")
    if not backup_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "backup_id is required")
    record = db.query(BackupRecord).get(uuid.UUID(backup_id))
    if record is None or record.status != "success":
        raise HTTPException(status.HTTP_409_CONFLICT, "Backup is not available for restore")

    restore_record = BackupRecord(
        target_type=f"{record.target_type}-restore", target_id=str(instance.id),
        target_name=f"{instance.name} (restore of {record.file_path.split('/')[-1]})",
        file_path=record.file_path, status="running", restore_of_id=record.id,
        created_by_name=user.username,
    )
    db.add(restore_record)
    db.commit()

    def _run(restore_id: str) -> None:
        from ...core.db import SessionLocal

        session = SessionLocal()
        try:
            rec = session.query(BackupRecord).get(restore_id)
            inst = session.query(DatabaseInstance).get(instance_id)
            backup_service.restore_database(inst, backup_service.backup_file_path(record.file_path))
            rec.status = "success"
            rec.finished_at = utcnow()
            session.commit()
        except Exception as exc:
            rec = session.query(BackupRecord).get(restore_id)
            rec.status = "failed"
            rec.error_message = str(exc)[:1000]
            session.commit()
        finally:
            session.close()

    import threading

    threading.Thread(target=_run, args=(str(restore_record.id),), daemon=True).start()
    record_audit(db, user, "backups.restore_database", "database", str(instance.id),
                 {"backup_id": backup_id}, request)
    return {"restore_id": str(restore_record.id), "status": restore_record.status}
