"""Replica scaling for applications.

One primary container `ld-<slug>` plus optional replicas `ld-<slug>-r2..n`,
all sharing the same Traefik service so traffic is load-balanced. The desired
count is reconciled against live containers (create missing / remove surplus).
"""
from __future__ import annotations

import socket
import time

import httpx

from ..core.config import settings
from ..core.db import utcnow
from ..core.security import decrypt_secret
from ..models.application import Application, ApplicationDomain, EnvironmentVariable
from .docker_client import docker_service
from .log_hub import log_hub
from .traefik import traefik_labels


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def container_name_for(slug: str, index: int) -> str:
    return f"ld-{slug}" if index == 1 else f"ld-{slug}-r{index}"


def current_replica_count(slug: str) -> int:
    """Live count of this app's containers that are running (primary counts as 1)."""
    client = docker_service.client()
    if client is None:
        return 0
    count = 0
    for index in range(1, 51):  # hard cap sanity
        container = docker_service.get_container(container_name_for(slug, index))
        if container is None:
            if index == 1:
                continue  # primary may be named differently (compose); keep scanning cheap
            break
        container.reload()
        if container.status == "running":
            count += 1
        if index > 1 and container is not None and count == 0 and index > 2:
            break
    return count


def scale_application(session, app: Application, desired: int, logger=None) -> dict:
    """Reconcile running replicas to `desired`. Returns a report."""
    client = docker_service.require()
    desired = max(1, min(desired, 10))

    primary = docker_service.get_container(container_name_for(app.slug, 1))
    if primary is None:
        raise RuntimeError("Primary container not found — deploy the application first")
    primary.reload()
    if primary.status != "running":
        primary.start()
    image = primary.image.tags[0] if primary.image.tags else None
    if image is None:
        raise RuntimeError("Primary container image has no tag")

    # template env/labels from the primary container definition (DB is source of truth)
    env_map = {
        v.key: decrypt_secret(v.value_encrypted)
        for v in session.query(EnvironmentVariable).filter_by(application_id=app.id).all()
    }
    from .db_connections import build_env_for_app

    env_map.update(build_env_for_app(session, app.id))
    domains = session.query(ApplicationDomain).filter_by(application_id=app.id).all()
    labels = {"io.localdeploy.managed": "true", "io.localdeploy.application": str(app.id)}
    labels.update(traefik_labels(app.slug, [(d.hostname, d.target_port, d.ssl_enabled) for d in domains], app.container_port))

    created, removed = 0, 0

    # scale up: create missing replicas
    for index in range(2, desired + 1):
        name = container_name_for(app.slug, index)
        existing = docker_service.get_container(name)
        if existing is not None:
            existing.reload()
            if existing.status != "running":
                existing.start()
            continue
        health_port = _free_loopback_port()
        container = client.containers.run(
            image=image,
            name=name,
            detach=True,
            environment=env_map,
            labels=labels,
            network=settings.deploy_network,
            ports={f"{app.container_port}/tcp": ("127.0.0.1", health_port)},
            mem_limit=f"{app.memory_limit_mb}m" if app.memory_limit_mb else None,
            nano_cpus=int((app.cpu_limit or 0) * 1e9) or None,
            restart_policy={"Name": "unless-stopped"},
        )
        created += 1
        # lightweight readiness: wait until it responds or 30s
        deadline = time.monotonic() + 30
        with httpx.Client(timeout=2.0) as http:
            while time.monotonic() < deadline:
                try:
                    if http.get(f"http://127.0.0.1:{health_port}{app.health_check_path or '/'}").status_code < 500:
                        break
                except httpx.HTTPError:
                    time.sleep(1.5)

    # scale down: remove surplus replicas (highest index first)
    for index in range(desired + 1, desired + 12):
        name = container_name_for(app.slug, index)
        container = docker_service.get_container(name)
        if container is None:
            break
        container.remove(force=True)
        removed += 1

    app.replicas = desired
    session.commit()
    report = {"desired": desired, "created": created, "removed": removed}
    log_hub.publish_sync("system", {
        "type": "application", "level": "info",
        "message": f"'{app.name}' scaled to {desired} replica(s) (+{created}/-{removed})",
        "application_id": str(app.id),
    })
    return report


# ---------------------------------------------------------------------------
# autoscaler decision (pure, testable)
# ---------------------------------------------------------------------------

def decide_autoscale(
    current: int,
    avg_cpu: float,
    threshold: int,
    minimum: int,
    maximum: int,
    high_streak: int,
    low_streak: int,
) -> tuple[int, int, int, str]:
    """Return (new_replicas, new_high_streak, new_low_streak, action).

    Scale up after 3 consecutive samples above threshold; scale down after 6
    consecutive samples below threshold/2. Hysteresis avoids flapping.
    """
    action = "hold"
    target = current
    if avg_cpu > threshold:
        high_streak += 1
        low_streak = 0
        if high_streak >= 3 and current < maximum:
            target = min(maximum, current + 1)
            action = "scale_up"
            high_streak = 0
    elif avg_cpu < threshold / 2:
        low_streak += 1
        high_streak = 0
        if low_streak >= 6 and current > minimum:
            target = max(minimum, current - 1)
            action = "scale_down"
            low_streak = 0
    else:
        high_streak = 0
        low_streak = 0
    return target, high_streak, low_streak, action
