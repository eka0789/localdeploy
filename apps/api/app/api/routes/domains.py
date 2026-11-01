"""Domain management with DNS instructions and SSL status."""
from __future__ import annotations

import socket
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.db import get_db
from ...models.application import Application, ApplicationDomain
from ...models.user import User
from ...services.traefik import validate_hostname
from ..deps import get_current_user, record_audit, require_permission, verify_csrf
from ..schemas import DomainCreate, DomainOut

router = APIRouter(prefix="/api/domains", tags=["domains"])


def _out(domain: ApplicationDomain, db: Session) -> DomainOut:
    return DomainOut.model_validate(domain)


@router.get("", response_model=list[DomainOut])
def list_domains(application_id: str | None = None,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(ApplicationDomain).order_by(ApplicationDomain.created_at.desc())
    if application_id:
        query = query.filter(ApplicationDomain.application_id == uuid.UUID(application_id))
    return [_out(d, db) for d in query.all()]


@router.post("", response_model=DomainOut, status_code=201, dependencies=[Depends(verify_csrf)])
def create_domain(payload: DomainCreate, request: Request,
                  user: User = Depends(require_permission("domains.write")), db: Session = Depends(get_db)):
    app = db.query(Application).filter(Application.id == uuid.UUID(payload.application_id),
                                       Application.deleted_at.is_(None)).first()
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if db.query(ApplicationDomain).filter_by(hostname=payload.hostname).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Domain already registered")
    domain = ApplicationDomain(
        application_id=app.id,
        hostname=payload.hostname,
        target_port=payload.target_port,
        ssl_enabled=payload.ssl_enabled,
        ssl_status="disabled" if not payload.ssl_enabled else "pending",
        is_primary=payload.is_primary,
    )
    if payload.is_primary:
        db.query(ApplicationDomain).filter_by(application_id=app.id).update({"is_primary": False})
    db.add(domain)
    db.commit()
    db.refresh(domain)

    # Apply the new routing labels to the running container (if any).
    try:
        from ...services.containers import recreate_container_with_domains

        recreate_container_with_domains(db, app)
    except Exception:
        pass  # container recreation is best-effort; labels apply on next deploy otherwise
    record_audit(db, user, "domains.create", "domain", str(domain.id), {"hostname": domain.hostname}, request)
    return _out(domain, db)


@router.delete("/{domain_id}", dependencies=[Depends(verify_csrf)])
def delete_domain(domain_id: uuid.UUID, request: Request,
                  user: User = Depends(require_permission("domains.write")), db: Session = Depends(get_db)):
    domain = db.query(ApplicationDomain).get(domain_id)
    if domain is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain not found")
    app = domain.application
    hostname = domain.hostname
    db.delete(domain)
    db.commit()
    if app:
        try:
            from ...services.containers import recreate_container_with_domains

            recreate_container_with_domains(db, app)
        except Exception:
            pass
    record_audit(db, user, "domains.delete", "domain", None, {"hostname": hostname}, request)
    return {"ok": True}


@router.post("/{domain_id}/verify")
def verify_domain(domain_id: uuid.UUID, user: User = Depends(require_permission("domains.write")),
                  db: Session = Depends(get_db)):
    domain = db.query(ApplicationDomain).get(domain_id)
    if domain is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain not found")
    hostname = domain.hostname.removeprefix("*.").replace("*", "test") if domain.hostname.startswith("*.") else domain.hostname
    try:
        socket.getaddrinfo(hostname, None)
        domain.verified_at = __import__("app.core.db", fromlist=["utcnow"]).utcnow()
        db.commit()
        return {"resolved": True, "message": f"{hostname} resolves in public DNS"}
    except socket.gaierror:
        return {"resolved": False,
                "message": f"{hostname} does not resolve yet. DNS changes can take up to 48h."}


@router.get("/{domain_id}/dns-instructions")
def dns_instructions(domain_id: uuid.UUID, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    domain = db.query(ApplicationDomain).get(domain_id)
    if domain is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain not found")
    wildcard = domain.hostname.startswith("*")
    app = domain.application
    records = [
        {"type": "A", "name": "@" if not wildcard else "*", "value": "<YOUR_PUBLIC_IP>",
         "note": "Points the domain to your server's public IP"},
        {"type": "AAAA", "name": "@" if not wildcard else "*", "value": "<YOUR_PUBLIC_IPV6>",
         "note": "Optional — IPv6 equivalent"},
    ]
    if wildcard:
        records.append({"type": "A", "name": "*", "value": "<YOUR_PUBLIC_IP>",
                        "note": "Wildcard record covers all subdomains"})
    return {
        "hostname": domain.hostname,
        "application": app.name if app else None,
        "records": records,
        "cloudflare_hint": (
            "If you use Cloudflare, create the same record and enable the proxy (orange cloud), "
            "or set up a Cloudflare Tunnel under Networking — no open ports needed."
        ),
    }


@router.post("/{domain_id}/provision-tunnel")
def provision_domain_tunnel(domain_id: uuid.UUID, payload: dict, request: Request,
                            user: User = Depends(require_permission("domains.write")),
                            db: Session = Depends(get_db)):
    """One-click public exposure: tunnel ingress + DNS CNAME via the Cloudflare API."""
    from ...services import cloudflare

    domain = db.query(ApplicationDomain).get(domain_id)
    if domain is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain not found")
    app = domain.application
    if app is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Domain has no application")

    tunnel_id = str(payload.get("tunnel_id", "")).strip()
    if not tunnel_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tunnel_id is required")

    target_port = domain.target_port or app.container_port
    try:
        report = cloudflare.provision_domain(db, domain, app.slug, target_port, tunnel_id)
        db.commit()
    except cloudflare.CloudflareError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    record_audit(db, user, "domains.provision_tunnel", "domain", str(domain.id),
                 {"hostname": domain.hostname, "tunnel": tunnel_id}, request)
    return report
