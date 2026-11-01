"""Storage: Docker volumes with LocalDeploy metadata + disk summary."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...models.infrastructure import StorageVolume
from ...models.user import User
from ...services.docker_client import docker_service
from ..deps import get_current_user, record_audit, require_permission, verify_csrf

router = APIRouter(prefix="/api/storage", tags=["storage"])

LD_LABEL = "io.localdeploy.managed"


@router.get("/summary")
def storage_summary(user: User = Depends(get_current_user)):
    """Disk usage from the host + Docker system df."""
    import psutil

    from ...core.config import settings

    disk = psutil.disk_usage(str(settings.workspace_dir.resolve().anchor) or "/")
    docker_df = None
    if docker_service.available:
        try:
            client = docker_service.client()
            df = client.df()
            docker_df = {
                "images_size_bytes": sum(i.get("Size", 0) for i in df.get("Images", [])),
                "containers_size_bytes": sum(c.get("SizeRw", 0) or 0 for c in df.get("Containers", [])),
                "volumes_size_bytes": sum(v.get("UsageData", [{}])[0].get("Size", 0)
                                          for v in df.get("Volumes", []) if v.get("UsageData")),
                "build_cache_size_bytes": sum(b.get("Size", 0) for b in df.get("BuildCache", [])),
            }
        except Exception:
            docker_df = None
    return {
        "disk_used_gb": round(disk.used / 1024**3, 2),
        "disk_total_gb": round(disk.total / 1024**3, 2),
        "disk_percent": disk.percent,
        "docker": docker_df,
    }


@router.get("/volumes")
def list_volumes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Live volumes from Docker, enriched with LocalDeploy metadata."""
    if not docker_service.available:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Docker Engine is not reachable")
    client = docker_service.require()
    known = {v.name: v for v in db.query(StorageVolume).all()}
    in_use_names = set()
    for container in client.containers.list(all=True):
        for mount in container.attrs.get("Mounts", []):
            if mount.get("Type") == "volume":
                in_use_names.add(mount.get("Name"))

    result = []
    for volume in client.volumes.list():
        attrs = volume.attrs
        record = known.get(volume.name)
        if record is None and attrs.get("Labels", {}).get(LD_LABEL) == "true":
            record = StorageVolume(
                name=volume.name,
                driver=attrs.get("Driver", "local"),
                labels=attrs.get("Labels") or {},
            )
            db.add(record)
            db.commit()
            known[volume.name] = record
        result.append({
            "id": str(record.id) if record else None,
            "name": volume.name,
            "driver": attrs.get("Driver", "local"),
            "mountpoint": attrs.get("Mountpoint"),
            "in_use": volume.name in in_use_names,
            "managed": (attrs.get("Labels") or {}).get(LD_LABEL) == "true",
            "created_at": record.created_at.isoformat() if record else None,
        })
    result.sort(key=lambda v: (not v["managed"], v["name"]))
    return {"volumes": result}


@router.post("/volumes", status_code=201, dependencies=[Depends(verify_csrf)])
def create_volume(payload: dict, request: Request,
                  user: User = Depends(require_permission("docker.write")), db: Session = Depends(get_db)):
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 100:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid volume name")
    client = docker_service.require()
    try:
        client.volumes.get(name)
        raise HTTPException(status.HTTP_409_CONFLICT, "Volume already exists")
    except HTTPException:
        raise
    except Exception:
        pass  # not found — proceed to create
    volume = client.volumes.create(
        name=name,
        labels={LD_LABEL: "true", "io.localdeploy.created_by": user.username},
    )
    db.add(StorageVolume(name=volume.name, driver="local",
                         labels=volume.attrs.get("Labels") or {}))
    db.commit()
    record_audit(db, user, "storage.volume.create", "volume", None, {"name": name}, request)
    return {"ok": True, "name": volume.name}


@router.delete("/volumes/{name}", dependencies=[Depends(verify_csrf)])
def delete_volume(name: str, request: Request,
                  user: User = Depends(require_permission("docker.write")), db: Session = Depends(get_db)):
    client = docker_service.require()
    for container in client.containers.list(all=True):
        for mount in container.attrs.get("Mounts", []):
            if mount.get("Type") == "volume" and mount.get("Name") == name:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"Volume is in use by container '{container.name}'")
    try:
        volume = client.volumes.get(name)
        volume.remove()
    except Exception as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Volume not found: {exc}")
    record = db.query(StorageVolume).filter_by(name=name).first()
    if record:
        db.delete(record)
        db.commit()
    record_audit(db, user, "storage.volume.delete", "volume", None, {"name": name}, request)
    return {"ok": True}
