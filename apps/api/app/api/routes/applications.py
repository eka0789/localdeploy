"""Application management: CRUD, lifecycle actions, env vars, logs, upload."""
from __future__ import annotations

import asyncio
import re
import uuid

from fastapi import (APIRouter, Depends, HTTPException, Request, UploadFile, WebSocket,
                     WebSocketDisconnect, status)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.db import get_db, utcnow
from ...core.security import decrypt_secret, encrypt_secret
from ...models.application import Application, ApplicationDomain, EnvironmentVariable, WebhookIntegration
from ...models.deployment import DeploymentLog
from ...models.user import User
from ...services.container_logs import log_streams
from ...services.docker_client import docker_service
from ...services.log_hub import log_hub
from ...services.worker import create_deployment, enqueue_deployment
from ..deps import (SESSION_COOKIE, get_current_user, hash_token_ws_auth, record_audit,
                    require_permission, verify_csrf)
from ..schemas import (ApplicationCreate, ApplicationDetail, ApplicationOut, EnvVarCreate,
                       EnvVarOut, EnvVarUpdate)

router = APIRouter(prefix="/api/applications", tags=["applications"])

_slug_re = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:64] or "app"


def _app_out(app: Application, db: Session, detail: bool = False) -> dict:
    domains = db.query(ApplicationDomain).filter_by(application_id=app.id).all()
    data = {
        "id": str(app.id), "project_id": str(app.project_id) if app.project_id else None,
        "name": app.name, "slug": app.slug, "description": app.description,
        "source_type": app.source_type, "project_type": app.project_type,
        "git_url": app.git_url, "git_branch": app.git_branch, "status": app.status,
        "container_name": app.container_name, "container_port": app.container_port,
        "health_check_path": app.health_check_path, "auto_deploy": app.auto_deploy,
        "cpu_limit": app.cpu_limit, "memory_limit_mb": app.memory_limit_mb,
        "last_deployed_at": app.last_deployed_at, "created_at": app.created_at,
        "domain_count": len(domains),
        "domains": [d.hostname for d in domains],
        "replicas": app.replicas or 1,
        "autoscale_enabled": app.autoscale_enabled,
        "autoscale_cpu_threshold": app.autoscale_cpu_threshold,
        "autoscale_min": app.autoscale_min,
        "autoscale_max": app.autoscale_max,
        "is_preview": app.is_preview,
        "preview_of": str(app.preview_of) if app.preview_of else None,
        "pr_number": app.pr_number,
        "enable_previews": app.enable_previews,
        "preview_base_domain": app.preview_base_domain,
        "preview_retention_days": app.preview_retention_days,
        "server_id": str(app.server_id) if app.server_id else None,
    }
    if detail:
        data.update({
            "git_username": app.git_username,
            "dockerfile_path": app.dockerfile_path,
            "docker_compose_path": app.docker_compose_path,
            "docker_image": app.docker_image,
            "install_command": app.install_command,
            "build_command": app.build_command,
            "start_command": app.start_command,
            "container_id": app.container_id,
            "has_git_password": bool(app.git_password_encrypted),
        })
    return data


def _get_app(db: Session, app_id: uuid.UUID) -> Application:
    app = db.query(Application).filter(Application.id == app_id, Application.deleted_at.is_(None)).first()
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return app


@router.get("", response_model=list[ApplicationOut])
def list_applications(project_id: str | None = None, preview_of: str | None = None,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Application).filter(Application.deleted_at.is_(None))
    if project_id:
        query = query.filter(Application.project_id == uuid.UUID(project_id))
    if preview_of:
        query = query.filter(Application.preview_of == uuid.UUID(preview_of))
    apps = query.order_by(Application.created_at.desc()).all()
    return [_app_out(a, db) for a in apps]


