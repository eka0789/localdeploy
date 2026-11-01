"""Public Git webhook receiver with signature verification."""
from __future__ import annotations

import hmac
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...core.security import decrypt_secret, verify_hmac_signature
from ...models.application import Application, WebhookIntegration
from ...models.deployment import Deployment
from ...services.worker import create_deployment, enqueue_deployment
from ..deps import get_client_ip, login_limiter, record_audit

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

QUEUE_LIMIT_PER_WINDOW = 20


@router.post("/{token}")
async def receive_webhook(token: str, request: Request, db: Session = Depends(get_db)):
    if not login_limiter.check(f"webhook:{token}:{get_client_ip(request)}", 30, 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Webhook rate limit exceeded")

    hook = db.query(WebhookIntegration).filter_by(secret_token=token).first()
    if hook is None or not hook.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown webhook token")

    app = db.query(Application).filter(Application.id == hook.application_id,
                                       Application.deleted_at.is_(None)).first()
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")

    payload = await request.body()
    secret = decrypt_secret(hook.secret_encrypted) if hook.secret_encrypted else ""

    if hook.provider in ("github", "gitea"):
        header = "x-hub-signature-256" if hook.provider == "github" else "x-gitea-signature"
        signature = request.headers.get(header, "")
        if secret and not verify_hmac_signature(payload, signature, secret):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature")
    elif hook.provider == "gitlab":
        gitlab_token = request.headers.get("x-gitlab-token", "")
        if secret and not hmac.compare_digest(gitlab_token, secret):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook token")
    elif hook.provider == "generic":
        signature = request.headers.get("x-localdeploy-signature", "")
        if secret and not verify_hmac_signature(payload, signature, secret):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature")

    try:
        event = json.loads(payload or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON payload")

    # ---- preview deployments per pull request / merge request ----
    gh_event = request.headers.get("x-github-event", "")
    gl_event = request.headers.get("x-gitlab-event", "")
    if gh_event == "pull_request" or gl_event == "Merge Request Hook":
        from ...services import previews

        provider = "github" if gh_event else "gitlab"
        if app.enable_previews:
            outcome = previews.handle_pull_request(db, app, provider, event)
            if outcome.get("handled"):
                if outcome.get("action") == "deployed" and outcome.get("deployment_id"):
                    deployment = db.query(Deployment).get(uuid.UUID(outcome["deployment_id"]))
                    if deployment:
                        await enqueue_deployment(deployment)
                record_audit(db, None, "webhooks.preview", "application", str(app.id),
                             {"outcome": outcome.get("action")}, request)
                return {"ok": True, "preview": outcome}
        return {"ok": True, "message": "Preview deployments disabled for this app"}

    # --- extract push info across providers --------------------------------
    ref = event.get("ref") or ""
    branch = ref.rsplit("/", 1)[-1] if ref else None
    commit_sha = None
    commit_message = None
    if hook.provider == "github":
        if request.headers.get("x-github-event") == "ping":
            return {"ok": True, "message": "Webhook ping received"}
        head = (event.get("head_commit") or {})
        commit_sha = head.get("id")
        commit_message = head.get("message")
    elif hook.provider == "gitlab":
        commit_sha = event.get("after")
        commit_message = (event.get("commits") or [{}])[-1].get("message") if event.get("commits") else None
    elif hook.provider == "gitea":
        commit_sha = event.get("after")
        commit_message = (event.get("commits") or [{}])[-1].get("message") if event.get("commits") else None

    wanted_branch = hook.branch or app.git_branch or "main"
    if branch and branch != wanted_branch:
        return {"ok": True, "message": f"Ignoring push to branch '{branch}' (watches '{wanted_branch}')"}

    if not app.auto_deploy:
        return {"ok": True, "message": "Auto-deploy is disabled for this application"}

    deployment = create_deployment(db, app, trigger="webhook", commit_sha=commit_sha)
    hook.last_triggered_at = utcnow()
    db.commit()
    await enqueue_deployment(deployment)
    record_audit(db, None, "webhooks.trigger", "application", str(app.id),
                 {"branch": branch, "commit": (commit_sha or "")[:8]}, request)
    return {"ok": True, "deployment_id": str(deployment.id), "status": deployment.status}
