"""The deployment engine.

Executes the full deployment lifecycle in a worker thread with its own DB
session. HTTP requests never block on builds — the API only enqueues.

Lifecycle: validate → acquire source → detect runtime → resolve Dockerfile →
build image → create network → start new container → health check → switch
traffic → cleanup. The previous container is only removed after the new one
passes health checks (near-zero-downtime switch, rollback keeps the old image).
"""
from __future__ import annotations

import socket
import time
import traceback
import uuid as uuid_mod
from pathlib import Path

import httpx

from ..core.config import settings
from ..core.db import SessionLocal, utcnow
from ..core.security import decrypt_secret
from ..models.application import Application, ApplicationDomain, EnvironmentVariable
from ..models.deployment import Deployment, DeploymentLog
from .buildpacks import BuildConfig, generate_dockerfile
from .docker_client import DockerUnavailableError, docker_service
from .git import GitError, clone, extract_upload_archive
from .log_hub import log_hub
from .runtime_detect import detect_runtime, suggest_container_port, suggest_health_check_path
from .traefik import traefik_labels

SKIP_DIRS = {".git", "node_modules", "vendor", "__pycache__", ".next", "dist", "build", ".venv"}
DETECT_FILES = {
    "package.json", "composer.json", "requirements.txt", "pyproject.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "gemfile",
    "docker-compose.yml", "docker-compose.yaml", "manage.py",
}


class DeploymentCancelled(Exception):
    pass


class DeploymentFailed(Exception):
    pass


class _Logger:
    """Persists deployment logs and fans them out to WebSocket subscribers."""

    def __init__(self, deployment_id: str, session) -> None:
        self.deployment_id = deployment_id
        self.session = session
        self.seq = 0

    def log(self, message: str, stream: str = "system") -> None:
        self.seq += 1
        self.session.add(
            DeploymentLog(deployment_id=self.deployment_id, sequence=self.seq, message=message, stream=stream)
        )
        self.session.commit()
        log_hub.publish_sync(
            f"deploy:{self.deployment_id}",
            {"deployment_id": str(self.deployment_id), "sequence": self.seq, "stream": stream, "message": message},
        )


def _check_cancelled(session, deployment_id) -> None:
    fresh = session.query(Deployment).get(deployment_id)
    if fresh and fresh.status in ("cancelled",):
        raise DeploymentCancelled("Deployment cancelled by user")


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_deployment(deployment_id: uuid_mod.UUID) -> None:
    """Entry point executed by the worker thread."""
    session = SessionLocal()
    try:
        _execute(session, deployment_id)
    except DeploymentCancelled:
        session.rollback()
        dep = session.query(Deployment).get(deployment_id)
        if dep and dep.status == "running":
            dep.status = "cancelled"
            dep.finished_at = utcnow()
            dep.error_message = "Cancelled"
            session.commit()
    except DeploymentFailed as exc:
        session.rollback()
        dep = session.query(Deployment).get(deployment_id)
        if dep:
            dep.status = "failed"
            dep.finished_at = utcnow()
            dep.error_message = str(exc)[:2000]
            _Logger(dep.id, session).log(f"✖ Deployment failed: {exc}")
            session.commit()
            _notify_result(session, dep)
    except DockerUnavailableError as exc:
        session.rollback()
        dep = session.query(Deployment).get(deployment_id)
        if dep:
            dep.status = "failed"
            dep.finished_at = utcnow()
            dep.error_message = str(exc)[:2000]
            _Logger(dep.id, session).log(f"✖ Docker unavailable: {exc}")
            session.commit()
            _notify_result(session, dep)
    except Exception as exc:  # unexpected — never leave a deployment "running"
        session.rollback()
        dep = session.query(Deployment).get(deployment_id)
        if dep:
            dep.status = "failed"
            dep.finished_at = utcnow()
            dep.error_message = f"{type(exc).__name__}: {exc}"[:2000]
            _Logger(dep.id, session).log(f"✖ Internal error: {exc}\n{traceback.format_exc(limit=3)}")
            session.commit()
            _notify_result(session, dep)
    finally:
        session.close()


