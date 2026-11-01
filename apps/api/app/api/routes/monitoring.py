"""Monitoring: server snapshot, history, per-app metrics, dashboard overview, Prometheus."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.db import get_db, utcnow
from ...models.application import Application
from ...models.deployment import Deployment
from ...models.monitoring import ApplicationMetric, ServerMetric
from ...models.user import AuditLog
from ...services.monitor import latest_application_metrics, server_snapshot
from ..deps import get_current_user
from ...models.user import User

router = APIRouter(prefix="/api", tags=["monitoring"])


@router.get("/monitoring/server")
def monitoring_server(user: User = Depends(get_current_user)):
    return server_snapshot()


@router.get("/monitoring/server/history")
def monitoring_history(hours: float = Query(default=6, gt=0, le=168),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cutoff = utcnow() - timedelta(hours=hours)
    rows = (db.query(ServerMetric)
            .filter(ServerMetric.sampled_at >= cutoff)
            .order_by(ServerMetric.sampled_at).all())
    # Downsample to ~200 points for charting
    step = max(1, len(rows) // 200)
    return [{
        "sampled_at": r.sampled_at.isoformat(),
        "cpu_percent": r.cpu_percent,
        "memory_percent": r.memory_percent,
        "memory_used_mb": r.memory_used_mb,
        "disk_percent": r.disk_percent,
        "net_rx_bps": r.net_rx_bytes,
        "net_tx_bps": r.net_tx_bytes,
    } for r in rows[::step]]


@router.get("/monitoring/applications")
def monitoring_applications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    latest = latest_application_metrics(db)
    apps = db.query(Application).filter(Application.deleted_at.is_(None)).all()
    result = []
    for app in apps:
        metric = latest.get(str(app.id))
        result.append({
            "application_id": str(app.id),
            "name": app.name,
            "slug": app.slug,
            "status": app.status,
            "project_type": app.project_type,
            "cpu_percent": metric["cpu_percent"] if metric else 0,
            "memory_usage_mb": metric["memory_usage_mb"] if metric else 0,
            "memory_limit_mb": metric["memory_limit_mb"] if metric else 0,
            "net_rx_bytes": metric["net_rx_bytes"] if metric else 0,
            "net_tx_bytes": metric["net_tx_bytes"] if metric else 0,
            "sampled_at": metric["sampled_at"] if metric else None,
        })
    return {"applications": result}


@router.get("/monitoring/applications/{app_id}/history")
def monitoring_app_history(app_id: str, hours: float = Query(default=6, gt=0, le=168),
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cutoff = utcnow() - timedelta(hours=hours)
    rows = (db.query(ApplicationMetric)
            .filter(ApplicationMetric.application_id == app_id,
                    ApplicationMetric.sampled_at >= cutoff)
            .order_by(ApplicationMetric.sampled_at).all())
    step = max(1, len(rows) // 200)
    return [{
        "sampled_at": r.sampled_at.isoformat(),
        "cpu_percent": r.cpu_percent,
        "memory_usage_mb": r.memory_usage_mb,
        "net_rx_bytes": r.net_rx_bytes,
        "net_tx_bytes": r.net_tx_bytes,
    } for r in rows[::step]]


@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Dashboard aggregate: widgets + recent activity."""
    apps = db.query(Application).filter(Application.deleted_at.is_(None)).all()
    day_ago = utcnow() - timedelta(hours=24)
    failed_24h = (db.query(Deployment)
                  .filter(Deployment.status.in_(("failed", "timed_out")),
                          Deployment.created_at >= day_ago).count())
    recent_deployments = (db.query(Deployment)
                          .order_by(Deployment.created_at.desc()).limit(8).all())
    recent_activity = (db.query(AuditLog)
                       .order_by(AuditLog.created_at.desc()).limit(12).all())

    deployments_out = []
    app_names = {str(a.id): a.name for a in apps}
    for d in recent_deployments:
        deployments_out.append({
            "id": str(d.id), "application_id": str(d.application_id),
            "application_name": app_names.get(str(d.application_id), "—"),
            "status": d.status, "trigger": d.trigger,
            "git_message": d.git_message, "created_at": d.created_at.isoformat(),
            "build_duration_ms": d.build_duration_ms,
        })

    return {
        "applications": {
            "total": len(apps),
            "running": sum(1 for a in apps if a.status == "running"),
            "stopped": sum(1 for a in apps if a.status == "stopped"),
            "error": sum(1 for a in apps if a.status == "error"),
            "deploying": sum(1 for a in apps if a.status == "deploying"),
        },
        "deployments_failed_24h": failed_24h,
        "server": server_snapshot(),
        "recent_deployments": deployments_out,
        "recent_activity": [{
            "action": a.action, "username": a.username, "resource_type": a.resource_type,
            "created_at": a.created_at.isoformat(),
        } for a in recent_activity],
    }


@router.get("/metrics-scrape")
def prometheus_metrics(db: Session = Depends(get_db)):
    """Prometheus-compatible text exposition (kept under /api for auth-boundary clarity)."""
    from ...services.prometheus import render_metrics

    return Response(content=render_metrics(db), media_type="text/plain; version=0.0.4")
