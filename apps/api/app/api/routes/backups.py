"""Global backup records (database dumps + volume archives)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...models.deployment import BackupRecord
from ...models.user import User
from ...services import backups as backup_service
from ..deps import get_current_user, record_audit, require_permission, verify_csrf

router = APIRouter(prefix="/api/backups", tags=["backups"])


@router.get("")
def list_backups(target_type: str | None = None, status_filter: str | None = None,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(300)
    if target_type:
        query = query.filter(BackupRecord.target_type == target_type)
    if status_filter:
        query = query.filter(BackupRecord.status == status_filter)
    records = query.all()
    return [{
        "id": str(r.id), "target_type": r.target_type, "target_id": r.target_id,
        "target_name": r.target_name, "status": r.status,
        "file": (r.file_path or "").replace("\\", "/").split("/")[-1],
        "file_size_bytes": r.file_size_bytes, "checksum": r.checksum,
        "restore_of_id": str(r.restore_of_id) if r.restore_of_id else None,
        "created_by_name": r.created_by_name, "error_message": r.error_message,
        "created_at": r.created_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    } for r in records]


@router.post("/volumes", status_code=202, dependencies=[Depends(verify_csrf)])
def create_volume_backup(payload: dict, request: Request,
                         user: User = Depends(require_permission("backups.write")),
                         db: Session = Depends(get_db)):
    volume_name = str(payload.get("volume", "")).strip()
    if not volume_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "volume name is required")
    filename = f"volume-{volume_name}-{utcnow().strftime('%Y%m%d-%H%M%S')}.tar.gz"
    record = BackupRecord(
        target_type="volume", target_id=volume_name, target_name=volume_name,
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
            path = backup_service.backup_volume(volume_name, filename)
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
    record_audit(db, user, "backups.create_volume", "volume", None, {"volume": volume_name}, request)
    return {"backup_id": str(record.id), "status": record.status}


@router.post("/volumes/restore", status_code=202, dependencies=[Depends(verify_csrf)])
def restore_volume_backup(payload: dict, request: Request,
                          user: User = Depends(require_permission("backups.write")),
                          db: Session = Depends(get_db)):
    backup_id = payload.get("backup_id")
    target_volume = str(payload.get("target_volume", "")).strip()
    if not backup_id or not target_volume:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "backup_id and target_volume are required")
    record = db.query(BackupRecord).get(uuid.UUID(backup_id))
    if record is None or record.status != "success" or record.target_type != "volume":
        raise HTTPException(status.HTTP_409_CONFLICT, "Backup is not an available volume archive")

    restore_record = BackupRecord(
        target_type="volume-restore", target_id=target_volume,
        target_name=f"{target_volume} (restore of {(record.file_path or '').replace(chr(92), '/').split('/')[-1]})",
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
            backup_service.restore_volume(target_volume,
                                          backup_service.backup_file_path(record.file_path))
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
    record_audit(db, user, "backups.restore_volume", "volume", None,
                 {"backup_id": backup_id, "target": target_volume}, request)
    return {"restore_id": str(restore_record.id), "status": restore_record.status}


@router.get("/{backup_id}/download")
def download_backup(backup_id: uuid.UUID, user: User = Depends(require_permission("backups.read")),
                    db: Session = Depends(get_db)):
    record = db.query(BackupRecord).get(backup_id)
    if record is None or record.status != "success":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup not available")
    path = backup_service.backup_file_path((record.file_path or "").replace("\\", "/").split("/")[-1])
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup file is missing on disk")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.delete("/{backup_id}", dependencies=[Depends(verify_csrf)])
def delete_backup(backup_id: uuid.UUID, request: Request,
                  user: User = Depends(require_permission("backups.write")),
                  db: Session = Depends(get_db)):
    record = db.query(BackupRecord).get(backup_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Backup not found")
    path = backup_service.backup_file_path((record.file_path or "").replace("\\", "/").split("/")[-1])
    if path.exists():
        path.unlink()
    db.delete(record)
    db.commit()
    record_audit(db, user, "backups.delete", "backup", str(backup_id), {}, request)
    return {"ok": True}


# ------------------------------------------------------------------ schedules

@router.get("/schedules/all")
def list_schedules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ...models.infrastructure import BackupSchedule

    schedules = db.query(BackupSchedule).order_by(BackupSchedule.created_at).all()
    return [{
        "id": str(s.id), "target_type": s.target_type, "target_id": s.target_id,
        "target_name": s.target_name, "interval_hours": s.interval_hours,
        "keep_last": s.keep_last, "enabled": s.enabled,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "last_status": s.last_status, "last_error": s.last_error,
        "created_at": s.created_at.isoformat(),
    } for s in schedules]


@router.post("/schedules", status_code=201, dependencies=[Depends(verify_csrf)])
def create_schedule(payload: dict, request: Request,
                    user: User = Depends(require_permission("backups.write")),
                    db: Session = Depends(get_db)):
    from ...models.infrastructure import BackupSchedule

    target_type = payload.get("target_type")
    if target_type not in ("database", "volume"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "target_type must be database|volume")
    schedule = BackupSchedule(
        target_type=target_type,
        target_id=str(payload.get("target_id", "")),
        target_name=str(payload.get("target_name", "")),
        interval_hours=int(payload.get("interval_hours", 24)),
        keep_last=int(payload.get("keep_last", 7)),
        created_by_name=user.username,
    )
    if not schedule.target_id or not schedule.target_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "target_id and target_name are required")
    db.add(schedule)
    db.commit()
    record_audit(db, user, "backups.schedule.create", "backup_schedule", str(schedule.id),
                 {"target": schedule.target_name, "interval": schedule.interval_hours}, request)
    return {"ok": True, "id": str(schedule.id)}


@router.put("/schedules/{schedule_id}", dependencies=[Depends(verify_csrf)])
def update_schedule(schedule_id: uuid.UUID, payload: dict, request: Request,
                    user: User = Depends(require_permission("backups.write")),
                    db: Session = Depends(get_db)):
    from ...models.infrastructure import BackupSchedule

    schedule = db.query(BackupSchedule).get(schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    if "enabled" in payload:
        schedule.enabled = bool(payload["enabled"])
    if "interval_hours" in payload:
        schedule.interval_hours = max(1, int(payload["interval_hours"]))
    if "keep_last" in payload:
        schedule.keep_last = max(1, int(payload["keep_last"]))
    db.commit()
    record_audit(db, user, "backups.schedule.update", "backup_schedule", str(schedule.id), {}, request)
    return {"ok": True}


@router.delete("/schedules/{schedule_id}", dependencies=[Depends(verify_csrf)])
def delete_schedule(schedule_id: uuid.UUID, request: Request,
                    user: User = Depends(require_permission("backups.write")),
                    db: Session = Depends(get_db)):
    from ...models.infrastructure import BackupSchedule

    schedule = db.query(BackupSchedule).get(schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    db.delete(schedule)
    db.commit()
    record_audit(db, user, "backups.schedule.delete", "backup_schedule", None,
                 {"target": schedule.target_name}, request)
    return {"ok": True}


@router.post("/schedules/{schedule_id}/run", status_code=202, dependencies=[Depends(verify_csrf)])
def run_schedule_now(schedule_id: uuid.UUID,
                     user: User = Depends(require_permission("backups.write")),
                     db: Session = Depends(get_db)):
    """Force a schedule to run on the next scheduler tick (within 60s)."""
    from ...models.infrastructure import BackupSchedule

    schedule = db.query(BackupSchedule).get(schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    schedule.last_run_at = None  # makes it due immediately
    db.commit()
    record_audit(db, user, "backups.schedule.run_now", "backup_schedule", str(schedule.id), {}, request)
    return {"ok": True, "message": "Backup will start within 60 seconds"}