def _notify_result(session, deployment) -> None:
    """Fire notification channels for a finished deployment (never raises)."""
    try:
        from .notify import dispatch

        app = session.query(Application).get(deployment.application_id)
        dispatch(session, f"deployment.{deployment.status}", {
            "application_name": app.name if app else "?",
            "status": deployment.status,
            "commit": (deployment.git_commit_sha or "")[:8],
            "error": deployment.error_message,
            "duration": f"{deployment.build_duration_ms / 1000:.1f}s" if deployment.build_duration_ms else None,
        })
    except Exception:
        pass


def _dispatch_remote(session, deployment, app, logger) -> None:
    """Send the deployment job to the remote agent; it reports logs/result back."""
    from ..models.infrastructure import Server, ServerCommand
    from .db_connections import build_env_for_app

    server = session.query(Server).get(app.server_id)
    if server is None:
        raise DeploymentFailed("Target server no longer exists — reassign the application")

    env_map = {
        v.key: decrypt_secret(v.value_encrypted)
        for v in session.query(EnvironmentVariable).filter_by(application_id=app.id).all()
    }
    env_map.update(build_env_for_app(session, app.id))

    from ..models.application import ApplicationDomain
    from .traefik import traefik_labels

    domains = session.query(ApplicationDomain).filter_by(application_id=app.id).all()

    payload = {
        "slug": app.slug,
        "deployment_id": str(deployment.id),
        "source_type": app.source_type,
        "git_url": app.git_url,
        "git_branch": deployment.git_branch or app.git_branch,
        "git_commit_sha": deployment.git_commit_sha,
        "git_username": app.git_username,
        "git_password": decrypt_secret(app.git_password_encrypted) if app.git_password_encrypted else None,
        "dockerfile_path": app.dockerfile_path,
        "docker_compose_path": app.docker_compose_path,
        "docker_image": app.docker_image,
        "install_command": app.install_command,
        "build_command": app.build_command,
        "start_command": app.start_command,
        "container_port": app.container_port,
        "health_check_path": app.health_check_path or "/",
        "env": env_map,
        "cpu_limit": app.cpu_limit,
        "memory_limit_mb": app.memory_limit_mb,
        "replicas": app.replicas or 1,
        "network": settings.deploy_network,
        "labels_extra": {"io.localdeploy.application": str(app.id)},
        "traefik_labels": traefik_labels(
            app.slug, [(d.hostname, d.target_port, d.ssl_enabled) for d in domains], app.container_port),
        "rollback_image": (deployment.meta or {}).get("image_tag"),
    }
    command = ServerCommand(
        server_id=server.id, deployment_id=deployment.id,
        command_type="deploy", payload=payload,
    )
    session.add(command)
    session.commit()
    logger.log(f"→ Dispatched to remote server '{server.name}' (agent picks it up within seconds)")
    logger.log("  Build logs will stream here from the agent.")


def dispatch_remote_container_action(session, app: Application, action: str) -> None:
    """Queue a start/stop/restart command for an app hosted on a remote server."""
    from ..models.infrastructure import ServerCommand

    command = ServerCommand(
        server_id=app.server_id, command_type="container_action",
        payload={"slug": app.slug, "action": action},
    )
    session.add(command)
    session.commit()


