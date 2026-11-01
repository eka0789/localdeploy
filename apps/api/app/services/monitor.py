"""Server & application monitoring (real metrics — never simulated)."""
from __future__ import annotations

import platform
import time
from datetime import timedelta

import psutil

from ..core.config import settings
from ..core.db import SessionLocal, utcnow
from ..models.monitoring import ApplicationMetric, ServerMetric
from .docker_client import docker_service
from .log_hub import log_hub

_prev_net: dict = {"rx": 0, "tx": 0, "ts": 0.0}


def server_snapshot() -> dict:
    """One-shot host snapshot used by both the API endpoint and the sampler."""
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk_root = psutil.disk_usage(str(settings.workspace_dir.resolve().anchor) or "/")
    net = psutil.net_io_counters()
    now = time.monotonic()

    rx_delta = tx_delta = 0
    if _prev_net["ts"] and net:
        dt = now - _prev_net["ts"]
        if dt > 0:
            rx_delta = max(0, int((net.bytes_recv - _prev_net["rx"]) / dt))
            tx_delta = max(0, int((net.bytes_sent - _prev_net["tx"]) / dt))
    _prev_net.update({"rx": net.bytes_recv if net else 0, "tx": net.bytes_sent if net else 0, "ts": now})

    try:
        load_1 = psutil.getloadavg()[0]
    except (AttributeError, OSError):
        load_1 = None

    engine = docker_service.engine_info()
    return {
        "cpu_percent": cpu,
        "cpu_count": psutil.cpu_count() or 1,
        "memory_used_mb": round((mem.total - mem.available) / 1024 / 1024, 1),
        "memory_total_mb": round(mem.total / 1024 / 1024, 1),
        "memory_percent": mem.percent,
        "swap_percent": psutil.swap_memory().percent,
        "disk_used_gb": round(disk_root.used / 1024 / 1024 / 1024, 2),
        "disk_total_gb": round(disk_root.total / 1024 / 1024 / 1024, 2),
        "disk_percent": disk_root.percent,
        "net_rx_bps": rx_delta,
        "net_tx_bps": tx_delta,
        "load_1": load_1,
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "platform": platform.platform(),
        "docker": engine,
    }


def sample_server_metrics() -> None:
    snap = server_snapshot()
    session = SessionLocal()
    try:
        session.add(
            ServerMetric(
                cpu_percent=snap["cpu_percent"],
                memory_used_mb=snap["memory_used_mb"],
                memory_total_mb=snap["memory_total_mb"],
                memory_percent=snap["memory_percent"],
                disk_used_gb=snap["disk_used_gb"],
                disk_total_gb=snap["disk_total_gb"],
                disk_percent=snap["disk_percent"],
                net_rx_bytes=snap["net_rx_bps"],
                net_tx_bytes=snap["net_tx_bps"],
                load_1=snap["load_1"],
                container_count=(snap["docker"] or {}).get("containers_running") or 0,
            )
        )
        cutoff = utcnow() - timedelta(hours=settings.metrics_retention_hours)
        session.query(ServerMetric).filter(ServerMetric.sampled_at < cutoff).delete(synchronize_session=False)
        session.commit()
        log_hub.publish_sync("metrics", {"type": "server", **snap})
    finally:
        session.close()


def sample_application_metrics() -> None:
    if not docker_service.available:
        return
    client = docker_service.client()
    if client is None:
        return
    session = SessionLocal()
    try:
        from ..models.application import Application

        containers = client.containers.list(filters={"label": "io.localdeploy.managed=true"})
        app_ids: set = set()
        for container in containers:
            app_id = (container.labels or {}).get("io.localdeploy.application")
            if not app_id:
                continue
            app_ids.add(app_id)
            try:
                stats = container.stats(stream=False)
            except Exception:
                continue
            cpu_percent = _stats_cpu_percent(stats)
            mem = _stats_memory_mb(stats)
            nets = _stats_network(stats)
            session.add(
                ApplicationMetric(
                    application_id=app_id,
                    container_id=container.id,
                    cpu_percent=cpu_percent,
                    memory_usage_mb=mem[0],
                    memory_limit_mb=mem[1],
                    net_rx_bytes=nets[0],
                    net_tx_bytes=nets[1],
                )
            )
            log_hub.publish_sync(f"metrics:app:{app_id}", {
                "application_id": app_id, "cpu_percent": cpu_percent,
                "memory_usage_mb": mem[0], "memory_limit_mb": mem[1],
                "net_rx_bytes": nets[0], "net_tx_bytes": nets[1],
            })
        cutoff = utcnow() - timedelta(hours=settings.metrics_retention_hours)
        session.query(ApplicationMetric).filter(ApplicationMetric.sampled_at < cutoff).delete(
            synchronize_session=False
        )
        session.commit()
    finally:
        session.close()


def latest_application_metrics(session) -> dict:
    """Latest metric per managed application, joined with app identity."""
    from sqlalchemy import func

    from ..models.application import Application

    subq = (
        session.query(
            ApplicationMetric.application_id,
            func.max(ApplicationMetric.sampled_at).label("latest"),
        )
        .group_by(ApplicationMetric.application_id)
        .subquery()
    )
    rows = (
        session.query(ApplicationMetric, Application.name, Application.slug)
        .join(
            subq,
            (ApplicationMetric.application_id == subq.c.application_id)
            & (ApplicationMetric.sampled_at == subq.c.latest),
        )
        .join(Application, Application.id == ApplicationMetric.application_id)
        .all()
    )
    return {
        str(metric.application_id): {
            "application_id": str(metric.application_id),
            "name": name,
            "slug": slug,
            "cpu_percent": metric.cpu_percent,
            "memory_usage_mb": metric.memory_usage_mb,
            "memory_limit_mb": metric.memory_limit_mb,
            "net_rx_bytes": metric.net_rx_bytes,
            "net_tx_bytes": metric.net_tx_bytes,
            "sampled_at": metric.sampled_at.isoformat(),
        }
        for metric, name, slug in rows
    }


def _stats_cpu_percent(stats: dict) -> float:
    try:
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
        online = stats["cpu_stats"].get("online_cpus") or psutil.cpu_count() or 1
        if system_delta > 0 and cpu_delta > 0:
            return round((cpu_delta / system_delta) * online * 100, 2)
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return 0.0


def _stats_memory_mb(stats: dict) -> tuple[float, float]:
    try:
        usage = stats["memory_stats"].get("usage", 0)
        limit = stats["memory_stats"].get("limit", 0)
        cache = stats["memory_stats"].get("stats", {}).get("cache", 0) or stats["memory_stats"].get("stats", {}).get("inactive_file", 0)
        return round(max(0, usage - cache) / 1024 / 1024, 1), round(limit / 1024 / 1024, 1)
    except (KeyError, TypeError):
        return 0.0, 0.0


def _stats_network(stats: dict) -> tuple[int, int]:
    try:
        nets = stats.get("networks", {})
        rx = sum(n.get("rx_bytes", 0) for n in nets.values())
        tx = sum(n.get("tx_bytes", 0) for n in nets.values())
        return rx, tx
    except (TypeError, AttributeError):
        return 0, 0
