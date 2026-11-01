"""Pytest fixtures: temp SQLite database, test client, authenticated session."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("LOCALDEPLOY_DOCKER_DISABLED", "true")
os.environ.setdefault("LOCALDEPLOY_SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ.setdefault("LOCALDEPLOY_ENVIRONMENT", "test")

_tmp = Path(tempfile.mkdtemp(prefix="localdeploy-test-"))
os.environ.setdefault("LOCALDEPLOY_WORKSPACE_DIR", str(_tmp / "workspace"))
os.environ.setdefault("LOCALDEPLOY_BACKUPS_DIR", str(_tmp / "backups"))
os.environ.setdefault("LOCALDEPLOY_DATABASE_URL", f"sqlite:///{_tmp.as_posix()}/test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal, bootstrap  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402
from app.core.security import hash_password  # noqa: E402

settings.docker_disabled = True


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def auth(client):
    """Returns headers dict with session cookie + CSRF token for an admin user."""
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "localdeploy123"})
    assert resp.status_code == 200, resp.text
    csrf = resp.json()["csrf_token"]

    def headers(**extra):
        return {"X-CSRF-Token": csrf, **extra}

    return headers


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def sample_app(db):
    import uuid as _uuid

    from app.models.application import Application

    app_row = Application(
        name=f"Test App {_uuid.uuid4().hex[:6]}", slug=f"test-app-{_uuid.uuid4().hex[:8]}",
        source_type="git",
        git_url="https://github.com/example/repo", git_branch="main",
        container_port=3000,
    )
    db.add(app_row)
    db.commit()
    db.refresh(app_row)
    return app_row


@pytest.fixture(scope="session", autouse=True)
def _bootstrap():
    session = SessionLocal()
    try:
        bootstrap(session)
    finally:
        session.close()