def _execute(session, deployment_id: uuid_mod.UUID) -> None:
    deployment = session.query(Deployment).get(deployment_id)
    if deployment is None:
        return
    app = session.query(Application).get(deployment.application_id)
    if app is None:
        raise DeploymentFailed("Application not found")

    logger = _Logger(deployment.id, session)
    started = time.monotonic()

    deployment.status = "running"
    deployment.started_at = utcnow()
    session.commit()

    logger.log(f"▲ LocalDeploy: starting deployment for '{app.name}' (trigger: {deployment.trigger})")
    _check_cancelled(session, deployment.id)

    # -------------------------------------------------------- remote dispatch
    if app.server_id:
        _dispatch_remote(session, deployment, app, logger)
        return

    # -------------------------------------------------------------- rollback
    rollback_to = (deployment.meta or {}).get("rollback_to")
    if rollback_to:
        target = session.query(Deployment).get(rollback_to)
        image_tag = (deployment.meta or {}).get("image_tag") or (target.image_tag if target else None)
        if not image_tag:
            raise DeploymentFailed("Rollback target has no image tag")
        client = docker_service.require()
        try:
            client.images.get(image_tag)
        except Exception as exc:
            raise DeploymentFailed(f"Rollback image {image_tag} no longer exists") from exc
        deployment.image_tag = image_tag
        logger.log(f"⟲ Rolling back to image {image_tag}")
        container_port = app.container_port or 80
        _deploy_single_container(session, app, deployment, image_tag, container_port, logger)
        _finish(session, deployment, app, started)
        return

    # ------------------------------------------------------------------ source
    workdir = Path(settings.workspace_dir) / app.slug / deployment.id.hex[:12]
    container_port = app.container_port or 80
    image_tag = _image_tag(app.slug, deployment)

    runtime = deployment.project_type or app.project_type
    files: list[str] = []

    if app.source_type == "git":
        if not app.git_url:
            raise DeploymentFailed("No Git repository URL configured")
        logger.log(f"→ Cloning {app.git_url} (branch: {deployment.git_branch or app.git_branch or 'default'})")
        try:
            result = clone(
                url=app.git_url,
                branch=deployment.git_branch or app.git_branch,
                dest=workdir,
                username=app.git_username,
                password=decrypt_secret(app.git_password_encrypted) if app.git_password_encrypted else None,
                commit=deployment.git_commit_sha,
            )
        except GitError as exc:
            raise DeploymentFailed(f"Git clone failed: {exc}") from exc
        deployment.git_commit_sha = result.commit_sha
        deployment.git_message = result.commit_message
        logger.log(f"✓ Cloned commit {result.commit_sha[:8]} — {result.commit_message}")
        files = _list_files(workdir)

    elif app.source_type == "upload":
        archive = Path(settings.workspace_dir) / "uploads" / f"{app.slug}.zip"
        if not archive.exists():
            raise DeploymentFailed("No uploaded source archive found for this application")
        logger.log("→ Extracting uploaded source archive")
        try:
            extract_upload_archive(archive, workdir)
        except GitError as exc:
            raise DeploymentFailed(str(exc)) from exc
        files = _list_files(workdir)

    elif app.source_type in ("dockerfile", "compose"):
        if not app.git_url:
            raise DeploymentFailed("This source requires a Git repository URL")
        logger.log(f"→ Cloning {app.git_url}")
        try:
            result = clone(
                url=app.git_url,
                branch=deployment.git_branch or app.git_branch,
                dest=workdir,
                username=app.git_username,
                password=decrypt_secret(app.git_password_encrypted) if app.git_password_encrypted else None,
            )
        except GitError as exc:
            raise DeploymentFailed(f"Git clone failed: {exc}") from exc
        deployment.git_commit_sha = result.commit_sha
        files = _list_files(workdir)

    elif app.source_type == "image":
        if not app.docker_image:
            raise DeploymentFailed("No Docker image configured")
        logger.log(f"→ Pulling prebuilt image {app.docker_image}")
        client = docker_service.require()
        client.images.pull(app.docker_image)
        deployment.image_tag = app.docker_image

    # ------------------------------------------------------- runtime detection
    if app.source_type in ("git", "upload"):
        detection = detect_runtime(files, _make_reader(workdir))
        runtime = detection.runtime
        deployment.project_type = runtime
        logger.log(
            f"→ Runtime detected: {runtime} (confidence {int(detection.confidence * 100)}%) {detection.details or ''}"
        )
        if runtime in ("unknown",):
            raise DeploymentFailed(
                "Could not detect project runtime. Add a Dockerfile, docker-compose.yml, "
                "or set the project type manually in application settings."
            )

    _check_cancelled(session, deployment.id)

    # ------------------------------------------------------- build / provision
    compose_file = workdir / (app.docker_compose_path or "docker-compose.yml")

    if app.source_type == "compose" and compose_file.exists():
        deployment.image_tag = f"compose:{app.slug}"
        _deploy_compose(session, app, deployment, workdir, compose_file, logger)
        _finish(session, deployment, app, started)
        return

    if app.source_type == "image":
        _deploy_image(session, app, deployment, logger)
        _finish(session, deployment, app, started)
        return

    if runtime == "compose" and compose_file.exists():
        deployment.image_tag = f"compose:{app.slug}"
        _deploy_compose(session, app, deployment, workdir, compose_file, logger)
        _finish(session, deployment, app, started)
        return

    dockerfile_path = workdir / (app.dockerfile_path or "Dockerfile")
    if runtime == "dockerfile" or dockerfile_path.exists():
        logger.log(f"→ Using project Dockerfile: {app.dockerfile_path or 'Dockerfile'}")
        context = workdir
    else:
        cfg = BuildConfig(
            runtime=runtime,
            container_port=container_port,
            install_command=app.install_command,
            build_command=app.build_command,
            start_command=app.start_command,
        )
        generated = generate_dockerfile(cfg)
        dockerfile_path = workdir / "Dockerfile"
        dockerfile_path.write_text(generated, encoding="utf-8")
        logger.log("→ Generated Dockerfile (buildpack):")
        for line in generated.splitlines():
            logger.log(f"    {line}", stream="stdout")
        context = workdir

    _check_cancelled(session, deployment.id)
    deployment.image_tag = image_tag
    _build_image(deployment, context, dockerfile_path, image_tag, logger)
    _deploy_single_container(session, app, deployment, image_tag, container_port, logger)
    _finish(session, deployment, app, started)


