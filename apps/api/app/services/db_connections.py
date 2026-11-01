"""External managed-database connections (Supabase, Neon, Turso, Atlas, …).

Provides:
- provider presets that drive the UI forms and default env-var mapping
- real connection testing (SELECT 1 / PING / pipeline) — never simulated
- env resolution used by the deployment engine at deploy time
"""
from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass, field
from typing import Any

from ..core.security import decrypt_secret


@dataclass
class ProviderPreset:
    key: str
    label: str
    engine: str  # postgresql|mysql|mongodb|redis|libsql
    url_scheme: str
    fields: list[str] = field(default_factory=list)  # extra secret fields
    default_env: dict[str, str] = field(default_factory=dict)  # env_key -> field ref
    docs: str = ""


PROVIDERS: dict[str, ProviderPreset] = {
    "supabase": ProviderPreset(
        key="supabase",
        label="Supabase",
        engine="postgresql",
        url_scheme="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres",
        fields=["anon_key", "service_role_key"],
        default_env={
            "DATABASE_URL": "url",
            "SUPABASE_ANON_KEY": "extra:anon_key",
            "SUPABASE_SERVICE_ROLE_KEY": "extra:service_role_key",
        },
        docs="Project Settings → Database → Connection string (use the pooler URL for serverless).",
    ),
    "neon": ProviderPreset(
        key="neon",
        label="Neon",
        engine="postgresql",
        url_scheme="postgresql://<user>:<password>@ep-<id>-<region>.aws.neon.tech/neondb?sslmode=require",
        fields=[],
        default_env={"DATABASE_URL": "url"},
        docs="Neon dashboard → Connection Details → copy the pooled or direct connection string.",
    ),
    "turso": ProviderPreset(
        key="turso",
        label="Turso (libSQL)",
        engine="libsql",
        url_scheme="libsql://<database>-<org>.turso.io",
        fields=["auth_token"],
        default_env={
            "DATABASE_URL": "url",
            "TURSO_DATABASE_URL": "url",
            "TURSO_AUTH_TOKEN": "extra:auth_token",
        },
        docs="turso db show <name> --url and --auth-token, or create a token in the dashboard.",
    ),
    "planetscale": ProviderPreset(
        key="planetscale",
        label="PlanetScale (MySQL)",
        engine="mysql",
        url_scheme="mysql://<user>:<password>@aws.connect.psdb.cloud/<dbname>?sslaccept=strict",
        fields=[],
        default_env={"DATABASE_URL": "url"},
        docs="PlanetScale → database → Connect → 'Prisma' or general connection string.",
    ),
    "upstash": ProviderPreset(
        key="upstash",
        label="Upstash (Redis)",
        engine="redis",
        url_scheme="rediss://default:<password>@<name>.upstash.io:6379",
        fields=["rest_url", "rest_token"],
        default_env={
            "REDIS_URL": "url",
            "UPSTASH_REDIS_REST_URL": "extra:rest_url",
            "UPSTASH_REDIS_REST_TOKEN": "extra:rest_token",
        },
        docs="Upstash console → database → REST API section and/or the rediss:// endpoint.",
    ),
    "mongodb_atlas": ProviderPreset(
        key="mongodb_atlas",
        label="MongoDB Atlas",
        engine="mongodb",
        url_scheme="mongodb+srv://<user>:<password>@cluster0.xxxxx.mongodb.net/<dbname>",
        fields=[],
        default_env={"MONGODB_URI": "url", "DATABASE_URL": "url"},
        docs="Atlas → Connect → Drivers → connection string (allow your IP or 0.0.0.0/0).",
    ),
    "xata": ProviderPreset(
        key="xata",
        label="Xata (Postgres)",
        engine="postgresql",
        url_scheme="postgresql://<workspace>:<password>@<region>.sql.xata.sh/<db>?sslmode=require",
        fields=[],
        default_env={"DATABASE_URL": "url", "XATA_DATABASE_URL": "url"},
        docs="Xata → database → Settings → Postgres connection string.",
    ),
    "generic": ProviderPreset(
        key="generic",
        label="Generic connection string",
        engine="postgresql",
        url_scheme="postgresql://user:pass@host:5432/db",
        fields=[],
        default_env={"DATABASE_URL": "url"},
        docs="Any provider — pick the underlying engine so health checks know what to test.",
    ),
}


def get_preset(provider: str) -> ProviderPreset:
    return PROVIDERS.get(provider) or PROVIDERS["generic"]


# ---------------------------------------------------------------------------
# env resolution (deploy-time injection)
# ---------------------------------------------------------------------------

def resolve_field(connection, field_ref: str) -> str | None:
    """Resolve 'url' | 'username' | 'password' | 'database' | 'host' | 'port' | 'extra:<key>'."""
    if field_ref == "url":
        return decrypt_secret(connection.url_encrypted) if connection.url_encrypted else None
    if field_ref == "password":
        return decrypt_secret(connection.password_encrypted) if connection.password_encrypted else None
    if field_ref == "username":
        return connection.username
    if field_ref == "database":
        return connection.database_name
    if field_ref == "host":
        return connection.host
    if field_ref == "port":
        return str(connection.port) if connection.port else None
    if field_ref.startswith("extra:"):
        key = field_ref.split(":", 1)[1]
        stored = (connection.extra_secrets or {}).get(key)
        return decrypt_secret(stored) if stored else None
    return None


