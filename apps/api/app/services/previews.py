"""Preview deployments: one environment per pull request.

A preview is a real Application row (is_preview=True) so it reuses the whole
platform — deployer, logs, terminal, domains, env injection. Previews are
created from Git provider PR/MR webhooks and cleaned up on close/merge or
after `preview_retention_days`.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import utcnow
from ..core.security import decrypt_secret, encrypt_secret
from ..models.application import Application, ApplicationDomain, EnvironmentVariable, WebhookIntegration
from ..models.infrastructure import ApplicationDatabaseLink
from ..models.user import User
from .log_hub import log_hub
from .worker import create_deployment


def ensure_preview(session: Session, parent: Application, pr_number: int,
                   branch: str, commit_sha: str | None = None) -> tuple[Application, bool]:
    """Find or create the preview application for a PR. Returns (app, created)."""
    slug = f"{parent.slug}-pr{pr_number}"
    existing = session.query(Application).filter_by(slug=slug, deleted_at=None).first()
    if existing:
        existing.git_branch = branch
        if commit_sha:
            existing.git_commit_sha = commit_sha
        session.commit()
        return existing, False

    preview = Application(
        name=f"{parent.name} · PR#{pr_number}",
        slug=slug,
        description=f"Preview deployment for PR #{pr_number} ({branch}) of {parent.name}",
        project_id=parent.project_id,
        source_type=parent.source_type,
        git_url=parent.git_url,
        git_branch=branch,
        git_username=parent.git_username,
        git_password_encrypted=parent.git_password_encrypted,
        dockerfile_path=parent.dockerfile_path,
        docker_compose_path=parent.docker_compose_path,
        container_port=parent.container_port,
        health_check_path=parent.health_check_path,
        cpu_limit=parent.cpu_limit,
        memory_limit_mb=parent.memory_limit_mb,
        is_preview=True,
        preview_of=parent.id,
        pr_number=pr_number,
        server_id=parent.server_id,
        status="idle",
    )
    session.add(preview)
    session.flush()

    # copy environment variables (encrypted values are reusable — same key)
    for var in session.query(EnvironmentVariable).filter_by(application_id=parent.id).all():
        session.add(EnvironmentVariable(
            application_id=preview.id, key=var.key,
            value_encrypted=var.value_encrypted, is_secret=var.is_secret,
        ))
    # copy database links so DATABASE_URL etc. are injected in previews too
    for link in session.query(ApplicationDatabaseLink).filter_by(application_id=parent.id).all():
        session.add(ApplicationDatabaseLink(
            application_id=preview.id, connection_id=link.connection_id,
            env_mapping=link.env_mapping,
        ))
    # webhook integration for the preview itself
    session.add(WebhookIntegration(
        application_id=preview.id, provider="generic",
        secret_encrypted=encrypt_secret(uuid.uuid4().hex),
        secret_token=uuid.uuid4().hex,
    ))
    session.commit()
    session.refresh(preview)
    return preview, True


def ensure_preview_domain(session: Session, parent: Application, preview: Application) -> str | None:
    """Attach pr<N>.<base-domain> to the preview and provision via Cloudflare when possible."""
    if not parent.enable_previews or not parent.preview_base_domain:
        return None
    hostname = f"pr{preview.pr_number}.{parent.preview_base_domain}"
    domain = session.query(ApplicationDomain).filter_by(
        application_id=preview.id, hostname=hostname).first()
    if domain is None:
        domain = ApplicationDomain(
            application_id=preview.id, hostname=hostname,
            ssl_enabled=True, ssl_status="pending",
        )
        session.add(domain)
        session.commit()
        session.refresh(domain)

    # best-effort one-click provisioning via Cloudflare (tunnel ingress + CNAME)
    try:
        from . import cloudflare
        from ..models.infrastructure import TunnelConnection

        if cloudflare.get_token(session):
            tunnel_id = None
            running = (session.query(TunnelConnection)
                       .filter_by(status="running").first())
            if running:
                tunnel_id = running.container_id  # not used; cf side needs the CF tunnel id
            tunnels = []
            try:
                account_id = cloudflare.get_account_id(session)
                token = cloudflare.get_token(session)
                tunnels = cloudflare.list_account_tunnels(token, account_id)
            except Exception:
                tunnels = []
            cf_tunnel = next((t for t in tunnels if t.get("status") in ("healthy", "active")), None) \
                or (tunnels[0] if tunnels else None)
            if cf_tunnel:
                report = cloudflare.provision_domain(
                    session, domain, preview.slug, preview.container_port, cf_tunnel["id"])
                session.commit()
                return report.get("message")
        _ = tunnel_id
    except Exception as exc:
        _ = exc  # provisioning is best-effort; Traefik wildcard routing still applies
    return hostname


def start_preview_deploy(session: Session, parent: Application, pr_number: int,
                         branch: str, commit_sha: str | None = None) -> dict:
    """Create/refresh the preview app and queue a deployment for it."""
    preview, created = ensure_preview(session, parent, pr_number, branch, commit_sha)
    if preview.deleted_at is not None:
        preview.deleted_at = None  # reopened
    deployment = create_deployment(session, preview, trigger="preview",
                                   commit_sha=commit_sha, created_by_name="preview-bot")
    message = ensure_preview_domain(session, parent, preview)
    log_hub.publish_sync("system", {
        "type": "preview", "level": "info",
        "message": (f"Preview for {parent.name} PR#{pr_number} "
                    f"{'created' if created else 'updated'} — deploying {branch}"),
        "application_id": str(preview.id),
    })
    return {"preview": preview, "deployment": deployment, "created": created, "domain_message": message}


def cleanup_preview(session: Session, preview: Application) -> None:
    """Stop and remove a preview's containers, then soft-delete the app."""
    from .docker_client import docker_service

    for index in range(1, 11):
        name = f"ld-{preview.slug}" if index == 1 else f"ld-{preview.slug}-r{index}"
        container = docker_service.get_container(name) if docker_service.available else None
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass
    preview.deleted_at = utcnow()
    preview.status = "deleted"
    session.commit()
    log_hub.publish_sync("system", {
        "type": "preview", "level": "info",
        "message": f"Preview '{preview.name}' cleaned up (PR closed or expired)",
        "application_id": str(preview.id),
    })