# ---------------------------------------------------------------------------
# phases
# ---------------------------------------------------------------------------

def _build_image(deployment, context: Path, dockerfile_path: Path, tag: str, logger) -> None:
    import docker.errors

    client = docker_service.require()
    logger.log(f"→ Building image {tag}")
    started = time.monotonic()
    try:
        stream = client.api.build(
            path=str(context),
            dockerfile=dockerfile_path.name,
            tag=tag,
            rm=True,
            forcerm=True,
            decode=True,
            labels={"io.localdeploy.managed": "true", "io.localdeploy.deployment": deployment.id.hex},
        )
        current_step = ""
        for chunk in stream:
            _check_cancelled_build(deployment)
            if "stream" in chunk:
                for line in chunk["stream"].splitlines():
                    line = line.strip()
                    if line and line != current_step:
                        logger.log(line, stream="stdout")
                        if line.startswith("#"):
                            current_step = line
            if "errorDetail" in chunk:
                raise DeploymentFailed(chunk.get("errorDetail", {}).get("message", "Build error"))
            if "error" in chunk:
                raise DeploymentFailed(chunk["error"])
    except DeploymentCancelled:
        raise
    except docker.errors.BuildError as exc:
        raise DeploymentFailed(f"Image build failed: {exc}") from exc
    except docker.errors.DockerException as exc:
        raise DockerUnavailableError(f"Docker build error: {exc}") from exc
    logger.log(f"✓ Image built in {time.monotonic() - started:.1f}s")


def _check_cancelled_build(deployment) -> None:
    session = SessionLocal()
    try:
        _check_cancelled(session, deployment.id)
    finally:
        session.close()


