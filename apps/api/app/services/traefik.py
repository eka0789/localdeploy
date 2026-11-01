"""Traefik label generation for dynamic reverse proxy routing.

Applications are routed via Docker labels on the shared `localdeploy-network`.
Traefik runs with `exposedByDefault=false`, so only labelled services are routed.
"""
from __future__ import annotations

from ..core.config import settings


def traefik_labels(slug: str, domains: list[tuple[str, int, bool]], container_port: int) -> dict[str, str]:
    """Build router/service labels.

    All containers of an application share ONE service name (`svc-<slug>`) so
    Traefik load-balances across replicas automatically (round-robin).

    `domains` is a list of (hostname, target_port, ssl_enabled).
    """
    labels: dict[str, str] = {
        "traefik.enable": "true",
        "traefik.docker.network": settings.deploy_network,
    }

    service = f"svc-{slug}"
    labels[f"traefik.http.services.{service}.loadbalancer.server.port"] = str(container_port)

    for i, (hostname, target_port, ssl_enabled) in enumerate(domains):
        suffix = f"{slug}-{i}"
        port = target_port or container_port
        # per-domain service override when the domain targets a different port
        effective_service = service
        if port != container_port:
            per_domain = f"svc-{slug}-{i}"
            labels[f"traefik.http.services.{per_domain}.loadbalancer.server.port"] = str(port)
            effective_service = per_domain

        if ssl_enabled:
            labels[f"traefik.http.routers.{suffix}-http.rule"] = f"Host(`{hostname}`)"
            labels[f"traefik.http.routers.{suffix}-http.entrypoints"] = settings.traefik_entrypoint_http
            labels[f"traefik.http.routers.{suffix}-http.middlewares"] = "redirect-to-https"
            labels[f"traefik.http.routers.{suffix}-http.service"] = effective_service

            labels[f"traefik.http.routers.{suffix}.rule"] = f"Host(`{hostname}`)"
            labels[f"traefik.http.routers.{suffix}.entrypoints"] = settings.traefik_entrypoint_https
            labels[f"traefik.http.routers.{suffix}.tls"] = "true"
            labels[f"traefik.http.routers.{suffix}.tls.certresolver"] = settings.traefik_cert_resolver
            labels[f"traefik.http.routers.{suffix}.service"] = effective_service
        else:
            labels[f"traefik.http.routers.{suffix}.rule"] = f"Host(`{hostname}`)"
            labels[f"traefik.http.routers.{suffix}.entrypoints"] = settings.traefik_entrypoint_http
            labels[f"traefik.http.routers.{suffix}.service"] = effective_service

    return labels


def domain_healthcheck_labels(slug: str, hostname: str, port: int, path: str = "/") -> dict[str, str]:
    """Attach healthcheck labels so Traefik removes unhealthy backends."""
    key = f"traefik.http.services.{slug}.loadbalancer.healthcheck"
    return {
        f"{key}.path": path,
        f"{key}.interval": "30s",
        f"{key}.timeout": "5s",
    }


def validate_hostname(hostname: str) -> str | None:
    """Return an error string when invalid, else None. Supports wildcards (*.example.com)."""
    import re

    host = hostname.strip().lower().rstrip(".")
    if len(host) < 3 or len(host) > 253:
        return "Hostname length must be between 3 and 253 characters."
    pattern = re.compile(
        r"^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
    )
    if not pattern.match(host):
        return "Invalid hostname. Use a format like app.example.com or *.example.com."
    return None
