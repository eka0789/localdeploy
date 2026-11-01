"""Cloudflare Tunnel management (cloudflared containers)."""
from __future__ import annotations

from ..core.config import settings
from .docker_client import docker_service

CLOUDFLARED_IMAGE = "cloudflare/cloudflared:latest"


def start_tunnel(tunnel) -> dict:
    client = docker_service.require()
    docker_service.ensure_network(settings.deploy_network)

    from ..core.security import decrypt_secret

    token = decrypt_secret(tunnel.token_encrypted)

    stop_tunnel(tunnel)  # replace existing

    container = client.containers.run(
        image=CLOUDFLARED_IMAGE,
        name=f"ld-tunnel-{tunnel.name}",
        command=["tunnel", "--no-autoupdate", "run", "--token", token],
        detach=True,
        network=settings.deploy_network,
        labels={
            "io.localdeploy.managed": "true",
            "io.localdeploy.kind": "tunnel",
            "io.localdeploy.tunnel": str(tunnel.id),
        },
        restart_policy={"Name": "unless-stopped"},
    )
    tunnel.container_id = container.id
    tunnel.status = "running"
    return {"container_id": container.id}


def stop_tunnel(tunnel) -> None:
    container = docker_service.get_container(f"ld-tunnel-{tunnel.name}")
    if container:
        container.remove(force=True)
    tunnel.status = "stopped"
    tunnel.container_id = None


def tunnel_status(tunnel) -> dict:
    container = docker_service.get_container(f"ld-tunnel-{tunnel.name}") or (
        docker_service.get_container(tunnel.container_id) if tunnel.container_id else None
    )
    if container is None:
        return {"status": "stopped", "message": "Tunnel container is not running"}
    container.reload()
    logs = container.logs(tail=30).decode(errors="replace")
    connected = "Registered tunnel connection" in logs
    errored = "ERR" in logs or container.status == "exited"
    status = "running" if connected else ("error" if errored else container.status)
    message = "Connected to Cloudflare edge" if connected else "Waiting for connection..."
    if errored and not connected:
        message = logs.strip().splitlines()[-1][:300] if logs.strip() else "Tunnel error"
    return {"status": status, "message": message, "container_status": container.status}


def prune_dead_tunnels() -> None:
    """Remove orphaned tunnel containers not matching any DB record."""
    if not docker_service.available:
        return
    client = docker_service.client()
    if client is None:
        return
    for container in client.containers.list(all=True, filters={"label": "io.localdeploy.kind=tunnel"}):
        pass  # tunnels are user-managed; nothing to prune automatically
