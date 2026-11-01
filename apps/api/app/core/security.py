"""Security primitives: Argon2id password hashing, session tokens, Fernet encryption.

The Fernet key is derived from SECRET_KEY via HKDF-SHA256 so that rotating
SECRET_KEY invalidates stored ciphertexts on purpose (never silently keeps old key).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import settings

_password_hasher = PasswordHasher()  # Argon2id defaults

_FERNET_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"localdeploy:fernet:v1",
        info=b"localdeploy:secret-box",
    )
    key = base64.urlsafe_b64encode(kdf.derive(settings.secret_key.encode()))
    return Fernet(key)


# ---------------------------------------------------------------------------
# Passwords (Argon2id)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


PASSWORD_MIN_LENGTH = 8


def password_policy_error(password: str) -> str | None:
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters long."
    return None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


# ---------------------------------------------------------------------------
# Secret encryption at rest
# ---------------------------------------------------------------------------

def encrypt_secret(plaintext: str) -> str:
    token = _fernet().encrypt(plaintext.encode())
    return _FERNET_PREFIX + token.decode()


def decrypt_secret(ciphertext: str) -> str:
    if not ciphertext.startswith(_FERNET_PREFIX):
        return ciphertext  # legacy/plain value
    token = ciphertext[len(_FERNET_PREFIX):].encode()
    try:
        return _fernet().decrypt(token).decode()
    except InvalidToken as exc:  # wrong key or corrupted value
        raise ValueError("Cannot decrypt secret: invalid key or corrupted value") from exc


def redact(value: str | None, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "***"
    return value[:keep] + "***"


# ---------------------------------------------------------------------------
# Webhook signature verification (GitHub / GitLab / generic HMAC-SHA256)
# ---------------------------------------------------------------------------

def verify_hmac_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC verification. Accepts 'sha256=<hex>' (GitHub/Gitea)
    or bare hex digest (GitLab token style is checked by caller)."""
    if not signature or not secret:
        return False
    if signature.startswith("sha256="):
        signature = signature[len("sha256="):]
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def safe_json(data: dict[str, Any] | None) -> dict[str, Any]:
    return data if isinstance(data, dict) else {}
