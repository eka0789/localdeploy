"""Tests for notifications, API tokens (CI/CD) and backup schedules."""
from app.core.security import hash_token
from app.models.infrastructure import BackupSchedule, NotificationChannel
from app.models.user import ApiToken
from app.services.notify import _render_message


# ----------------------------------------------------------------- notifications

def test_notification_channel_crud(client, auth, db):
    created = client.post("/api/notifications", headers=auth(), json={
        "name": "Ops Discord", "type": "discord",
        "url": "https://discord.com/api/webhooks/123/abc",
    })
    assert created.status_code == 201
    body = created.json()
    assert body["has_url"] is True
    assert "abc" not in str(body)  # never leak secrets

    listed = client.get("/api/notifications").json()
    assert any(c["name"] == "Ops Discord" for c in listed)

    # webhook type requires url
    missing = client.post("/api/notifications", headers=auth(), json={
        "name": "Broken", "type": "discord",
    })
    assert missing.status_code == 400

    # telegram requires token + chat
    tg = client.post("/api/notifications", headers=auth(), json={
        "name": "Tg", "type": "telegram",
    })
    assert tg.status_code == 400

    deleted = client.delete(f"/api/notifications/{body['id']}", headers=auth())
    assert deleted.status_code == 200


def test_render_message_contains_context():
    message = _render_message("deployment.failed", {
        "application_name": "shop", "status": "failed",
        "error": "build failed", "commit": "abc12345",
    })
    assert "shop" in message and "failed" in message and "abc12345" in message


# ----------------------------------------------------------------- API tokens

def test_api_token_enables_bearer_auth(client, auth, db, sample_app):
    created = client.post("/api/auth/tokens", headers=auth(), json={"name": "GitHub Actions"})
    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("ldt_")
    # stored hashed — plaintext never persisted
    rows = db.query(ApiToken).all()
    assert all(token != r.token_hash for r in rows)

    # bearer auth works without the session cookie: run cookie-free, restore after
    import http.cookiejar

    saved_jar = client.cookies.jar
    client.cookies = http.cookiejar.CookieJar()
    try:
        bare = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert bare.status_code == 200
        assert bare.json()["username"] == "admin"

        # garbage token rejected
        bad = client.get("/api/auth/me", headers={"Authorization": "Bearer ldt_wrong"})
        assert bad.status_code == 401

        # token can trigger a deploy (CI/CD flow)
        deploy = client.post(f"/api/applications/{sample_app.id}/deploy",
                             headers={"Authorization": f"Bearer {token}"})
        assert deploy.status_code == 202

        # revoke (session cookie restored) -> token dies
        token_id = created.json()["id"]
        client.cookies = saved_jar
        revoked = client.delete(f"/api/auth/tokens/{token_id}", headers=auth())
        assert revoked.status_code == 200
        client.cookies = http.cookiejar.CookieJar()
        dead = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert dead.status_code == 401
    finally:
        client.cookies = saved_jar


# ----------------------------------------------------------------- schedules

def test_backup_schedule_crud(client, auth, db):
    from app.models.infrastructure import DatabaseInstance

    instance = DatabaseInstance(
        name="sched-db", engine="postgresql", image="postgres:16-alpine", version="16-alpine",
        username="u", password_encrypted="x", port=5432,
        container_name="ld-db-sched-db", volume_name="ld-db-sched-db-data",
    )
    db.add(instance)
    db.commit()

    created = client.post("/api/backups/schedules", headers=auth(), json={
        "target_type": "database", "target_id": str(instance.id),
        "target_name": "sched-db", "interval_hours": 24, "keep_last": 5,
    })
    assert created.status_code == 201

    # nonexistent volume target rejected
    bad_volume = client.post("/api/backups/schedules", headers=auth(), json={
        "target_type": "volume", "target_id": "no-such-volume",
        "target_name": "no-such-volume", "interval_hours": 24, "keep_last": 5,
    })
    assert bad_volume.status_code in (404, 503)  # 404 validated, 503 when docker offline

    schedules = client.get("/api/backups/schedules/all").json()
    assert any(s["target_name"] == "sched-db" for s in schedules)

    updated = client.put(f"/api/backups/schedules/{created.json()['id']}",
                         headers=auth(), json={"enabled": False, "interval_hours": 12})
    assert updated.status_code == 200
    row = db.query(BackupSchedule).filter_by(target_name="sched-db").first()
    assert row.enabled is False and row.interval_hours == 12

    # invalid target type rejected
    invalid = client.post("/api/backups/schedules", headers=auth(), json={
        "target_type": "weird", "target_id": "x", "target_name": "x",
    })
    assert invalid.status_code == 400
