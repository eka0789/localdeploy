"""Prometheus-compatible metrics rendering."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.application import Application
from ..models.monitoring import ApplicationMetric, ServerMetric
from .monitor import server_snapshot


def render_metrics(db: Session) -> str:
    lines: list[str] = []

    def emit(name: str, mtype: str, help_text: str, samples: list[tuple[str, float]]) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {mtype}")
        for labels, value in samples:
            lines.append(f"{name}{{{labels}}} {value}")

    snap = server_snapshot()
    emit("localdeploy_server_cpu_percent", "gauge", "Host CPU usage percent",
         [("", snap["cpu_percent"])])
    emit("localdeploy_server_memory_percent", "gauge", "Host memory usage percent",
         [("", snap["memory_percent"])])
    emit("localdeploy_server_memory_used_bytes", "gauge", "Host memory used",
         [("", snap["memory_used_mb"] * 1024 * 1024)])
    emit("localdeploy_server_disk_percent", "gauge", "Host disk usage percent",
         [("", snap["disk_percent"])])
    emit("localdeploy_server_net_rx_bytes_per_second", "gauge", "Host inbound network bytes/s",
         [("", snap["net_rx_bps"])])
    emit("localdeploy_server_net_tx_bytes_per_second", "gauge", "Host outbound network bytes/s",
         [("", snap["net_tx_bps"])])

    docker = snap.get("docker") or {}
    emit("localdeploy_docker_containers_running", "gauge", "Running containers",
         [("", docker.get("containers_running") or 0)])
    emit("localdeploy_docker_available", "gauge", "Docker engine reachability (1=ok)",
         [("", 1 if docker.get("available") else 0)])

    # Latest application metrics
    apps = db.query(Application).filter(Application.deleted_at.is_(None)).all()
    for app in apps:
        metric = (db.query(ApplicationMetric)
                  .filter(ApplicationMetric.application_id == app.id)
                  .order_by(ApplicationMetric.sampled_at.desc())
                  .first())
        labels = f'application="{app.slug}"'
        if metric:
            emit("localdeploy_app_cpu_percent", "gauge", "Application CPU percent",
                 [(labels, metric.cpu_percent)])
            emit("localdeploy_app_memory_used_bytes", "gauge", "Application memory used",
                 [(labels, metric.memory_usage_mb * 1024 * 1024)])
        lines.append(f'localdeploy_app_up{{{labels}}} {1 if app.status == "running" else 0}')

    # HTTP request counters (populated by middleware)
    from ..api.deps import metrics_registry

    for route, counts in sorted(metrics_registry.items()):
        for code, count in counts.items():
            lines.append(f'localdeploy_http_requests_total{{route="{route}",code="{code}"}} {count}')

    return "\n".join(lines) + "\n"
