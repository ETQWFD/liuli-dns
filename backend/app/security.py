"""Small crypto/auth primitives. Everything sensitive is hashed or encrypted."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings

# Argon2id: 64 MiB, 3 passes, 4 lanes, 32-byte hash, 16-byte salt.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity
REDACT_KEYS = re.compile(
    r"(?i)(password|passwd|token|secret|authorization|private[_ -]?key|api[_ -]?key|"
    r"cert[_ -]?key|refresh|cookie|set-cookie|身份证|证件号)"
)


def utcnow() -> datetime:
    """Naive UTC timestamp (DB stores naive UTC consistently)."""
    return datetime.now(UTC).replace(tzinfo=None)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, ValueError):
        return False


def new_access_token(user_id: int, role: str, ttl: int | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + (ttl or s.access_ttl_seconds),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    s = get_settings()
    payload = jwt.decode(
        token, s.secret_key, algorithms=["HS256"], options={"require": ["exp", "sub", "type"]}
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Return (raw token for client, sha256 hash for DB)."""
    raw = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.strip().upper())


def generate_activation_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(20))
    return "-".join(raw[i : i + 5] for i in range(0, 20, 5))


def hmac_code(code: str) -> str:
    """HMAC-SHA256(pepper, normalized code). The plaintext code is never stored."""
    s = get_settings()
    msg = normalize_code(code).encode()
    return hmac.new(s.code_pepper.encode(), msg, hashlib.sha256).hexdigest()


def hmac_document(doc_number: str) -> str:
    s = get_settings()
    msg = re.sub(r"[^0-9A-Za-z]", "", doc_number).upper().encode()
    return hmac.new(s.doc_pepper.encode(), msg, hashlib.sha256).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _aes_key() -> bytes:
    s = get_settings()
    key = base64.urlsafe_b64decode(s.cert_master_key)
    if len(key) != 32:
        raise RuntimeError("CERT_MASTER_KEY must decode to 32 bytes")
    return key


def encrypt_secret(plaintext: str) -> str:
    """AES-256-GCM. Output: v1:<base64(nonce|tag|ciphertext)>."""
    nonce = os_urandom(12)
    ct_and_tag = AESGCM(_aes_key()).encrypt(nonce, plaintext.encode(), b"liuli-cert-v1")
    return "v1:" + base64.urlsafe_b64encode(nonce + ct_and_tag).decode()


def decrypt_secret(blob: str) -> str:
    if not blob.startswith("v1:"):
        raise ValueError("unsupported cipher format")
    data = base64.urlsafe_b64decode(blob[3:])
    nonce, ct_and_tag = data[:12], data[12:]
    return AESGCM(_aes_key()).decrypt(nonce, ct_and_tag, b"liuli-cert-v1").decode()


def os_urandom(n: int) -> bytes:
    return secrets.token_bytes(n)


def mask_email(email: str) -> str:
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return "***"
    keep = local[:2] if len(local) > 2 else local[:1]
    return f"{keep}{'*' * max(1, len(local) - len(keep))}@{domain}"


def redact_value(value: Any) -> Any:
    """Best-effort redaction for log payloads; never used on outbound API data."""
    if isinstance(value, dict):
        return {
            k: ("***" if REDACT_KEYS.search(str(k)) else redact_value(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_value(v) for v in value[:20]]
    if isinstance(value, str):
        value = re.sub(r"(?i)bearer\s+[a-z0-9._\-]+", "Bearer ***", value)
        value = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", "<email>", value)
        value = re.sub(r"\b\d{17}[\dXx]\b", "<id>", value)
        value = re.sub(r"\b\d{15}\b", "<id>", value)
        if "BEGIN" in value and "PRIVATE KEY" in value:
            return "<private-key-redacted>"
        return value[:500]
    return value


def hash_ip(ip: str) -> str:
    s = get_settings()
    return hmac.new(s.secret_key.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]
