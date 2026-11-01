"""Container lifecycle helpers shared by routes (domain changes, compose actions)."""
from __future__ import annotations

import socket
import time

import httpx

from ..core.config import settings
from ..core.security import decrypt_secret
from ..models.application import Application, ApplicationDomain, EnvironmentVariable
from .docker_client import docker_service
from .log_hub import log_hub
from .traefik import traefik_labels


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def recreate_container_with_domains(session, app: Application) -> dict:
    """Recreate the running container to apply updated Traefik labels.

    Keeps the current image; the old container is only removed after the new
    one responds on its health endpoint (same safety as deployments).
    """
    client = docker_service.require()
    current = docker_service.get_container(app.container_name or f"ld-{app.slug}")
    if current is None:
        return {"recreated": False, "reason": "no running container"}
    tags = current.image.tags or []
    if not tags:
        return {"recreated": False, "reason": "container image has no tag"}

    image = tags[0]
    port = app.container_port
    env_map = {
        v.key: decrypt_secret(v.value_encrypted)
        for v in session.query(EnvironmentVariable).filter_by(application_id=app.id).all()
    }
    domains = session.query(ApplicationDomain).filter_by(application_id=app.id).all()
    labels = {"io.localdeploy.managed": "true", "io.localdeploy.application": str(app.id)}
    labels.update(traefik_labels(app.slug, [(d.hostname, d.target_port, d.ssl_enabled) for d in domains], port))

    health_port = _free_loopback_port()
    tmp_name = f"ld-{app.slug}-recreate"
    new_container = client.containers.run(
        image=image,
        name=tmp_name,
        detach=True,
        environment=env_map,
        labels=labels,
        network=settings.deploy_network,
        ports={f"{port}/tcp": ("127.0.0.1", health_port)},
        mem_limit=f"{app.memory_limit_mb}m" if app.memory_limit_mb else None,
        nano_cpus=int((app.cpu_limit or 0) * 1e9) or None,
        restart_policy={"Name": "unless-stopped"},
    )

    url = f"http://127.0.0.1:{health_port}{app.health_check_path or '/'}"
    healthy = False
    deadline = time.monotonic() + 60
    with httpx.Client(timeout=3.0) as http:
        while time.monotonic() < deadline:
            try:
                resp = http.get(url)
                if resp.status_code < 500:
                    healthy = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)

    if not healthy:
        new_container.remove(force=True)
        return {"recreated": False, "reason": "health check failed; previous container kept"}

    current.remove(force=True)
    new_container.rename(f"ld-{app.slug}")
    app.container_id = new_container.id
    app.container_name = new_container.name
    session.commit()
    log_hub.publish_sync("system", {
        "type": "application", "level": "info",
        "message": f"Container for '{app.name}' recreated with updated routing labels",
        "application_id": str(app.id),
    })
    return {"recreated": True}
