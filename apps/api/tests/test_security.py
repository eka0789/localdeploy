"""Security primitives: hashing, encryption, HMAC, hostname validation, Traefik labels."""
from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    new_session_token,
    password_policy_error,
    verify_hmac_signature,
    verify_password,
)
from app.services.traefik import traefik_labels, validate_hostname


def test_password_hash_roundtrip():
    hashed = hash_password("s3cret-password")
    assert hashed != "s3cret-password"
    assert hashed.startswith("$argon2id$")
    assert verify_password("s3cret-password", hashed)
    assert not verify_password("wrong", hashed)


def test_password_policy():
    assert password_policy_error("short") is not None
    assert password_policy_error("long-enough-password") is None


def test_secret_encryption_roundtrip():
    secret = "super-secret-db-password-123!"
    encrypted = encrypt_secret(secret)
    assert encrypted.startswith("enc:v1:")
    assert secret not in encrypted
    assert decrypt_secret(encrypted) == secret


def test_encryption_is_deterministic_key_bound():
    token = encrypt_secret("value")
    assert decrypt_secret(token) == "value"
    assert token != encrypt_secret("value")  # fernet adds randomness


def test_hmac_signature():
    import hashlib
    import hmac as hmac_mod

    payload = b'{"ref": "refs/heads/main"}'
    secret = "whsec_123"
    good = "sha256=" + hmac_mod.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_hmac_signature(payload, good, secret)
    assert not verify_hmac_signature(payload, "sha256=deadbeef", secret)


def test_session_token_uniqueness():
    tokens = {new_session_token() for _ in range(100)}
    assert len(tokens) == 100
    assert len(hash_token("abc")) == 64


def test_hostname_validation():
    assert validate_hostname("app.example.com") is None
    assert validate_hostname("*.example.com") is None
    assert validate_hostname("a.b") is not None
    assert validate_hostname("-bad.example.com") is not None
    assert validate_hostname("under_score.example.com") is not None
    assert validate_hostname("") is not None


def test_traefik_labels_http_and_https():
    labels = traefik_labels(
        "myapp",
        [("app.example.com", None, True), ("api.example.com", 9000, False)],
        container_port=3000,
    )
    assert labels["traefik.enable"] == "true"
    # shared service name → Traefik load-balances across replicas
    assert labels["traefik.http.services.svc-myapp.loadbalancer.server.port"] == "3000"
    assert labels["traefik.http.routers.myapp-0.rule"] == "Host(`app.example.com`)"
    assert labels["traefik.http.routers.myapp-0.service"] == "svc-myapp"
    assert labels["traefik.http.routers.myapp-0.tls"] == "true"
    assert labels["traefik.http.routers.myapp-0.tls.certresolver"] == "letsencrypt"
    # http entrypoint for the ssl domain redirects
    assert labels["traefik.http.routers.myapp-0-http.middlewares"] == "redirect-to-https"
    # non-ssl domain uses http only
    assert labels["traefik.http.routers.myapp-1.entrypoints"] == "http"
    # per-domain port override creates its own service
    assert labels["traefik.http.services.svc-myapp-1.loadbalancer.server.port"] == "9000"


def test_autoscale_decision_hysteresis():
    from app.services.scaling import decide_autoscale

    # 3 consecutive high samples → scale up
    t, h, l, action = decide_autoscale(1, 90, 70, 1, 3, 0, 0)
    assert (t, action) == (1, "hold")
    _, h, _, _ = decide_autoscale(1, 90, 70, 1, 3, h, 0)
    t, h, l, action = decide_autoscale(1, 90, 70, 1, 3, h, 0)
    assert action == "scale_up" and t == 2

    # respects maximum
    t, _, _, action = decide_autoscale(3, 95, 70, 1, 3, 2, 0)
    assert action in ("hold", "scale_up") and t <= 3

    # 6 consecutive low samples → scale down
    t, h, l, action = (2, 0, 0, "hold")
    for _ in range(6):
        t, h, l, action = decide_autoscale(t, 10, 70, 1, 3, h, l)
    assert action == "scale_down" and t == 1