def _deploy_single_container(session, app, deployment, image_tag, container_port, logger) -> None:
    client = docker_service.require()
    docker_service.ensure_network(settings.deploy_network)
    network = client.networks.get(settings.deploy_network)

    env_vars = session.query(EnvironmentVariable).filter_by(application_id=app.id).all()
    env_map = {v.key: decrypt_secret(v.value_encrypted) for v in env_vars}
    # Inject environment variables from linked external databases (Supabase, Neon, Turso, …)
    from .db_connections import build_env_for_app

    for key, value in build_env_for_app(session, app.id).items():
        env_map[key] = value
    if env_map:
        logger.log(f"→ Injecting {len(env_map)} environment variables")

    domains = session.query(ApplicationDomain).filter_by(application_id=app.id).all()
    domain_tuples = [(d.hostname, d.target_port, d.ssl_enabled) for d in domains]
    labels = {"io.localdeploy.managed": "true", "io.localdeploy.application": str(app.id)}
    labels.update(traefik_labels(app.slug, domain_tuples, container_port))

    health_port = _free_loopback_port()
    health_path = app.health_check_path or suggest_health_check_path(app.project_type or "")

    old_container = client.containers.get(f"ld-{app.slug}") if docker_service.get_container(f"ld-{app.slug}") else None
    if old_container:
        old_name = f"ld-{app.slug}-old-{deployment.id.hex[:8]}"
        old_container.rename(old_name)
        logger.log(f"→ Renamed previous container to {old_name} (kept until health check passes)")

    name = f"ld-{app.slug}"
    logger.log(f"→ Starting container {name} (port {container_port})")
    try:
        container = client.containers.run(
            image=image_tag,
            name=name,
            detach=True,
            environment=env_map,
            labels=labels,
            network=settings.deploy_network,
            ports={f"{container_port}/tcp": ("127.0.0.1", health_port)},
            mem_limit=f"{app.memory_limit_mb}m" if app.memory_limit_mb else None,
            nano_cpus=int((app.cpu_limit or 0) * 1e9) or None,
            restart_policy={"Name": "unless-stopped"},
        )
    except Exception as exc:
        if old_container:
            old_container.rename(f"ld-{app.slug}")
        raise DeploymentFailed(f"Failed to start container: {exc}") from exc

    deployment.meta = {**(deployment.meta or {}), "health_port": health_port, "health_path": health_path}
    session.commit()

    # ------------------------------------------------------------ health check
    healthy = _health_check(container, container_port, health_port, health_path, logger, deployment)
    if not healthy:
        container.remove(force=True)
        if old_container:
            old_container.rename(f"ld-{app.slug}")
            logger.log("→ Previous container restored")
        raise DeploymentFailed(
            f"Health check failed: no successful HTTP response on port {container_port}{health_path} "
            f"within {settings.healthcheck_timeout_seconds}s"
        )

    logger.log("✓ Health check passed")
    if old_container:
        old_container.remove(force=True)
        logger.log("→ Removed previous container")

    app.status = "running"
    app.container_id = container.id
    app.container_name = container.name
    app.project_type = app.project_type or deployment.project_type
    app.last_deployed_at = utcnow()
    session.commit()

    # scale out to the configured replica count (Traefik load-balances them)
    if (app.replicas or 1) > 1 and app.source_type != "compose":
        try:
            from .scaling import scale_application

            report = scale_application(session, app, max(1, app.replicas or 1))
            logger.log(f"→ Scaled to {report['desired']} replica(s) (+{report['created']} created)")
        except Exception as exc:
            logger.log(f"⚠ Replica scaling failed (primary is healthy): {exc}")


def _health_check(container, container_port, host_port, path, logger, deployment) -> bool:
    url = f"http://127.0.0.1:{host_port}{path or '/'}"
    deadline = time.monotonic() + settings.healthcheck_timeout_seconds
    logger.log(f"→ Health checking {url} (timeout {settings.healthcheck_timeout_seconds}s)")
    last_error = ""
    with httpx.Client(timeout=3.0) as http:
        while time.monotonic() < deadline:
            if deployment.status == "cancelled":
                raise DeploymentCancelled("Deployment cancelled by user")
            try:
                container.reload()
                if container.status not in ("running", "created", "restarting"):
                    last_error = f"container is {container.status}"
                    logger.log(f"  container state: {container.status}")
                    return False
                resp = http.get(url)
                if resp.status_code < 500:
                    logger.log(f"  HTTP {resp.status_code} OK")
                    return True
                last_error = f"HTTP {resp.status_code}"
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2)
    logger.log(f"  last health check result: {last_error}")
    return False


