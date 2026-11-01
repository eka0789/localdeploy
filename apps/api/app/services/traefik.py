"""Traefik label generation for dynamic reverse proxy routing.

Applications are routed via Docker labels on the shared `localdeploy-network`.
Traefik runs with `exposedByDefault=false`, so only labelled services are routed.
"""
from __future__ import annotations

from ..core.config import settings


def traefik_labels(slug: str, domains: list[tuple[str, int, bool]], container_port: int) -> dict[str, str]:
    """Build router/service labels.

    `domains` is a list of (hostname, target_port, ssl_enabled).
    Falls back to an internal-only service label when no domain is attached.
    """
    labels: dict[str, str] = {
        "traefik.enable": "true",
        "traefik.docker.network": settings.deploy_network,
    }

    routers: list[str] = []
    for i, (hostname, target_port, ssl_enabled) in enumerate(domains):
        suffix = f"{slug}-{i}"
        port = target_port or container_port
        service = f"traefik.http.services.{suffix}.loadbalancer.server.port"
        labels[service] = str(port)

        if ssl_enabled:
            # HTTP entrypoint redirects to HTTPS (middleware defined in Traefik static config)
            labels[f"traefik.http.routers.{suffix}-http.rule"] = f"Host(`{hostname}`)"
            labels[f"traefik.http.routers.{suffix}-http.entrypoints"] = settings.traefik_entrypoint_http
            labels[f"traefik.http.routers.{suffix}-http.middlewares"] = "redirect-to-https"
            labels[f"traefik.http.routers.{suffix}-http.service"] = suffix

            labels[f"traefik.http.routers.{suffix}.rule"] = f"Host(`{hostname}`)"
            labels[f"traefik.http.routers.{suffix}.entrypoints"] = settings.traefik_entrypoint_https
            labels[f"traefik.http.routers.{suffix}.tls"] = "true"
            labels[f"traefik.http.routers.{suffix}.tls.certresolver"] = settings.traefik_cert_resolver
            labels[f"traefik.http.routers.{suffix}.service"] = suffix
            routers += [f"{suffix}-http", suffix]
        else:
            labels[f"traefik.http.routers.{suffix}.rule"] = f"Host(`{hostname}`)"
            labels[f"traefik.http.routers.{suffix}.entrypoints"] = settings.traefik_entrypoint_http
            labels[f"traefik.http.routers.{suffix}.service"] = suffix
            routers.append(suffix)

    if routers:
        labels["traefik.http.routers." + slug + ".rule"] = f"Host(`{domains[0][0]}`)"
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
