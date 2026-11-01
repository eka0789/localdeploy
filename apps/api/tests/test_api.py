"""API integration tests: auth flow, CSRF, applications CRUD, deployments lifecycle."""
from app.core.security import decrypt_secret
from app.models.application import Application, EnvironmentVariable, WebhookIntegration


# ----------------------------------------------------------------- auth

def test_health_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_login_rejects_bad_credentials(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_me_requires_session(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_with_session(client, auth):
    # the `auth` fixture logged in on this client; session cookie is present
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["role_name"] == "admin"


def test_csrf_required_for_mutations(client, auth):
    # missing CSRF header on a mutating request -> 403
    resp = client.post("/api/projects", json={"name": "No CSRF"})
    assert resp.status_code == 403
    resp = client.post("/api/projects", json={"name": "With CSRF"}, headers=auth())
    assert resp.status_code == 201


# ----------------------------------------------------------------- projects & applications

def test_project_crud(client, auth):
    created = client.post("/api/projects", json={"name": "Crud Project"}, headers=auth()).json()
    assert created["name"] == "Crud Project"

    listed = client.get("/api/projects").json()
    assert any(p["id"] == created["id"] for p in listed)

    updated = client.put(f"/api/projects/{created['id']}",
                         json={"description": "updated"}, headers=auth()).json()
    assert updated["description"] == "updated"

    deleted = client.delete(f"/api/projects/{created['id']}", headers=auth())
    assert deleted.status_code == 200


def test_application_slug_uniqueness(client, auth, db):
    body = {"name": "Unique App One", "source_type": "git",
            "git_url": "https://github.com/x/y", "container_port": 3000}
    first = client.post("/api/applications", json=body, headers=auth())
    assert first.status_code == 201
    conflict = client.post("/api/applications", json=body, headers=auth())
    assert conflict.status_code == 409
    assert "slug" in conflict.json()["detail"]


def test_application_validation_rejects_bad_input(client, auth):
    resp = client.post("/api/applications",
                       json={"name": "x", "source_type": "git"}, headers=auth())
    assert resp.status_code == 422  # name too short -> slug validation


def test_application_env_var_encrypted_at_rest(client, auth, sample_app, db):
    resp = client.post(f"/api/applications/{sample_app.id}/env-vars",
                       json={"key": "API_KEY", "value": "plain-secret-value"}, headers=auth())
    assert resp.status_code == 201

    row = db.query(EnvironmentVariable).filter_by(key="API_KEY").first()
    assert row is not None
    assert "plain-secret-value" not in row.value_encrypted  # encrypted at rest
    assert decrypt_secret(row.value_encrypted) == "plain-secret-value"

    # duplicate key rejected
    dup = client.post(f"/api/applications/{sample_app.id}/env-vars",
                      json={"key": "API_KEY", "value": "x"}, headers=auth())
    assert dup.status_code == 409


def test_application_detail_masks_git_password(client, auth, db):
    resp = client.post("/api/applications", headers=auth(), json={
        "name": "Secret App", "source_type": "git",
        "git_url": "https://github.com/x/y", "git_password": "ghp_secrettoken",
    })
    body = resp.json()
    detail = client.get(f"/api/applications/{body['id']}").json()
    assert "ghp_secrettoken" not in str(detail)
    assert detail["has_git_password"] is True


# ----------------------------------------------------------------- webhooks

def test_webhook_unknown_token_404(client):
    resp = client.post("/api/webhooks/does-not-exist", json={})
    assert resp.status_code == 404


def test_webhook_created_automatically(client, auth, sample_app):
    hook = client.get(f"/api/applications/{sample_app.id}/webhook").json()
    assert hook["url"].endswith(hook["url"].split("/")[-1])
    assert hook["is_active"] is True


# ----------------------------------------------------------------- domains

def test_domain_create_and_conflict(client, auth, sample_app):
    resp = client.post("/api/domains", headers=auth(), json={
        "application_id": str(sample_app.id), "hostname": "test.example.com",
    })
    assert resp.status_code == 201
    domain = resp.json()
    assert domain["ssl_status"] == "pending"

    conflict = client.post("/api/domains", headers=auth(), json={
        "application_id": str(sample_app.id), "hostname": "test.example.com",
    })
    assert conflict.status_code == 409

    instructions = client.get(f"/api/domains/{domain['id']}/dns-instructions").json()
    assert any(r["type"] == "A" for r in instructions["records"])


def test_domain_invalid_hostname_rejected(client, auth, sample_app):
    resp = client.post("/api/domains", headers=auth(), json={
        "application_id": str(sample_app.id), "hostname": "not valid!!",
    })
    assert resp.status_code == 422


# ----------------------------------------------------------------- deployments

def test_deploy_flow_records_failure_without_docker(client, auth, sample_app):
    """Docker is disabled in tests: deployment must fail gracefully, never hang."""
    resp = client.post(f"/api/applications/{sample_app.id}/deploy", headers=auth())
    assert resp.status_code == 202
    deployment_id = resp.json()["deployment_id"]

    import time

    status = None
    for _ in range(50):
        body = client.get(f"/api/deployments/{deployment_id}").json()
        status = body["status"]
        if status in ("failed", "success", "cancelled"):
            break
        time.sleep(0.2)
    assert status == "failed"
    assert body["error_message"]  # recorded failure reason


def test_deployment_cancel_after_finish_conflicts(client, auth, sample_app):
    import time

    resp = client.post(f"/api/applications/{sample_app.id}/deploy", headers=auth())
    deployment_id = resp.json()["deployment_id"]
    for _ in range(50):
        body = client.get(f"/api/deployments/{deployment_id}").json()
        if body["status"] in ("failed", "success"):
            break
        time.sleep(0.2)
    cancel = client.post(f"/api/deployments/{deployment_id}/cancel", headers=auth())
    assert cancel.status_code == 409


# ----------------------------------------------------------------- monitoring & settings

def test_monitoring_server_snapshot(client, auth):
    body = client.get("/api/monitoring/server").json()
    assert 0 <= body["cpu_percent"] <= 100
    assert body["memory_total_mb"] > 0
    assert "docker" in body


def test_overview_aggregates(client, auth):
    body = client.get("/api/overview").json()
    assert "applications" in body
    assert "recent_deployments" in body
    assert "server" in body


def test_settings_roundtrip(client, auth):
    resp = client.put("/api/settings", headers=auth(), json={
        "settings": [{"key": "test.setting", "value": {"enabled": True}}],
    })
    assert resp.status_code == 200
    body = client.get("/api/settings").json()
    assert body["settings"]["test.setting"]["value"] == {"enabled": True}


def test_audit_log_records_actions(client, auth):
    logs = client.get("/api/audit-logs?limit=5").json()
    assert logs["total"] >= 1
    actions = [entry["action"] for entry in logs["logs"]]
    assert any(a.startswith("applications.") or a.startswith("projects.") for a in actions)


def test_prometheus_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "localdeploy_server_cpu_percent" in resp.text


def test_viewer_role_cannot_write(client, db):
    """RBAC: viewer role is read-only. Runs in an isolated cookie jar so the
    shared admin session is not clobbered for subsequent tests."""
    import http.cookiejar

    from app.models.user import Role, User

    from app.core.security import hash_password

    viewer_role = db.query(Role).filter_by(name="viewer").first()
    user = User(username="viewer1", email="viewer1@test.local",
                password_hash=hash_password("password123"), role_id=viewer_role.id)
    db.add(user)
    db.commit()

    saved_jar = client.cookies.jar
    client.cookies = http.cookiejar.CookieJar()
    try:
        login = client.post("/api/auth/login", json={"username": "viewer1", "password": "password123"})
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        resp = client.post("/api/projects", json={"name": "Forbidden"},
                           headers={"X-CSRF-Token": csrf})
        assert resp.status_code == 403

        # read is allowed
        assert client.get("/api/projects").status_code == 200
    finally:
        client.cookies = saved_jar
