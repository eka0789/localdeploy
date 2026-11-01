"""SSL certificate status via Traefik's acme.json (when available)."""
from __future__ import annotations

import fnmatch
import json
from datetime import timedelta

from ..core.config import settings
from ..core.db import utcnow


def read_certificates() -> list[dict]:
    """Parse acme.json and return [{'domain', 'expires_at', 'issuer'}]."""
    path = settings.acme_json_path
    if not path:
        return []
    try:
        raw = open(path, encoding="utf-8").read()
        data = json.loads(raw or "{}")
    except OSError:
        return []
    except json.JSONDecodeError:
        return []

    certs: list[dict] = []
    for _resolver, body in data.items():
        for cert in body.get("Certificates") or []:
            pem = cert.get("certificate") or ""
            domain_main = (cert.get("domain") or {}).get("main", "")
            expires_at = _pem_not_after(pem)
            certs.append({
                "domain": domain_main,
                "sans": (cert.get("domain") or {}).get("sans", []),
                "expires_at": expires_at,
            })
    return certs


def _pem_not_after(pem: str):
    if not pem:
        return None
    try:
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(pem.encode())
        # normalize to naive UTC to match stored timestamps
        return cert.not_valid_after_utc.replace(tzinfo=None)
    except Exception:
        return None


def refresh_domain_ssl_status(session) -> int:
    """Update ApplicationDomain ssl_status/ssl_expires_at from live certificates."""
    from ..models.application import ApplicationDomain

    certs = read_certificates()
    if not certs:
        return 0
    now = utcnow()
    updated = 0
    for domain in session.query(ApplicationDomain).filter_by(ssl_enabled=True).all():
        for cert in certs:
            pattern = cert["domain"]
            if fnmatch.fnmatch(domain.hostname, pattern.replace("*.", "*.")) or domain.hostname == pattern:
                domain.ssl_status = "issued"
                domain.ssl_issuer = domain.ssl_issuer or "Let's Encrypt"
                if cert["expires_at"]:
                    domain.ssl_expires_at = cert["expires_at"]
                    if cert["expires_at"] < now + timedelta(days=14):
                        domain.ssl_status = "expiring"
                updated += 1
                break
    session.commit()
    return updated