def build_env_for_app(session, application_id) -> dict[str, str]:
    """All env vars injected from database links for an application (decrypted)."""
    from ..models.infrastructure import ApplicationDatabaseLink, DatabaseConnection

    links = session.query(ApplicationDatabaseLink).filter_by(application_id=application_id).all()
    env: dict[str, str] = {}
    for link in links:
        connection = session.get(DatabaseConnection, link.connection_id)
        if connection is None:
            continue
        for env_key, field_ref in (link.env_mapping or {}).items():
            value = resolve_field(connection, field_ref)
            if value:
                env[env_key] = value
    return env


# ---------------------------------------------------------------------------
# real connection testing
# ---------------------------------------------------------------------------

def test_connection(connection) -> tuple[str, str | None]:
    """Returns (status, error). status: connected | reachable | failed."""
    url = None
    try:
        url = resolve_field(connection, "url")
        engine = connection.engine

        if engine == "postgresql" and url:
            import psycopg

            with psycopg.connect(url, connect_timeout=8) as conn:  # noqa: SIM117
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return "connected", None

        if engine == "mysql" and url:
            import pymysql

            parsed = _parse_url(url)
            conn = pymysql.connect(
                host=parsed["host"], port=parsed["port"], user=parsed["username"] or "",
                password=parsed["password"] or "", database=parsed["database"] or "",
                connect_timeout=8, ssl={"ssl": True},
            )
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            conn.close()
            return "connected", None

        if engine == "redis" and url:
            reply = _redis_ping(url)
            if reply:
                return "connected", None
            return "reachable", "TCP/TLS reachable but no PONG (check auth/password)"

        if engine == "libsql" and url:
            return _libsql_ping(connection, url)

        if engine == "mongodb" and url:
            ok, err = _tcp_tls_check(connection)
            return ("reachable", err) if ok else ("failed", err)

        # no URL — fall back to raw TCP check
        ok, err = _tcp_tls_check(connection)
        return ("reachable", err) if ok else ("failed", err)
    except Exception as exc:
        return "failed", f"{type(exc).__name__}: {exc}"[:300]


def _parse_url(url: str) -> dict[str, Any]:
    from urllib.parse import urlparse, unquote

    parsed = urlparse(url)
    default_port = 6379 if url.startswith("redis") else 443 if url.startswith("libsql") else 5432
    return {
        "host": parsed.hostname,
        "port": parsed.port or default_port,
        "username": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "database": (parsed.path or "").lstrip("/") or None,
    }


def _tcp_tls_check(connection, timeout: float = 6.0) -> tuple[bool, str | None]:
    """Best-effort reachability check for engines without a client library."""
    if not connection.host:
        return False, "no host configured"
    try:
        raw = socket.create_connection((connection.host, connection.port or 443), timeout=timeout)
        try:
            if connection.port == 443 or connection.engine in ("libsql",):
                ctx = ssl.create_default_context()
                with ctx.wrap_socket(raw, server_hostname=connection.host):
                    pass
        finally:
            raw.close()
        return True, None
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"[:200]


def _redis_ping(url: str) -> bool:
    """Minimal RESP PING over TCP/TLS — no client library needed."""
    parsed = _parse_url(url)
    target_host = parsed["host"]
    target_port = parsed["port"]
    use_tls = url.startswith("rediss://")
    raw = socket.create_connection((target_host, target_port), timeout=6)
    try:
        if use_tls:
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=target_host)
        password = parsed.get("password")
        payload = b""
        if password:
            payload += b"*2\r\n$4\r\nAUTH\r\n$" + str(len(password)).encode() + b"\r\n" + password.encode() + b"\r\n"
        payload += b"*1\r\n$4\r\nPING\r\n"
        raw.sendall(payload)
        raw.settimeout(6)
        data = raw.recv(128)
        return b"+PONG" in data or b"+NOAUTH" not in data and b"ERR" not in data and b"PONG" in data.upper()
    finally:
        raw.close()


def _libsql_ping(connection, url: str) -> tuple[str, str | None]:
    """Turso/libSQL: hit the HTTP pipeline API with SELECT 1."""
    import httpx

    host = connection.host or url.replace("libsql://", "").split("/")[0]
    token = resolve_field(connection, "extra:auth_token")
    api_url = f"https://{host}/v2/pipeline"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    body = {"requests": [{"type": "execute", "stmt": {"sql": "SELECT 1"}}]}
    resp = httpx.post(api_url, json=body, headers=headers, timeout=10)
    if resp.status_code == 200 and '"result"' in resp.text:
        return "connected", None
    if resp.status_code in (401, 403):
        return "failed", f"Auth failed ({resp.status_code}) — check the auth token"
    return "failed", f"HTTP {resp.status_code}: {resp.text[:150]}"


def redacted_view(connection) -> dict:
    """Safe representation for API responses (no secrets)."""
    extras = {key: bool(value) for key, value in (connection.extra_secrets or {}).items()}
    return {
        "id": str(connection.id),
        "name": connection.name,
        "provider": connection.provider,
        "engine": connection.engine,
        "host": connection.host,
        "port": connection.port,
        "database_name": connection.database_name,
        "username": connection.username,
        "has_url": bool(connection.url_encrypted),
        "has_password": bool(connection.password_encrypted),
        "extra_fields": extras,
        "notes": connection.notes,
        "last_tested_at": connection.last_tested_at.isoformat() if connection.last_tested_at else None,
        "last_test_status": connection.last_test_status,
        "last_error": connection.last_error,
        "created_at": connection.created_at.isoformat(),
    }


def parse_connection_url(url: str) -> dict:
    """Extract host/port/database from a connection URL (for the UI + tests)."""
    try:
        return _parse_url(url)
    except Exception:
        return {}