def cleanup_expired_previews(session: Session) -> int:
    """Remove previews whose last deploy is older than the parent's retention window."""
    from datetime import timedelta

    expired = 0
    previews = session.query(Application).filter_by(is_preview=True, deleted_at=None).all()
    for preview in previews:
        parent = session.query(Application).get(preview.preview_of) if preview.preview_of else None
        retention = (parent.preview_retention_days if parent else 7) or 7
        last = preview.last_deployed_at or preview.created_at
        if last and last < utcnow() - timedelta(days=retention):
            cleanup_preview(session, preview)
            expired += 1
    return expired


def handle_pull_request(session: Session, parent: Application, provider: str, event: dict) -> dict:
    """Process a PR/MR webhook event. Returns an action summary."""
    if provider == "github":
        action = event.get("action", "")
        pr = event.get("pull_request") or {}
        pr_number = pr.get("number")
        branch = ((pr.get("head") or {}).get("ref")) or ""
        commit = ((pr.get("head") or {}).get("sha"))
        closed_merged = action == "closed"
    elif provider == "gitlab":
        attrs = event.get("object_attributes") or {}
        action = {None: "", "update": "synchronize"}.get(attrs.get("action"), attrs.get("action") or "")
        pr_number = attrs.get("iid")
        branch = attrs.get("source_branch") or ""
        commit = (event.get("object_attributes", {}).get("last_commit") or {}).get("id")
        closed_merged = attrs.get("action") in ("close", "merge")
    else:
        return {"handled": False, "reason": f"provider {provider} has no PR support"}

    if not pr_number or not branch:
        return {"handled": False, "reason": "missing PR number/branch"}

    if closed_merged:
        slug = f"{parent.slug}-pr{pr_number}"
        preview = session.query(Application).filter_by(slug=slug, deleted_at=None).first()
        if preview:
            cleanup_preview(session, preview)
            return {"handled": True, "action": "cleaned", "preview": slug}
        return {"handled": True, "action": "nothing-to-clean"}

    if action in ("opened", "synchronize", "reopened", "update", ""):
        result = start_preview_deploy(session, parent, pr_number, branch, commit)
        return {"handled": True, "action": "deployed",
                "preview": result["preview"].slug,
                "deployment_id": str(result["deployment"].id)}
    return {"handled": False, "reason": f"action '{action}' ignored"}
