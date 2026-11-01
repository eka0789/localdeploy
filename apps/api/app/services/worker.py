"""Background deployment worker.

Runs inside the API process as an asyncio task; heavy work is executed in a
thread (`asyncio.to_thread`) so the HTTP event loop never blocks on builds.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from ..core.config import settings
from ..core.db import SessionLocal, utcnow
from ..models.deployment import Deployment
from .deployer import run_deployment
from .log_hub import log_hub


class DeploymentWorker:
    def __init__(self, concurrency: int = 2) -> None:
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._concurrency = concurrency
        self._running: set[uuid.UUID] = set()

    async def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [asyncio.create_task(self._loop(i)) for i in range(self._concurrency)]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    async def enqueue(self, deployment_id: uuid.UUID) -> None:
        self._running.add(deployment_id)
        await self._queue.put(deployment_id)
        await log_hub.publish("system", {
            "type": "deployment", "level": "info",
            "message": f"Deployment queued ({self._queue.qsize()} in queue)",
            "deployment_id": str(deployment_id),
        })

    async def _loop(self, index: int) -> None:
        while True:
            deployment_id = await self._queue.get()
            try:
                await asyncio.to_thread(run_deployment, deployment_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # deployer already records failures; belt & braces
                pass
            finally:
                self._running.discard(deployment_id)
                self._queue.task_done()


worker = DeploymentWorker()


def create_deployment(
    session,
    application,
    trigger: str = "manual",
    created_by: uuid.UUID | None = None,
    created_by_name: str | None = None,
    commit_sha: str | None = None,
) -> Deployment:
    deployment = Deployment(
        application_id=application.id,
        status="queued",
        trigger=trigger,
        git_branch=application.git_branch,
        git_commit_sha=commit_sha,
        source_type=application.source_type,
        created_by=created_by,
        created_by_name=created_by_name,
        meta={},
    )
    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    return deployment


async def enqueue_deployment(deployment: Deployment) -> None:
    await worker.enqueue(deployment.id)


async def metrics_sampler() -> None:
    """Periodic host + container metrics sampler with retention pruning."""
    from .monitor import sample_application_metrics, sample_server_metrics

    while True:
        try:
            await asyncio.to_thread(sample_server_metrics)
            await asyncio.to_thread(sample_application_metrics)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(settings.metrics_sample_seconds)


async def session_cleaner() -> None:
    from ..core.db import purge_expired_sessions

    from ...services.previews import cleanup_expired_previews

    counter = 0
    while True:
        try:
            await asyncio.to_thread(purge_expired_sessions, SessionLocal())
            await asyncio.to_thread(purge_old_logs, SessionLocal())
            counter += 1
            if counter % 6 == 0:  # ~every 6 hours
                expired = await asyncio.to_thread(cleanup_expired_previews, SessionLocal())
                if expired:
                    await log_hub.publish("system", {
                        "type": "preview", "level": "info",
                        "message": f"Cleaned up {expired} expired preview deployment(s)",
                    })
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(3600)


def purge_old_logs(db) -> None:
    """Retention policy: deployment logs 30d, audit logs 180d (configurable via env)."""
    from datetime import timedelta

    import os

    from ..models.deployment import DeploymentLog
    from ..models.user import AuditLog

    log_days = int(os.environ.get("LOCALDEPLOY_LOG_RETENTION_DAYS", "30"))
    audit_days = int(os.environ.get("LOCALDEPLOY_AUDIT_RETENTION_DAYS", "180"))
    cutoff_logs = utcnow() - timedelta(days=log_days)
    cutoff_audit = utcnow() - timedelta(days=audit_days)
    db.query(DeploymentLog).filter(DeploymentLog.created_at < cutoff_logs).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.created_at < cutoff_audit).delete(synchronize_session=False)
    db.commit()


def run_due_backup_schedules() -> int:
    """Run any enabled backup schedule whose interval has elapsed. Returns count."""
    from datetime import timedelta

    from ..models.deployment import BackupRecord
    from ..models.infrastructure import BackupSchedule, DatabaseInstance
    from . import backups as backup_service

    session = SessionLocal()
    ran = 0
    try:
        schedules = session.query(BackupSchedule).filter_by(enabled=True).all()
        now = utcnow()
        for schedule in schedules:
            due = schedule.last_run_at is None or (
                now - schedule.last_run_at >= timedelta(hours=schedule.interval_hours)
            )
            if not due:
                continue
            ran += 1
            schedule.last_run_at = now
            filename = (
                f"auto-{schedule.target_name}-{now.strftime('%Y%m%d-%H%M%S')}"
                + (".sql" if schedule.target_type == "database" else ".tar.gz")
            )
            record = BackupRecord(
                target_type=schedule.target_type, target_id=schedule.target_id,
                target_name=f"[auto] {schedule.target_name}",
                file_path=str(backup_service.backup_file_path(filename)),
                status="running", created_by_name="schedule",
            )
            session.add(record)
            session.commit()
            try:
                if schedule.target_type == "database":
                    instance = session.query(DatabaseInstance).filter(
                        DatabaseInstance.id == schedule.target_id,
                        DatabaseInstance.deleted_at.is_(None)).first()
                    if instance is None:
                        raise RuntimeError("Database instance no longer exists")
                    path = backup_service.backup_database(instance, filename)
                else:
                    path = backup_service.backup_volume(schedule.target_id, filename)
                backup_service.finalize_record(record, path)
                schedule.last_status = "success"
                schedule.last_error = None
            except Exception as exc:
                record = session.query(BackupRecord).get(record.id)
                record.status = "failed"
                record.error_message = str(exc)[:1000]
                schedule.last_status = "failed"
                schedule.last_error = str(exc)[:500]
            session.commit()
            _prune_schedule_backups(session, schedule)
        return ran
    finally:
        session.close()


def _prune_schedule_backups(session, schedule, ) -> None:
    """Keep only the newest `keep_last` successful auto backups for this schedule."""
    from ..models.deployment import BackupRecord
    from . import backups as backup_service

    records = (
        session.query(BackupRecord)
        .filter(BackupRecord.target_id == schedule.target_id,
                BackupRecord.target_name.like("[auto]%"),
                BackupRecord.status == "success")
        .order_by(BackupRecord.created_at.desc())
        .all()
    )
    for record in records[schedule.keep_last:]:
        path = backup_service.backup_file_path((record.file_path or "").replace("\\", "/").split("/")[-1])
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        session.delete(record)
    session.commit()


async def backup_scheduler() -> None:
    """Periodic backup schedule runner (every 60s)."""
    while True:
        try:
            count = await asyncio.to_thread(run_due_backup_schedules)
            if count:
                await log_hub.publish("system", {
                    "type": "backup", "level": "info",
                    "message": f"Backup scheduler ran {count} scheduled backup(s)",
                })
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# autoscaler
# ---------------------------------------------------------------------------

_autoscale_state: dict[str, dict] = {}  # app_id -> {high_streak, low_streak, last_action_ts}


async def autoscaler() -> None:
    """Sample application CPU and scale replicas with hysteresis (every 15s)."""
    import time

    from .scaling import decide_autoscale, scale_application

    while True:
        try:
            await asyncio.to_thread(_autoscale_tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(15)


def _autoscale_tick() -> None:
    from datetime import timedelta

    from sqlalchemy import func

    from ..models.application import Application
    from ..models.monitoring import ApplicationMetric
    from .scaling import decide_autoscale, scale_application

    session = SessionLocal()
    try:
        apps = session.query(Application).filter_by(autoscale_enabled=True, status="running").all()
        cutoff = utcnow() - timedelta(seconds=90)
        for app in apps:
            rows = (
                session.query(func.avg(ApplicationMetric.cpu_percent))
                .filter(ApplicationMetric.application_id == app.id,
                        ApplicationMetric.sampled_at >= cutoff)
                .scalar()
            )
            if rows is None:
                continue
            avg_cpu = float(rows)
            state = _autoscale_state.setdefault(str(app.id), {"high": 0, "low": 0})
            target, high, low, action = decide_autoscale(
                current=app.replicas or 1,
                avg_cpu=avg_cpu,
                threshold=app.autoscale_cpu_threshold,
                minimum=app.autoscale_min,
                maximum=app.autoscale_max,
                high_streak=state["high"],
                low_streak=state["low"],
            )
            state["high"], state["low"] = high, low
            if action != "hold":
                try:
                    scale_application(session, app, target)
                    log_hub.publish_sync("system", {
                        "type": "application", "level": "info",
                        "message": (f"Autoscaler: '{app.name}' {action} to {target} replica(s) "
                                    f"(avg CPU {avg_cpu:.0f}%)"),
                        "application_id": str(app.id),
                    })
                except Exception:
                    pass
    finally:
        session.close()


def utcnow_ts() -> datetime:
    return datetime.now(timezone.utc)
