"""Public networking: mode selection (public IP vs Cloudflare Tunnel), tunnels, guidance."""
from __future__ import annotations

import ipaddress
import socket

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.db import get_db, utcnow
from ...core.security import encrypt_secret
from ...models.infrastructure import ServerSetting, TunnelConnection
from ...models.user import User
from ...services import tunnel as tunnel_service
from ...services.docker_client import docker_service
from ..deps import get_current_user, record_audit, require_permission, verify_csrf
from ..schemas import NetworkingModeUpdate, TunnelCreate, TunnelOut

router = APIRouter(prefix="/api/networking", tags=["networking"])

_public_ip_cache: dict = {"ip": None, "ts": 0.0}
import time

MODE_KEY = "networking.mode"


@router.get("/info")
def networking_info(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Current networking mode + guidance for each mode."""
    mode_setting = db.query(ServerSetting).filter_by(key=MODE_KEY).first()
    mode = (mode_setting.value or {}).get("mode", "public-ip") if mode_setting else "public-ip"
    return {
        "mode": mode,
        "public_ip": _detect_public_ip(),
        "local_ip": _detect_local_ip(),
        "docker_available": docker_service.available,
        "traefik": {
            "http_entrypoint": settings.traefik_entrypoint_http,
            "https_entrypoint": settings.traefik_entrypoint_https,
            "cert_resolver": settings.traefik_cert_resolver,
        },
        "modes": {
            "public-ip": {
                "title": "Public IP + port forwarding",
                "prerequisites": [
                    "A public IP address (static preferred) or a dynamic DNS service",
                    "Router port forwarding: TCP 80 and 443 → this server",
                    "A firewall that allows inbound traffic only on 80/443",
                    "DNS A/AAAA records pointing your domains to the public IP",
                ],
                "ssl": "Let's Encrypt HTTP-01 challenge via Traefik (automatic)",
                "never_do": [
                    "Never expose the Docker socket (2375/2376) to the internet",
                    "Never forward database ports — apps reach databases over the internal Docker network",
                ],
            },
            "cloudflare-tunnel": {
                "title": "Cloudflare Tunnel (no open ports)",
                "prerequisites": [
                    "A Cloudflare account with a domain in Cloudflare DNS",
                    "Create a tunnel in Zero Trust → Networks → Tunnels and copy the token",
                    "Public hostnames mapped to http://<app-container>:<port> over the LocalDeploy network",
                ],
                "ssl": "Handled by Cloudflare edge ( Flexible / Full / Full-strict )",
                "advantages": ["No port forwarding", "Hides your home IP", "Works behind CGNAT"],
            },
        },
    }


@router.put("/mode", dependencies=[Depends(verify_csrf)])
def set_mode(payload: NetworkingModeUpdate, request: Request,
             user: User = Depends(require_permission("networking.write")),
             db: Session = Depends(get_db)):
    setting = db.query(ServerSetting).filter_by(key=MODE_KEY).first()
    if setting is None:
        setting = ServerSetting(key=MODE_KEY, value={})
        db.add(setting)
    setting.value = {"mode": payload.mode, "public_ip": payload.public_ip}
    db.commit()
    record_audit(db, user, "networking.mode", "settings", None, {"mode": payload.mode}, request)
    return {"ok": True, "mode": payload.mode}# ------------------------------------------------------------------ tunnels

@router.get("/tunnels", response_model=list[TunnelOut])
def list_tunnels(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tunnels = db.query(TunnelConnection).order_by(TunnelConnection.created_at).all()
    out = []
    for tunnel in tunnels:
        if tunnel.status == "running" or docker_service.available:
            status_info = tunnel_service.tunnel_status(tunnel)
            tunnel.status = status_info["status"]
            tunnel.last_error = status_info.get("message")
            if status_info["status"] == "running":
                tunnel.last_connected_at = utcnow()
    db.commit()
    return tunnels


@router.post("/tunnels", response_model=TunnelOut, status_code=201, dependencies=[Depends(verify_csrf)])
def create_tunnel(payload: TunnelCreate, request: Request,
                  user: User = Depends(require_permission("networking.write")),
                  db: Session = Depends(get_db)):
    if db.query(TunnelConnection).filter_by(name=payload.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "A tunnel with this name already exists")
    tunnel = TunnelConnection(name=payload.name, token_encrypted=encrypt_secret(payload.token))
    db.add(tunnel)
    db.commit()
    db.refresh(tunnel)
    record_audit(db, user, "networking.tunnel.create", "tunnel", str(tunnel.id), {"name": tunnel.name}, request)
    return tunnel


@router.post("/tunnels/{tunnel_id}/start", dependencies=[Depends(verify_csrf)])
def start_tunnel(tunnel_id: str, request: Request,
                 user: User = Depends(require_permission("networking.write")),
                 db: Session = Depends(get_db)):
    tunnel = db.query(TunnelConnection).get(tunnel_id)
    if tunnel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tunnel not found")
    try:
        tunnel_service.start_tunnel(tunnel)
    except Exception as exc:
        tunnel.status = "error"
        tunnel.last_error = str(exc)[:500]
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to start cloudflared: {exc}")
    db.commit()
    record_audit(db, user, "networking.tunnel.start", "tunnel", str(tunnel.id), {}, request)
    return {"ok": True, "status": tunnel.status}


@router.post("/tunnels/{tunnel_id}/stop", dependencies=[Depends(verify_csrf)])
def stop_tunnel(tunnel_id: str, request: Request,
                user: User = Depends(require_permission("networking.write")),
                db: Session = Depends(get_db)):
    tunnel = db.query(TunnelConnection).get(tunnel_id)
    if tunnel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tunnel not found")
    tunnel_service.stop_tunnel(tunnel)
    db.commit()
    record_audit(db, user, "networking.tunnel.stop", "tunnel", str(tunnel.id), {}, request)
    return {"ok": True, "status": tunnel.status}


@router.delete("/tunnels/{tunnel_id}", dependencies=[Depends(verify_csrf)])
def delete_tunnel(tunnel_id: str, request: Request,
                  user: User = Depends(require_permission("networking.write")),
                  db: Session = Depends(get_db)):
    tunnel = db.query(TunnelConnection).get(tunnel_id)
    if tunnel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tunnel not found")
    tunnel_service.stop_tunnel(tunnel)
    db.delete(tunnel)
    db.commit()
    record_audit(db, user, "networking.tunnel.delete", "tunnel", None, {"name": tunnel.name}, request)
    return {"ok": True}


@router.get("/tunnels/{tunnel_id}/status")
def tunnel_status(tunnel_id: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    tunnel = db.query(TunnelConnection).get(tunnel_id)
    if tunnel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tunnel not found")
    return tunnel_service.tunnel_status(tunnel)


# ------------------------------------------------------------------ helpers

def _detect_public_ip() -> str | None:
    if _public_ip_cache["ip"] and time.monotonic() - _public_ip_cache["ts"] < 300:
        return _public_ip_cache["ip"]
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            resp = httpx.get(url, timeout=3.0)
            value = resp.text.strip()
            ipaddress.ip_address(value)
            _public_ip_cache.update({"ip": value, "ts": time.monotonic()})
            return value
        except Exception:
            continue
    return None


def _detect_local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
