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
