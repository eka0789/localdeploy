"""External database connections + Cloudflare provisioning tests."""
from app.core.security import encrypt_secret
from app.services.cloudflare import build_ingress, find_zone_for_hostname
from app.services.db_connections import (
    PROVIDERS,
    build_env_for_app,
    get_preset,
    resolve_field,
)


# ----------------------------------------------------------------- providers

def test_provider_presets_cover_major_providers():
    expected = {"supabase", "neon", "turso", "planetscale", "upstash", "mongodb_atlas", "generic"}
    assert expected.issubset(PROVIDERS.keys())


def test_provider_default_env_mapping_references_valid_fields():
    for provider in PROVIDERS.values():
        for env_key, field_ref in provider.default_env.items():
            assert env_key and env_key == env_key.upper()
            base = field_ref.split(":")[0]
            assert base in {"url", "username", "password", "database", "host", "port", "extra"}


def test_unknown_provider_falls_back_to_generic():
    assert get_preset("doesnotexist").key == "generic"


# ----------------------------------------------------------------- env resolution

class FakeConnection:
    def __init__(self):
        self.url_encrypted = encrypt_secret("postgresql://u:p@db.example.com:5432/appdb")
        self.password_encrypted = encrypt_secret("secret-pass")
        self.username = "appuser"
        self.database_name = "appdb"
        self.host = "db.example.com"
        self.port = 5432
        self.extra_secrets = {"auth_token": encrypt_secret("turso-token-123")}


def test_resolve_field_all_types():
    connection = FakeConnection()
    assert resolve_field(connection, "url") == "postgresql://u:p@db.example.com:5432/appdb"
    assert resolve_field(connection, "password") == "secret-pass"
    assert resolve_field(connection, "username") == "appuser"
    assert resolve_field(connection, "database") == "appdb"
    assert resolve_field(connection, "host") == "db.example.com"
    assert resolve_field(connection, "port") == "5432"
    assert resolve_field(connection, "extra:auth_token") == "turso-token-123"
    assert resolve_field(connection, "extra:missing") is None
    assert resolve_field(connection, "bogus") is None


def test_build_env_for_app_injects_linked_databases(db, sample_app):
    from app.models.infrastructure import ApplicationDatabaseLink, DatabaseConnection

    connection = DatabaseConnection(
        name="neon-main", provider="neon", engine="postgresql",
        username="appuser",
        url_encrypted=encrypt_secret("postgresql://u:p@ep-x.neon.tech/appdb?sslmode=require"),
        extra_secrets={},
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    link = ApplicationDatabaseLink(
        application_id=sample_app.id,
        connection_id=connection.id,
        env_mapping={"DATABASE_URL": "url", "DB_USER": "username"},
    )
    db.add(link)
    db.commit()

    env = build_env_for_app(db, sample_app.id)
    assert env["DATABASE_URL"] == "postgresql://u:p@ep-x.neon.tech/appdb?sslmode=require"
    assert env["DB_USER"] == "appuser"


# ----------------------------------------------------------------- cloudflare

def test_build_ingress_inserts_before_catch_all():
    existing = [
        {"hostname": "a.example.com", "service": "http://ld-a:80"},
        {"service": "http_status:404"},
    ]
    merged = build_ingress(existing, "b.example.com", "http://ld-b:3000")
    assert merged[0] == {"hostname": "b.example.com", "service": "http://ld-b:3000",
                         "origin_request": {"no_tls_verify": True}}
    assert merged[-1] == {"service": "http_status:404"}
    assert {"hostname": "a.example.com", "service": "http://ld-a:80"} in merged
    assert len(merged) == 3


def test_build_ingress_replaces_existing_hostname():
    existing = [
        {"hostname": "app.example.com", "service": "http://ld-app:80"},
        {"service": "http_status:404"},
    ]
    merged = build_ingress(existing, "app.example.com", "http://ld-app:3000")
    rules_for_host = [r for r in merged if r.get("hostname") == "app.example.com"]
    assert len(rules_for_host) == 1
    assert rules_for_host[0]["service"] == "http://ld-app:3000"


def test_find_zone_longest_suffix_match():
    zones = [{"id": "1", "name": "example.co.id", "status": "active"},
             {"id": "2", "name": "co.id", "status": "active"}]
    assert find_zone_for_hostname(zones, "app.example.co.id")["id"] == "1"
    assert find_zone_for_hostname(zones, "other.com") is None
