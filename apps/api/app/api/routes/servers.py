"""Multi-server management + the agent-facing API.

Agents run on remote Docker hosts, dial OUT to this API (no inbound ports),
authenticate with a server token (lds_…), report heartbeats and execute queued
commands. Deployments targeting a remote server are dispatched as commands;
the agent streams build logs back through /api/agent/logs.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...core.security import hash_token, new_session_token
from ...models.application import Application
from ...models.deployment import Deployment, DeploymentLog
from ...models.infrastructure import Server, ServerCommand
from ...models.user import User
from ..deps import get_current_user, record_audit, require_permission, verify_csrf

router = APIRouter(prefix="/api", tags=["servers"])

ONLINE_WINDOW = timedelta(seconds=60)


# ------------------------------------------------------------------ management (dashboard)

class ServerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


def _view(server: Server) -> dict:
    online = server.last_seen_at is not None and (utcnow() - server.last_seen_at) < ONLINE_WINDOW
    return {
        "id": str(server.id),
        "name": server.name,
        "status": "online" if online else ("offline" if server.last_seen_at else "pending"),
        "agent_version": server.agent_version,
        "last_seen_at": server.last_seen_at.isoformat() if server.last_seen_at else None,
        "cpu_percent": server.cpu_percent,
        "memory_used_mb": server.memory_used_mb,
        "memory_total_mb": server.memory_total_mb,
        "container_count": server.container_count,
        "running_count": server.running_count,
        "labels": server.labels or {},
        "token_prefix": server.token_prefix,
        "created_at": server.created_at.isoformat(),
    }


def _server_by_token(db: Session, token: str) -> Server:
    row = db.query(Server).filter(Server.token_hash == hash_token(token)).first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid server token")
    return row


@router.get("/servers")
def list_servers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_view(s) for s in db.query(Server).order_by(Server.created_at).all()]


@router.post("/servers", status_code=201, dependencies=[Depends(verify_csrf)])
def create_server(payload: ServerCreate, request: Request,
                  user: User = Depends(require_permission("settings.write")),
                  db: Session = Depends(get_db)):
    if db.query(Server).filter_by(name=payload.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Server name already exists")
    token = "lds_" + new_session_token()
    server = Server(name=payload.name, token_hash=hash_token(token), token_prefix=token[:12])
    db.add(server)
    db.commit()
    db.refresh(server)
    record_audit(db, user, "servers.create", "server", str(server.id), {"name": server.name}, request)
    return {
        **_view(server),
        "token": token,  # shown exactly once
        "install_hint": (
            "On the remote host with Docker + Python 3.11+: "
            "set LOCALDEPLOY_API_URL, LOCALDEPLOY_SERVER_TOKEN, then run python agent.py "
            "(see apps/agent/README.md)."
        ),
    }


@router.post("/servers/{server_id}/regenerate-token", dependencies=[Depends(verify_csrf)])
def regenerate_token(server_id: uuid.UUID, request: Request,
                     user: User = Depends(require_permission("settings.write")),
                     db: Session = Depends(get_db)):
    server = db.query(Server).get(server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Server not found")
    token = "lds_" + new_session_token()
    server.token_hash = hash_token(token)
    server.token_prefix = token[:12]
    server.status = "pending"
    db.commit()
    record_audit(db, user, "servers.regenerate_token", "server", str(server.id), {}, request)
    return {"ok": True, "token": token}


@router.delete("/servers/{server_id}", dependencies=[Depends(verify_csrf)])
def delete_server(server_id: uuid.UUID, request: Request,
                  user: User = Depends(require_permission("settings.write")),
                  db: Session = Depends(get_db)):
    server = db.query(Server).get(server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Server not found")
    apps = db.query(Application).filter(Application.server_id == server_id,
                                        Application.deleted_at.is_(None)).count()
    if apps:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{apps} application(s) still target this server. Reassign them first.")
    db.query(ServerCommand).filter_by(server_id=server_id).delete()
    db.delete(server)
    db.commit()
    record_audit(db, user, "servers.delete", "server", None, {"name": server.name}, request)
    return {"ok": True}


# ------------------------------------------------------------------ agent API

@router.post("/agent/hello")
def agent_hello(request: Request, payload: dict, db: Session = Depends(get_db)):
    """Agent heartbeat: update stats, return queued commands (marked sent)."""
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    server = _server_by_token(db, token)
    server.last_seen_at = utcnow()
    server.agent_version = str(payload.get("agent_version") or server.agent_version)
    server.cpu_percent = float(payload.get("cpu_percent") or 0)
    server.memory_used_mb = float(payload.get("memory_used_mb") or 0)
    server.memory_total_mb = float(payload.get("memory_total_mb") or 0)
    server.container_count = int(payload.get("container_count") or 0)
    server.running_count = int(payload.get("running_count") or 0)
    if payload.get("labels"):
        server.labels = payload["labels"]
    db.commit()

    commands = (db.query(ServerCommand)
                .filter_by(server_id=server.id, status="queued")
                .order_by(ServerCommand.created_at)
                .all())
    result = []
    for command in commands:
        command.status = "sent"
        result.append({
            "command_id": str(command.id),
            "type": command.command_type,
            "payload": command.payload,
        })
    db.commit()
    return {"ok": True, "commands": result}


@router.post("/agent/logs")
def agent_logs(request: Request, payload: dict, db: Session = Depends(get_db)):
    """Agent streams deployment log lines; persisted + fanned out to WS."""
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    _server_by_token(db, token)

    deployment_id = payload.get("deployment_id")
    lines = payload.get("lines") or []
    if not deployment_id or not isinstance(lines, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "deployment_id and lines[] are required")
    deployment = db.query(Deployment).get(uuid.UUID(str(deployment_id)))
    if deployment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")

    from ...services.log_hub import log_hub

    seq = (db.query(DeploymentLog)
           .filter(DeploymentLog.deployment_id == deployment.id)
           .count())
    for line in lines:
        seq += 1
        text = str(line.get("message", ""))[:4000]
        db.add(DeploymentLog(
            deployment_id=deployment.id, sequence=seq,
            stream=str(line.get("stream", "stdout"))[:10], message=text,
        ))
        log_hub.publish_sync(f"deploy:{deployment.id}", {
            "deployment_id": str(deployment.id), "sequence": seq,
            "stream": line.get("stream", "stdout"), "message": text,
        })
    db.commit()
    return {"ok": True, "count": len(lines)}


@router.post("/agent/result")
def agent_result(request: Request, payload: dict, db: Session = Depends(get_db)):
    """Agent reports a finished command."""
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    server = _server_by_token(db, token)

    command_id = payload.get("command_id")
    command = db.query(ServerCommand).get(uuid.UUID(str(command_id))) if command_id else None
    if command is None or command.server_id != server.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Command not found")

    ok = bool(payload.get("ok"))
    command.status = "done" if ok else "failed"
    command.result = payload.get("result") or {}
    command.error = payload.get("error")
    command.finished_at = utcnow()

    # update the deployment/application for deploy commands
    if command.command_type == "deploy" and command.deployment_id:
        deployment = db.query(Deployment).get(command.deployment_id)
        app = db.query(Application).get(deployment.application_id) if deployment else None
        if deployment:
            from datetime import datetime

            finished = utcnow()
            deployment.finished_at = finished
            if deployment.started_at:
                deployment.build_duration_ms = int((finished - deployment.started_at).total_seconds() * 1000)
            if ok:
                result = command.result or {}
                deployment.status = "success"
                deployment.image_tag = result.get("image_tag")
                if app:
                    app.status = "running"
                    app.container_id = result.get("container_id")
                    app.container_name = result.get("container_name")
                    app.last_deployed_at = finished
            else:
                deployment.status = "failed"
                deployment.error_message = (payload.get("error") or "Remote agent failed")[:2000]
                if app:
                    app.status = "error"
        from ...services.log_hub import log_hub

        log_hub.publish_sync("system", {
            "type": "deployment", "level": "success" if ok else "error",
            "message": (f"Remote deployment on '{server.name}' "
                        f"{'succeeded' if ok else 'failed: ' + str(payload.get('error'))[:200]}"),
            "deployment_id": str(command.deployment_id) if command.deployment_id else None,
        })
    db.commit()
    return {"ok": True}