@router.post("", response_model=ApplicationOut, status_code=201, dependencies=[Depends(verify_csrf)])
def create_application(payload: ApplicationCreate, request: Request,
                       user: User = Depends(require_permission("applications.write")),
                       db: Session = Depends(get_db)):
    slug = _slugify(payload.name)
    if not _slug_re.match(slug):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Name must produce a slug of 3+ characters (letters, digits, dashes)")
    if db.query(Application).filter(Application.slug == slug).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"An application with slug '{slug}' already exists")

    app = Application(
        name=payload.name,
        slug=slug,
        description=payload.description,
        project_id=uuid.UUID(payload.project_id) if payload.project_id else None,
        source_type=payload.source_type,
        project_type=payload.project_type,
        git_url=payload.git_url,
        git_branch=payload.git_branch or "main",
        git_username=payload.git_username,
        git_password_encrypted=encrypt_secret(payload.git_password) if payload.git_password else None,
        dockerfile_path=payload.dockerfile_path,
        docker_compose_path=payload.docker_compose_path,
        docker_image=payload.docker_image,
        install_command=payload.install_command,
        build_command=payload.build_command,
        start_command=payload.start_command,
        container_port=payload.container_port,
        health_check_path=payload.health_check_path,
        auto_deploy=payload.auto_deploy,
        cpu_limit=payload.cpu_limit,
        memory_limit_mb=payload.memory_limit_mb,
        status="idle",
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    # Auto-create a webhook integration so users can wire Git pushes immediately.
    db.add(WebhookIntegration(
        application_id=app.id, provider="github",
        secret_encrypted=encrypt_secret(uuid.uuid4().hex),
        secret_token=uuid.uuid4().hex,
    ))
    db.commit()
    record_audit(db, user, "applications.create", "application", str(app.id),
                 {"name": app.name, "source_type": app.source_type}, request)
    return _app_out(app, db)


@router.get("/{app_id}", response_model=ApplicationDetail)
def get_application(app_id: uuid.UUID, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    return ApplicationDetail.model_validate(_app_out(app, db, detail=True))


@router.put("/{app_id}", response_model=ApplicationOut, dependencies=[Depends(verify_csrf)])
def update_application(app_id: uuid.UUID, payload: dict, request: Request,
                       user: User = Depends(require_permission("applications.write")),
                       db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    allowed = {
        "name", "description", "source_type", "project_type", "git_url", "git_branch",
        "git_username", "dockerfile_path", "docker_compose_path", "docker_image",
        "install_command", "build_command", "start_command", "container_port",
        "health_check_path", "auto_deploy", "cpu_limit", "memory_limit_mb", "project_id",
        "replicas", "autoscale_enabled", "autoscale_cpu_threshold", "autoscale_min",
        "autoscale_max", "enable_previews", "preview_base_domain",
        "preview_retention_days", "server_id",
    }
    for key, value in payload.items():
        if key not in allowed:
            continue
        if key == "git_password":
            app.git_password_encrypted = encrypt_secret(value) if value else None
        elif key == "project_id":
            app.project_id = uuid.UUID(value) if value else None
        elif key == "server_id":
            app.server_id = uuid.UUID(value) if value else None
        else:
            setattr(app, key, value)
    if payload.get("git_password") is None and "git_password" in payload:
        app.git_password_encrypted = None
    db.commit()
    record_audit(db, user, "applications.update", "application", str(app.id),
                 {"fields": [k for k in payload if k in allowed]}, request)
    return _app_out(app, db)


@router.delete("/{app_id}", dependencies=[Depends(verify_csrf)])
def delete_application(app_id: uuid.UUID, request: Request,
                       user: User = Depends(require_permission("applications.write")),
                       db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    # Stop and remove managed container(s)
    if docker_service.available:
        for ref in (f"ld-{app.slug}",):
            container = docker_service.get_container(ref)
            if container:
                container.remove(force=True)
        import subprocess
        subprocess.run(["docker", "compose", "-p", f"ld-{app.slug}", "down", "--remove-orphans"],
                       capture_output=True, timeout=120)
    app.deleted_at = utcnow()
    app.status = "deleted"
    db.commit()
    log_streams.stop_stream(str(app.id))
    record_audit(db, user, "applications.delete", "application", str(app.id), {"name": app.name}, request)
    return {"ok": True}


# ----------------------------------------------------------------- actions

@router.post("/{app_id}/deploy", status_code=202, dependencies=[Depends(verify_csrf)])
async def deploy_application(app_id: uuid.UUID, request: Request,
                             user: User = Depends(require_permission("applications.deploy")),
                             db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    deployment = create_deployment(db, app, trigger="manual",
                                   created_by=user.id, created_by_name=user.username)
    await enqueue_deployment(deployment)
    record_audit(db, user, "applications.deploy", "application", str(app.id),
                 {"deployment_id": str(deployment.id)}, request)
    return {"deployment_id": str(deployment.id), "status": deployment.status}


@router.post("/{app_id}/upload", status_code=201, dependencies=[Depends(verify_csrf)])
async def upload_source(app_id: uuid.UUID, file: UploadFile,
                        user: User = Depends(require_permission("applications.write")),
                        db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    if not file.filename or not file.filename.lower().endswith((".zip", ".tar.gz", ".tgz", ".tar")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload a .zip, .tar.gz or .tgz archive")
    uploads_dir = settings.workspace_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    dest = uploads_dir / f"{app.slug}.zip"
    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 200 * 1024 * 1024:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Archive exceeds 200 MB")
            fh.write(chunk)
    app.source_type = "upload"
    db.commit()
    record_audit(db, user, "applications.upload_source", "application", str(app.id),
                 {"file": file.filename, "size": size}, request)
    return {"ok": True, "size": size, "file": dest.name}


def _container_action(app_id: uuid.UUID, action: str, request: Request, user: User, db: Session):
    app = _get_app(db, app_id)
    if app.server_id:
        from ...services.deployer import dispatch_remote_container_action

        dispatch_remote_container_action(db, app, action)
        record_audit(db, user, f"applications.{action}", "application", str(app.id),
                     {"remote": True}, request)
        return {"ok": True, "status": app.status, "dispatched": "remote"}
    container = docker_service.get_container(app.container_name or f"ld-{app.slug}")
    if container is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "No container found for this application. Deploy it first.")
    try:
        if action == "start":
            container.start()
            app.status = "running"
        elif action == "stop":
            container.stop(timeout=30)
            app.status = "stopped"
        elif action == "restart":
            container.restart(timeout=30)
            app.status = "running"
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Docker action failed: {exc}")
    db.commit()
    record_audit(db, user, f"applications.{action}", "application", str(app.id), {}, request)
    return {"ok": True, "status": app.status}


@router.post("/{app_id}/start", dependencies=[Depends(verify_csrf)])
def start_app(app_id: uuid.UUID, request: Request,
              user: User = Depends(require_permission("applications.deploy")), db: Session = Depends(get_db)):
    return _container_action(app_id, "start", request, user, db)


@router.post("/{app_id}/stop", dependencies=[Depends(verify_csrf)])
def stop_app(app_id: uuid.UUID, request: Request,
             user: User = Depends(require_permission("applications.deploy")), db: Session = Depends(get_db)):
    return _container_action(app_id, "stop", request, user, db)


@router.post("/{app_id}/restart", dependencies=[Depends(verify_csrf)])
def restart_app(app_id: uuid.UUID, request: Request,
                user: User = Depends(require_permission("applications.deploy")), db: Session = Depends(get_db)):
    return _container_action(app_id, "restart", request, user, db)


@router.post("/{app_id}/scale", dependencies=[Depends(verify_csrf)])
def scale_app(app_id: uuid.UUID, payload: dict, request: Request,
              user: User = Depends(require_permission("applications.deploy")),
              db: Session = Depends(get_db)):
    """Reconcile replica count (Traefik load-balances across containers)."""
    from ...services.scaling import scale_application

    app = _get_app(db, app_id)
    if app.source_type == "compose":
        raise HTTPException(status.HTTP_409_CONFLICT, "Scaling applies to single-container apps")
    desired = int(payload.get("replicas", 1))
    try:
        report = scale_application(db, app, desired)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except DockerUnavailableError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    record_audit(db, user, "applications.scale", "application", str(app.id),
                 {"replicas": desired}, request)
    return {"ok": True, **report}


@router.get("/{app_id}/status")
def app_status(app_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    container = docker_service.get_container(app.container_name or f"ld-{app.slug}")
    return {
        "application_status": app.status,
        "docker_status": container.status if container else None,
        "docker_available": docker_service.available,
    }


# ----------------------------------------------------------------- env vars

@router.get("/{app_id}/env-vars", response_model=list[EnvVarOut])
def list_env(app_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    return [EnvVarOut.model_validate(v) for v in app.env_vars]


@router.post("/{app_id}/env-vars", response_model=EnvVarOut, status_code=201,
             dependencies=[Depends(verify_csrf)])
def create_env(app_id: uuid.UUID, payload: EnvVarCreate, request: Request,
               user: User = Depends(require_permission("applications.write")), db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    if any(v.key == payload.key for v in app.env_vars):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Env var '{payload.key}' already exists")
    var = EnvironmentVariable(
        application_id=app.id, key=payload.key,
        value_encrypted=encrypt_secret(payload.value), is_secret=payload.is_secret,
    )
    db.add(var)
    db.commit()
    db.refresh(var)
    record_audit(db, user, "envvars.create", "application", str(app.id), {"key": payload.key}, request)
    return EnvVarOut.model_validate(var)


@router.put("/{app_id}/env-vars/{var_id}", response_model=EnvVarOut, dependencies=[Depends(verify_csrf)])
def update_env(app_id: uuid.UUID, var_id: uuid.UUID, payload: EnvVarUpdate, request: Request,
               user: User = Depends(require_permission("applications.write")), db: Session = Depends(get_db)):
    var = db.query(EnvironmentVariable).filter_by(id=var_id, application_id=app_id).first()
    if var is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Env var not found")
    var.value_encrypted = encrypt_secret(payload.value)
    if payload.is_secret is not None:
        var.is_secret = payload.is_secret
    db.commit()
    record_audit(db, user, "envvars.update", "application", str(app_id), {"key": var.key}, request)
    return EnvVarOut.model_validate(var)


@router.delete("/{app_id}/env-vars/{var_id}", dependencies=[Depends(verify_csrf)])
def delete_env(app_id: uuid.UUID, var_id: uuid.UUID, request: Request,
               user: User = Depends(require_permission("applications.write")), db: Session = Depends(get_db)):
    var = db.query(EnvironmentVariable).filter_by(id=var_id, application_id=app_id).first()
    if var is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Env var not found")
    key = var.key
    db.delete(var)
    db.commit()
    record_audit(db, user, "envvars.delete", "application", str(app_id), {"key": key}, request)
    return {"ok": True}


@router.get("/{app_id}/env-vars/{var_id}/reveal")
def reveal_env(app_id: uuid.UUID, var_id: uuid.UUID,
               user: User = Depends(require_permission("applications.write")), db: Session = Depends(get_db)):
    var = db.query(EnvironmentVariable).filter_by(id=var_id, application_id=app_id).first()
    if var is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Env var not found")
    return {"key": var.key, "value": decrypt_secret(var.value_encrypted)}


# ----------------------------------------------------------------- webhook config

@router.get("/{app_id}/webhook")
def get_webhook(app_id: uuid.UUID, user: User = Depends(require_permission("applications.write")),
                db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    hook = db.query(WebhookIntegration).filter_by(application_id=app.id).first()
    if hook is None:
        hook = WebhookIntegration(application_id=app.id, provider="generic",
                                  secret_encrypted=encrypt_secret(uuid.uuid4().hex),
                                  secret_token=uuid.uuid4().hex)
        db.add(hook)
        db.commit()
    return {
        "id": str(hook.id), "provider": hook.provider, "branch": hook.branch,
        "is_active": hook.is_active,
        "url": f"{settings.public_base_url}/api/webhooks/{hook.secret_token}",
        "secret": decrypt_secret(hook.secret_encrypted) if hook.provider != "github" else None,
    }


@router.put("/{app_id}/webhook", dependencies=[Depends(verify_csrf)])
def update_webhook(app_id: uuid.UUID, payload: dict, request: Request,
                   user: User = Depends(require_permission("applications.write")), db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    hook = db.query(WebhookIntegration).filter_by(application_id=app.id).first()
    if hook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook integration not found")
    for key in ("provider", "branch", "is_active"):
        if key in payload:
            setattr(hook, key, payload[key])
    if payload.get("regenerate_secret"):
        hook.secret_encrypted = encrypt_secret(uuid.uuid4().hex)
    if payload.get("regenerate_token"):
        hook.secret_token = uuid.uuid4().hex
    db.commit()
    record_audit(db, user, "webhooks.update", "application", str(app.id), {}, request)
    return get_webhook(app_id, user, db)


# ----------------------------------------------------------------- logs

@router.get("/{app_id}/logs")
def app_logs(app_id: uuid.UUID, tail: int = 300,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _get_app(db, app_id)
    tail = max(10, min(tail, 5000))
    container = docker_service.get_container(app.container_name or f"ld-{app.slug}")
    if container is None:
        return {"logs": [], "container": None}
    logs = container.logs(tail=tail, timestamps=True).decode(errors="replace")
    lines = [line for line in logs.splitlines() if line.strip()]
    return {"logs": lines, "container": container.name}


@router.websocket("/{app_id}/logs/stream")
async def app_logs_stream(websocket: WebSocket, app_id: uuid.UUID, db: Session = Depends(get_db)):
    """Live application log stream over WebSocket (cookie session auth)."""
    from ...core.db import utcnow
    from ...models.user import UserSession

    token = websocket.cookies.get(SESSION_COOKIE)
    session_row = (db.query(UserSession)
                   .filter(UserSession.token_hash == hash_token_ws_auth(token or ""),
                           UserSession.revoked_at.is_(None))
                   .first() if token else None)
    if session_row is None or session_row.expires_at < utcnow():
        await websocket.close(code=4401)
        return

    app = db.query(Application).filter(Application.id == app_id).first()
    if app is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    subscriber = await log_hub.subscribe(f"applogs:{app_id}")
    container_ref = app.container_name or f"ld-{app.slug}"
    started = log_streams.ensure_stream(str(app.id), container_ref)
    if not started:
        await websocket.send_json({"message": "Docker stream unavailable (engine offline or container missing)"})
    try:
        while True:
            message = await subscriber.queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        await log_hub.unsubscribe(subscriber)


@router.websocket("/{app_id}/terminal")
async def app_terminal(websocket: WebSocket, app_id: uuid.UUID, db: Session = Depends(get_db)):
    """Interactive container shell over WebSocket (docker exec, cookie auth)."""
    from ...core.db import utcnow
    from ...models.user import UserSession

    token = websocket.cookies.get(SESSION_COOKIE)
    session_row = (db.query(UserSession)
                   .filter(UserSession.token_hash == hash_token_ws_auth(token or ""),
                           UserSession.revoked_at.is_(None))
                   .first() if token else None)
    if session_row is None or session_row.expires_at < utcnow():
        await websocket.close(code=4401)
        return

    app_row = db.query(Application).filter(Application.id == app_id).first()
    if app_row is None:
        await websocket.close(code=4404)
        return

    container = docker_service.get_container(app_row.container_name or f"ld-{app_row.slug}")
    await websocket.accept()
    if container is None:
        await websocket.send_json({"data": "Container is not running - deploy or start it first.\r\n"})
        await websocket.close()
        return

    import threading

    client = docker_service.require()
    try:
        exec_id = client.api.exec_create(
            container.id,
            cmd=["/bin/sh", "-c", "command -v bash >/dev/null 2>&1 && exec bash || exec sh"],
            stdin=True, tty=True,
        )["Id"]
        sock = client.api.exec_start(exec_id, socket=True, tty=True)
        client.api.exec_resize(exec_id, height=30, width=100)
    except Exception as exc:
        await websocket.send_json({"data": f"Failed to attach: {exc}\r\n"})
        await websocket.close()
        return

    stop_event = threading.Event()
    loop = asyncio.get_running_loop()  # the uvicorn loop that owns this websocket

    def pump_output():
        try:
            while not stop_event.is_set():
                data = sock.read(4096)  # exec_start(socket=True) returns a SocketIO
                if not data:
                    break
                text = data.decode(errors="replace")
                asyncio.run_coroutine_threadsafe(
                    websocket.send_json({"data": text}), loop).result(timeout=5)
        except Exception:
            pass
        finally:
            stop_event.set()

    threading.Thread(target=pump_output, daemon=True).start()

    try:
        while not stop_event.is_set():
            message = await websocket.receive_json()
            if message.get("type") == "resize":
                try:
                    client.api.exec_resize(exec_id, height=int(message.get("rows", 30)),
                                           width=int(message.get("cols", 100)))
                except Exception:
                    pass
            else:
                data = message.get("data", "")
                if data:
                    sock._sock.sendall(data.encode())  # raw socket beneath the SocketIO
    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
        try:
            sock.close()
            sock._sock.close()
        except Exception:
            pass
        _ = loop  # reference kept: sends are marshalled onto the running loop
