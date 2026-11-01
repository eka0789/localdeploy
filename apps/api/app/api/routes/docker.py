"""Docker resource management: engine status, containers, images, networks."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...models.user import User
from ...services.docker_client import docker_service
from ..deps import get_current_user, record_audit, require_permission, verify_csrf

router = APIRouter(prefix="/api/docker", tags=["docker"])

PROTECTED_NETWORKS = {"bridge", "host", "none"}


@router.get("/status")
def docker_status(user: User = Depends(get_current_user)):
    return docker_service.engine_info()


@router.get("/containers")
def list_containers(user: User = Depends(get_current_user)):
    client = docker_service.require()
    containers = []
    for container in client.containers.list(all=True):
        stats_source = container.attrs.get("State", {})
        containers.append({
            "id": container.id[:12],
            "name": container.name,
            "image": container.image.tags[0] if container.image.tags else "<untagged>",
            "status": container.status,
            "state": stats_source.get("Status"),
            "created": container.attrs.get("Created"),
            "ports": container.ports,
            "labels": {k: v for k, v in (container.labels or {}).items() if not k.startswith("traefik.")},
            "managed": (container.labels or {}).get("io.localdeploy.managed") == "true",
        })
    return {"containers": containers}


@router.post("/containers/{container_id}/start", dependencies=[Depends(verify_csrf)])
def start_container(container_id: str, request: Request,
                    user: User = Depends(require_permission("docker.write"))):
    container = docker_service.get_container(container_id)
    if container is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Container not found")
    container.start()
    record_audit_docker(request, user, "docker.container.start", container.name)
    return {"ok": True}


@router.post("/containers/{container_id}/stop", dependencies=[Depends(verify_csrf)])
def stop_container(container_id: str, request: Request,
                   user: User = Depends(require_permission("docker.write"))):
    container = docker_service.get_container(container_id)
    if container is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Container not found")
    container.stop(timeout=30)
    record_audit_docker(request, user, "docker.container.stop", container.name)
    return {"ok": True}


@router.post("/containers/{container_id}/restart", dependencies=[Depends(verify_csrf)])
def restart_container(container_id: str, request: Request,
                      user: User = Depends(require_permission("docker.write"))):
    container = docker_service.get_container(container_id)
    if container is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Container not found")
    container.restart(timeout=30)
    record_audit_docker(request, user, "docker.container.restart", container.name)
    return {"ok": True}


@router.delete("/containers/{container_id}", dependencies=[Depends(verify_csrf)])
def remove_container(container_id: str, request: Request,
                     user: User = Depends(require_permission("docker.write"))):
    container = docker_service.get_container(container_id)
    if container is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Container not found")
    name = container.name
    container.remove(force=True)
    record_audit_docker(request, user, "docker.container.remove", name)
    return {"ok": True}


@router.get("/images")
def list_images(user: User = Depends(get_current_user)):
    client = docker_service.require()
    images = []
    for image in client.images.list():
        if not image.tags:
            continue
        attrs = image.attrs
        images.append({
            "id": image.id.replace("sha256:", "")[:12],
            "tags": image.tags,
            "size_mb": round(attrs.get("Size", 0) / 1024 / 1024, 1),
            "created": attrs.get("Created"),
        })
    images.sort(key=lambda i: i["created"] or "", reverse=True)
    return {"images": images[:200]}


@router.delete("/images/{image_id}", dependencies=[Depends(verify_csrf)])
def remove_image(image_id: str, request: Request,
                 user: User = Depends(require_permission("docker.write"))):
    client = docker_service.require()
    try:
        client.images.remove(image_id, force=False)
    except Exception as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot remove image: {exc}")
    record_audit_docker(request, user, "docker.image.remove", image_id)
    return {"ok": True}


@router.get("/networks")
def list_networks(user: User = Depends(get_current_user)):
    client = docker_service.require()
    networks = [{
        "id": net.id[:12],
        "name": net.name,
        "driver": net.attrs.get("Driver"),
        "internal": net.attrs.get("Internal", False),
        "containers": [c.get("Name") for c in (net.attrs.get("Containers") or {}).values()],
    } for net in client.networks.list()]
    return {"networks": networks}


@router.post("/networks", status_code=201, dependencies=[Depends(verify_csrf)])
def create_network(payload: dict, request: Request,
                   user: User = Depends(require_permission("docker.write"))):
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 100:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid network name")
    client = docker_service.require()
    if client.networks.list(names=[name]):
        raise HTTPException(status.HTTP_409_CONFLICT, "Network already exists")
    net = client.networks.create(name, driver=payload.get("driver") or "bridge")
    record_audit_docker(request, user, "docker.network.create", name)
    return {"ok": True, "id": net.id[:12]}


@router.delete("/networks/{name}", dependencies=[Depends(verify_csrf)])
def delete_network(name: str, request: Request,
                   user: User = Depends(require_permission("docker.write"))):
    if name in PROTECTED_NETWORKS or name == "localdeploy-network":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This network is protected")
    client = docker_service.require()
    try:
        net = client.networks.get(name)
        net.remove()
    except Exception as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot remove network: {exc}")
    record_audit_docker(request, user, "docker.network.remove", name)
    return {"ok": True}


def record_audit_docker(request: Request, user: User, action: str, target: str) -> None:
    from ..deps import record_audit

    db = request.app.state.db_session_factory() if hasattr(request.app.state, "db_session_factory") else None
    if db is None:
        from ...core.db import SessionLocal

        db = SessionLocal()
    try:
        record_audit(db, user, action, "docker", None, {"target": target}, request)
    finally:
        db.close()