def _deploy_compose(session, app, deployment, workdir, compose_file, logger) -> None:
    """Deploy via `docker compose` with a scoped project name."""
    import subprocess

    client = docker_service.require()
    docker_service.ensure_network(settings.deploy_network)
    project = f"ld-{app.slug}"
    env_vars = session.query(EnvironmentVariable).filter_by(application_id=app.id).all()

    import os

    env = {**os.environ}
    for v in env_vars:
        env[v.key] = decrypt_secret(v.value_encrypted)
    from .db_connections import build_env_for_app

    env.update(build_env_for_app(session, app.id))
    env["LOCALDEPLOY_NETWORK"] = settings.deploy_network

    logger.log(f"→ Running docker compose (project {project})")
    try:
        result = subprocess.run(
            ["docker", "compose", "-p", project, "-f", str(compose_file),
             "up", "-d", "--build", "--remove-orphans"],
            cwd=str(workdir), capture_output=True, text=True, timeout=settings.deploy_timeout_seconds, env=env,
        )
    except subprocess.TimeoutExpired:
        raise DeploymentFailed("docker compose timed out")
    except FileNotFoundError:
        raise DeploymentFailed("docker compose CLI not found on host")

    output = (result.stdout + result.stderr).strip()
    for line in output.splitlines()[-200:]:
        if line.strip():
            logger.log(line, stream="stderr" if line in (result.stderr or "") else "stdout")
    if result.returncode != 0:
        raise DeploymentFailed(f"docker compose failed (exit {result.returncode})")

    # Track the primary container for status/logs.
    containers = client.containers.list(all=True, filters={"label": f"com.docker.compose.project={project}"})
    running = [c for c in containers if c.status == "running"]
    if not running:
        raise DeploymentFailed("Compose project started but no containers are running")
    primary = running[0]
    app.status = "running"
    app.container_id = primary.id
    app.container_name = primary.name
    app.project_type = "compose"
    app.last_deployed_at = utcnow()
    logger.log(f"✓ Compose project running ({len(running)}/{len(containers)} containers up)")
    session.commit()


def _deploy_image(session, app, deployment, logger) -> None:
    container_port = app.container_port or 80
    _deploy_single_container(session, app, deployment, app.docker_image, container_port, logger)


def _finish(session, deployment, app, started) -> None:
    deployment.status = "success"
    deployment.finished_at = utcnow()
    deployment.build_duration_ms = int((time.monotonic() - started) * 1000)
    logger = _Logger(deployment.id, session)
    logger.log(f"✔ Deployment successful in {deployment.build_duration_ms / 1000:.1f}s")
    session.commit()
    _prune_old_images(session, app)
    _notify_result(session, deployment)
    log_hub.publish_sync("system", {
        "type": "deployment", "level": "success",
        "message": f"Application '{app.name}' deployed successfully",
        "application_id": str(app.id), "deployment_id": str(deployment.id),
    })


KEEP_IMAGES = 3


def _prune_old_images(session, app, keep: int = KEEP_IMAGES) -> None:
    """Delete old deployment images beyond the newest `keep` (disk hygiene)."""
    try:
        if app.source_type == "compose":
            return
        client = docker_service.client()
        if client is None:
            return
        prefix = f"{settings.image_prefix}/{app.slug}:"
        images = [img for img in client.images.list() for tag in (img.tags or []) if tag.startswith(prefix)]
        images.sort(key=lambda i: i.attrs.get("Created", 0), reverse=True)
        running_tag = None
        current = docker_service.get_container(app.container_name or f"ld-{app.slug}")
        if current is not None:
            tags = current.image.tags or []
            running_tag = tags[0] if tags else None
        removed = 0
        for image in images[keep:]:
            if running_tag and running_tag in (image.tags or []):
                continue  # never remove the image the running container uses
            try:
                client.images.remove(image.id, force=False)
                removed += 1
            except Exception:
                continue  # in use by an old container — leave it
        if removed:
            log_hub.publish_sync("system", {
                "type": "deployment", "level": "info",
                "message": f"Pruned {removed} old image(s) for '{app.name}' (keeping {keep})",
                "application_id": str(app.id),
            })
    except Exception:
        pass  # pruning must never fail a deployment


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _image_tag(slug: str, deployment) -> str:
    return f"{settings.image_prefix}/{slug}:{deployment.id.hex[:12]}"


def _list_files(root: Path) -> list[str]:
    files: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in rel.split("/")):
            continue
        files.append(rel)
        if len(files) >= 5000:
            break
    return files


def _make_reader(root: Path):
    def read(rel: str) -> str | None:
        matches = [p for p in root.rglob(rel) if p.is_file()][:1]
        for candidate in (root / rel, *matches):
            try:
                if candidate.exists() and candidate.stat().st_size < 512 * 1024:
                    return candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        return None

    return read


def deployment_runtime_defaults(files: list[str], reader) -> dict:
    detection = detect_runtime(files, reader)
    return {
        "runtime": detection.runtime,
        "confidence": detection.confidence,
        "container_port": suggest_container_port(detection.runtime),
        "health_check_path": suggest_health_check_path(detection.runtime),
        "details": detection.details,
    }
