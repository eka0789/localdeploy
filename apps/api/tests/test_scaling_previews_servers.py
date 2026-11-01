"""Tests for replicas, preview deployments and multi-server dispatch."""
import time
import uuid

from app.models.application import WebhookIntegration
from app.models.infrastructure import ServerCommand
from app.services.deployer import run_deployment
from app.services.previews import ensure_preview
from app.services.worker import create_deployment


# ----------------------------------------------------------------- servers

def test_server_lifecycle_and_agent_flow(client, auth, db):
    created = client.post("/api/servers", headers=auth(), json={"name": "vps-hetzner"})
    assert created.status_code == 201
    body = created.json()
    token = body["token"]
    assert token.startswith("lds_")

    bare = client.post("/api/agent/hello",
                       headers={"Authorization": f"Bearer {token}"},
                       json={"agent_version": "1.0.0", "cpu_percent": 12.5,
                             "memory_used_mb": 900, "memory_total_mb": 4000,
                             "container_count": 5, "running_count": 3})
    assert bare.status_code == 200
    assert bare.json()["commands"] == []

    listed = client.get("/api/servers").json()
    server = next(s for s in listed if s["name"] == "vps-hetzner")
    assert server["status"] == "online"
    assert server["container_count"] == 5

    # bad token rejected
    bad = client.post("/api/agent/hello", headers={"Authorization": "Bearer lds_nope"}, json={})
    assert bad.status_code == 401

    client.delete(f"/api/servers/{server['id']}", headers=auth())


def test_remote_deploy_dispatch(client, auth, db, sample_app):
    server = client.post("/api/servers", headers=auth(), json={"name": "remote-1"}).json()
    try:
        sample_app.server_id = uuid.UUID(server["id"])
        db.commit()

        deploy = client.post(f"/api/applications/{sample_app.id}/deploy", headers=auth())
        assert deploy.status_code == 202
        deployment_id = uuid.UUID(deploy.json()["deployment_id"])

        # the local engine must NOT run it — a command is queued instead
        command = None
        for _ in range(50):
            db.expire_all()
            command = db.query(ServerCommand).filter_by(deployment_id=deployment_id).first()
            if command is not None:
                break
            time.sleep(0.2)
        assert command is not None
        assert command.command_type == "deploy"
        assert command.payload["slug"] == sample_app.slug
        assert "git_url" in command.payload and "env" in command.payload

        # agent streams logs back
        logs = client.post("/api/agent/logs",
                           headers={"Authorization": f"Bearer {server['token']}"},
                           json={"deployment_id": str(deployment_id),
                                 "lines": [{"message": "→ Building", "stream": "stdout"}]})
        assert logs.status_code == 200

        # agent reports result
        result = client.post("/api/agent/result",
                             headers={"Authorization": f"Bearer {server['token']}"},
                             json={"command_id": str(command.id), "ok": True,
                                   "result": {"image_tag": "localdeploy/x:1", "container_id": "abc",
                                              "container_name": f"ld-{sample_app.slug}"}})
        assert result.status_code == 200

        detail = client.get(f"/api/deployments/{deployment_id}").json()
        assert detail["status"] == "success"
        assert detail["image_tag"] == "localdeploy/x:1"

        db.expire_all()
        stored = db.query(ServerCommand).get(command.id)
        assert stored.status == "done"
    finally:
        client.delete(f"/api/servers/{server['id']}", headers=auth())


# ----------------------------------------------------------------- previews

def test_preview_ensure_and_webhook(client, auth, db, sample_app):
    sample_app.enable_previews = True
    sample_app.preview_base_domain = "preview.example.com"
    db.commit()

    # ensure_preview creates a real app with copied env + links
    preview, created = ensure_preview(db, sample_app, pr_number=7, branch="feature/x")
    assert created is True
    assert preview.slug == f"{sample_app.slug}-pr7"
    assert preview.is_preview is True
    assert preview.preview_of == sample_app.id

    # second call reuses the same app
    preview2, created2 = ensure_preview(db, sample_app, pr_number=7, branch="feature/x")
    assert created2 is False and preview2.id == preview.id

    # GitHub PR webhook → preview deployment queued
    event = {"action": "opened", "pull_request": {
        "number": 9, "state": "open",
        "head": {"ref": "feature/y", "sha": "abc1234"},
    }}
    hook = (db.query(WebhookIntegration)
            .filter_by(application_id=sample_app.id).first())
    if hook is None:
        from app.core.security import encrypt_secret

        hook = WebhookIntegration(application_id=sample_app.id, provider="generic",
                                  secret_encrypted=encrypt_secret(""),  # no verification in test
                                  secret_token="testhooktoken123")
        db.add(hook)
        db.commit()

    push = client.post(f"/api/webhooks/{hook.secret_token}", json=event,
                       headers={"X-GitHub-Event": "pull_request"})
    assert push.status_code == 200
    body = push.json()
    assert body["preview"]["handled"] is True
    assert body["preview"]["preview"].endswith("-pr9")

    # PR closed → cleanup
    event_closed = {"action": "closed", "pull_request": {"number": 9, "head": {"ref": "feature/y"}}}
    closed = client.post(f"/api/webhooks/{hook.secret_token}", json=event_closed,
                         headers={"X-GitHub-Event": "pull_request"})
    assert closed.status_code == 200
    assert closed.json()["preview"]["action"] == "cleaned"


def test_preview_deployment_recorded(client, auth, db, sample_app):
    """A preview deploy goes through the normal worker (fails w/o docker, recorded)."""
    preview, _ = ensure_preview(db, sample_app, pr_number=3, branch="feat")
    deployment = create_deployment(db, preview, trigger="preview", created_by_name="preview-bot")
    run_deployment(deployment.id)  # sync worker execution
    body = client.get(f"/api/deployments/{deployment.id}").json()
    assert body["status"] == "failed"  # docker disabled in tests — graceful, recorded
    assert body["error_message"]
