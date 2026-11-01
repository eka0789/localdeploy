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

    while True:
        try:
            await asyncio.to_thread(purge_expired_sessions, SessionLocal())
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(3600)


def utcnow_ts() -> datetime:
    return datetime.now(timezone.utc)
