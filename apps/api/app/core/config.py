"""Application configuration loaded from environment / .env (LOCALDEPLOY_ prefix)."""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_API_DIR = Path(__file__).resolve().parent.parent.parent


def _load_or_create_secret_key(raw: str) -> str:
    """Return the configured secret key, or persist an auto-generated dev key."""
    if raw:
        return raw
    key_file = _API_DIR / "data" / ".secret_key"
    try:
        if key_file.exists():
            value = key_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        key = secrets.token_hex(32)
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(key, encoding="utf-8")
        return key
    except OSError:
        return secrets.token_hex(32)  # ephemeral fallback


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_API_DIR.parent.parent / ".env"),
        env_prefix="LOCALDEPLOY_",
        extra="ignore",
    )

    app_name: str = "LocalDeploy"
    version: str = "1.0.0"
    environment: str = "development"

    # Security
    secret_key: str = ""
    session_ttl_minutes: int = 60 * 24 * 7
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 300

    # HTTP
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]
    public_base_url: str = "http://localhost:8000"

    # Platform database (sync drivers: sqlite / postgresql+psycopg)
    database_url: str = "sqlite:///./data/localdeploy.db"

    # Docker Engine
    docker_host: str | None = None

    # Paths
    workspace_dir: Path = Path("./data/workspace")
    backups_dir: Path = Path("./data/backups")
    acme_json_path: str | None = None

    # Deployment engine
    deploy_network: str = "localdeploy-network"
    image_prefix: str = "localdeploy"
    deploy_timeout_seconds: int = 1800
    healthcheck_timeout_seconds: int = 120
    git_clone_timeout_seconds: int = 600

    # Traefik / SSL
    traefik_entrypoint_http: str = "http"
    traefik_entrypoint_https: str = "https"
    traefik_cert_resolver: str = "letsencrypt"

    # First-run bootstrap admin
    first_admin_username: str = "admin"
    first_admin_email: str = "admin@localdeploy.local"
    first_admin_password: str = "localdeploy123"

    # Metrics
    metrics_sample_seconds: int = 15
    metrics_retention_hours: int = 48

    # Redis (optional — enables Redis-backed rate limiting / pubsub when reachable)
    redis_url: str | None = None

    # Testing flags
    docker_disabled: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def ensure_dirs(self) -> None:
        for p in (self.workspace_dir, self.backups_dir):
            Path(p).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key:
        settings.secret_key = _load_or_create_secret_key("")
    return settings


settings = get_settings()
