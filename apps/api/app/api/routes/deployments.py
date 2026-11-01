"""Deployment history, live build logs, cancel, rollback and retry."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...models.application import Application
from ...models.deployment import Deployment, DeploymentLog
from ...models.user import User, UserSession
from ...services.log_hub import log_hub
from ...services.worker import create_deployment, enqueue_deployment
from ..deps import SESSION_COOKIE, get_current_user, hash_token_ws_auth, record_audit, require_permission, verify_csrf
from ..schemas import DeploymentOut

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


def _out(deployment: Deployment, db: Session) -> DeploymentOut:
    return DeploymentOut.model_validate(deployment)


@router.get("", response_model=list[DeploymentOut])
def list_deployments(
    application_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = db.query(Deployment).order_by(Deployment.created_at.desc())
    if application_id:
        query = query.filter(Deployment.application_id == uuid.UUID(application_id))
    if status:
        query = query.filter(Deployment.status == status)
    return [_out(d, db) for d in query.offset(offset).limit(limit).all()]


@router.get("/{deployment_id}", response_model=DeploymentOut)
def get_deployment(deployment_id: uuid.UUID, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    deployment = db.query(Deployment).get(deployment_id)
    if deployment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    return _out(deployment, db)


@router.get("/{deployment_id}/logs")
def deployment_logs(deployment_id: uuid.UUID, after: int = 0,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deployment = db.query(Deployment).get(deployment_id)
    if deployment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    logs = (db.query(DeploymentLog)
            .filter(DeploymentLog.deployment_id == deployment_id, DeploymentLog.sequence > after)
            .order_by(DeploymentLog.sequence).all())
    return {
        "logs": [{"sequence": log.sequence, "stream": log.stream, "message": log.message,
                  "created_at": log.created_at.isoformat()} for log in logs],
        "status": deployment.status,
    }


@router.websocket("/{deployment_id}/stream")
async def deployment_stream(websocket: WebSocket, deployment_id: uuid.UUID,
                            db: Session = Depends(get_db)):
    token = websocket.cookies.get(SESSION_COOKIE)
    row = (db.query(UserSession)
           .filter(UserSession.token_hash == hash_token_ws_auth(token or ""),
                   UserSession.revoked_at.is_(None)).first() if token else None)
    if row is None or row.expires_at < utcnow():
        await websocket.close(code=4401)
        return
    await websocket.accept()
    subscriber = await log_hub.subscribe(f"deploy:{deployment_id}")
    try:
        while True:
            message = await subscriber.queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        await log_hub.unsubscribe(subscriber)


@router.post("/{deployment_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel_deployment(deployment_id: uuid.UUID, request: Request,
                      user: User = Depends(require_permission("applications.deploy")),
                      db: Session = Depends(get_db)):
    deployment = db.query(Deployment).get(deployment_id)
    if deployment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    if deployment.status not in ("queued", "running"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Deployment already finished ({deployment.status})")
    deployment.status = "cancelled"
    deployment.error_message = "Cancelled by user"
    if deployment.status == "queued":
        deployment.finished_at = utcnow()
    db.commit()
    record_audit(db, user, "deployments.cancel", "deployment", str(deployment.id), {}, request)
    return {"ok": True, "status": deployment.status}


@router.post("/{deployment_id}/rollback", status_code=202, dependencies=[Depends(verify_csrf)])
async def rollback_deployment(deployment_id: uuid.UUID, request: Request,
                        user: User = Depends(require_permission("applications.deploy")),
                        db: Session = Depends(get_db)):
    """Redeploy the image of a previous successful deployment (single-container apps)."""
    deployment = db.query(Deployment).get(deployment_id)
    if deployment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    if deployment.status != "success" or not deployment.image_tag:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Rollback requires a successful image-based deployment")
    app = db.query(Application).get(deployment.application_id)
    if app is None or app.source_type == "compose":
        raise HTTPException(status.HTTP_409_CONFLICT, "Rollback is not supported for compose apps")
    new_deployment = create_deployment(db, app, trigger="rollback",
                                       created_by=user.id, created_by_name=user.username)
    new_deployment.meta = {"rollback_to": str(deployment.id), "image_tag": deployment.image_tag}
    new_deployment.git_commit_sha = deployment.git_commit_sha
    db.commit()
    await enqueue_deployment(new_deployment)
    record_audit(db, user, "deployments.rollback", "deployment", str(deployment.id),
                 {"to_deployment": str(deployment.id)}, request)
    return {"deployment_id": str(new_deployment.id), "status": new_deployment.status}


@router.post("/{deployment_id}/retry", status_code=202, dependencies=[Depends(verify_csrf)])
async def retry_deployment(deployment_id: uuid.UUID, request: Request,
                     user: User = Depends(require_permission("applications.deploy")),
                     db: Session = Depends(get_db)):
    deployment = db.query(Deployment).get(deployment_id)
    if deployment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    app = db.query(Application).get(deployment.application_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    new_deployment = create_deployment(db, app, trigger="retry",
                                       created_by=user.id, created_by_name=user.username,
                                       commit_sha=deployment.git_commit_sha)
    await enqueue_deployment(new_deployment)
    record_audit(db, user, "deployments.retry", "deployment", str(deployment.id), {}, request)
    return {"deployment_id": str(new_deployment.id), "status": new_deployment.status}
