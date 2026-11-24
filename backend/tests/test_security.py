from __future__ import annotations

import base64
import os

import pytest

from app.config import Settings
from app.security import (
    decrypt_secret,
    encrypt_secret,
    hash_ip,
    hash_password,
    hmac_code,
    normalize_code,
    redact_value,
    verify_password,
)
from tests.conftest import bearer, make_user


def test_aes_gcm_roundtrip():
    plain = "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----"
    blob = encrypt_secret(plain)
    assert blob.startswith("v1:")
    assert "PRIVATE" not in blob
    assert decrypt_secret(blob) == plain
    blob2 = encrypt_secret(plain)
    assert blob != blob2  # random nonce


def test_password_hashing_is_argon2id():
    h = hash_password("CorrectHorseBattery9")
    assert h.startswith("$argon2id$")
    assert verify_password("CorrectHorseBattery9", h)
    assert not verify_password("wrong", h)


def test_activation_code_normalization_and_hmac():
    a = hmac_code("abcde-fghjk-lmnpq-rstuv")
    b = hmac_code("ABCDE FGHJK LMNPQ RSTUV")
    assert a == b
    assert len(a) == 64
    assert normalize_code("ab-cd ef") == "ABCDEF"


def test_redaction_hides_secrets():
    text = (
        "Authorization: Bearer abc.def.ghi password=Hunter2 token=xyz "
        "user@example.com 110101199001011234 "
        "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----"
    )
    out = redact_value(text)
    assert "Hunter2" not in out
    assert "abc.def.ghi" not in out
    assert "user@example.com" not in out
    assert "110101199001011234" not in out
    assert "PRIVATE" not in out
    assert redact_value({"password": "x", "nested": {"token": "y"}})["password"] == "***"


def test_ip_hash_is_stable_and_not_plaintext():
    a = hash_ip("198.51.100.1")
    assert a == hash_ip("198.51.100.1")
    assert a != "198.51.100.1"
    assert len(a) == 32


def test_production_requires_explicit_secrets():
    s = Settings(
        app_env="prod", secret_key="", cert_master_key="", code_pepper="", doc_pepper="",
    )
    with pytest.raises(RuntimeError):
        s.validate_runtime()


def test_openapi_has_no_secret_fields(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    body = r.text.lower()
    for forbidden in ("key_cipher", "cert_master_key", "code_pepper", "doc_pepper", "refresh_hash"):
        assert forbidden not in body


def test_tools_dns_check(client, monkeypatch):
    tokens, _ = make_user(client, "t1@example.com")
    import app.routers.tools as tools_mod

    monkeypatch.setattr(tools_mod, "query", lambda n, t: ["203.0.113.77"])
    r = client.get("/api/v1/tools/dns-check?name=example.com&type=A", headers=bearer(tokens))
    assert r.status_code == 200
    assert r.json()["data"]["answers"] == ["203.0.113.77"]
    r = client.get("/api/v1/tools/dns-check?name=x&type=BOGUS", headers=bearer(tokens))
    assert r.status_code == 422


def test_port_check_blocks_private(client, monkeypatch):
    tokens, _ = make_user(client, "t2@example.com", realname=True)
    r = client.post("/api/v1/domains", json={"fqdn": "port.example.com"}, headers=bearer(tokens))
    did = r.json()["data"]["id"]
    import app.routers.tools as tools_mod

    monkeypatch.setattr(tools_mod, "check_a", lambda fqdn: ["127.0.0.1"])
    r = client.post("/api/v1/tools/port-check", json={"domain_id": did, "port": 80},
                    headers=bearer(tokens))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DOMAIN_VERIFY_FAILED"


def test_tool_port_requires_owned_domain(client, monkeypatch):
    tokens_a, _ = make_user(client, "t3a@example.com")
    tokens_b, _ = make_user(client, "t3b@example.com", realname=True)
    r = client.post("/api/v1/domains", json={"fqdn": "owned.example.com"}, headers=bearer(tokens_b))
    did = r.json()["data"]["id"]
    r = client.post("/api/v1/tools/port-check", json={"domain_id": did, "port": 80},
                    headers=bearer(tokens_a))
    assert r.status_code == 404
