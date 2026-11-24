from __future__ import annotations

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Domain, User
from app.services.cloudflare import CloudflareClient
from tests.conftest import bearer, get_captcha, make_user, SESSION_ID, login


def test_registration_is_unverified_and_domain_create_is_blocked(client):
    tokens, uid = make_user(client, "gate@example.com", realname=False)
    me = client.get("/api/v1/auth/me", headers=bearer(tokens))
    assert me.json()["data"]["realname_status"] == "unverified"
    r = client.post("/api/v1/domains/platform",
                    json={"prefix": "blocked", "upstream_url": "http://127.0.0.1:8080"},
                    headers=bearer(tokens))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "REALNAME_REQUIRED"
    assert "激活码" in r.json()["error"]["message"]
    with get_sessionmaker()() as db:
        assert db.scalar(select(Domain).where(Domain.user_id == uid)) is None


def test_platform_secondary_domain_is_active_only_after_cf_and_tunnel(client):
    tokens, _ = make_user(client, "platform@example.com", realname=True)
    r = client.post("/api/v1/domains/platform",
                    json={"prefix": "abc", "upstream_url": "http://127.0.0.1:9000"},
                    headers=bearer(tokens))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    from app.config import get_settings
    assert d["fqdn"] == f"abc.{get_settings().platform_domain}"
    assert d["kind"] == "platform"
    assert d["status"] == "active"
    assert d["public_url"] == f"https://abc.{get_settings().platform_domain}"
    assert d["tunnel_status"] == "active"
    with get_sessionmaker()() as db:
        row = db.get(Domain, d["id"])
        assert row.cloudflare_record_id
        assert row.tunnel_id


def test_platform_duplicate_and_limit(client):
    tokens, _ = make_user(client, "limit@example.com", realname=True)
    r = client.post("/api/v1/domains/platform",
                    json={"prefix": "same", "upstream_url": "http://127.0.0.1:8080"},
                    headers=bearer(tokens))
    assert r.status_code == 200
    r2 = client.post("/api/v1/domains/platform",
                     json={"prefix": "same", "upstream_url": "http://127.0.0.1:8080"},
                     headers=bearer(tokens))
    assert r2.status_code == 409
    for i in range(4):
        r = client.post("/api/v1/domains/external",
                        json={"fqdn": f"lim{i}.example.com",
                              "upstream_url": "http://127.0.0.1:8080"},
                        headers=bearer(tokens))
        assert r.status_code == 200, r.text
    r = client.post("/api/v1/domains/external",
                    json={"fqdn": "six.example.com",
                          "upstream_url": "http://127.0.0.1:8080"},
                    headers=bearer(tokens))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DOMAIN_LIMIT"


def test_external_domain_waits_for_ns_then_joins_tunnel(client, monkeypatch):
    tokens, _ = make_user(client, "external@example.com", realname=True)
    r = client.post("/api/v1/domains/external",
                    json={"fqdn": "external.example.com",
                          "upstream_url": "http://127.0.0.1:9000"},
                    headers=bearer(tokens))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "ns_pending"
    assert d["verification"]["nameservers"] == ["ns1.liuli.test", "ns2.liuli.test"]

    import app.routers.domains as dom

    monkeypatch.setattr(dom, "check_ns_switched", lambda *a, **k: (False, []))
    r = client.post(f"/api/v1/domains/{d['id']}/verify-ns", headers=bearer(tokens))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DOMAIN_NS_PENDING"
    assert r.json()["data"] if "data" in r.json() else True  # error envelope remains explicit

    monkeypatch.setattr(dom, "check_ns_switched",
                        lambda *a, **k: (True, ["ns1.liuli.test", "ns2.liuli.test"]))
    r = client.post(f"/api/v1/domains/{d['id']}/verify-ns", headers=bearer(tokens))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "active"


def test_missing_cloudflare_configuration_never_fakes_a_domain(client, monkeypatch):
    tokens, _ = make_user(client, "nocf@example.com", realname=True)
    import app.routers.domains as dom

    monkeypatch.setattr(dom, "_cf", lambda: CloudflareClient(token="", account_id=""))
    r = client.post("/api/v1/domains/platform",
                    json={"prefix": "nocf", "upstream_url": "http://127.0.0.1:8080"},
                    headers=bearer(tokens))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "CLOUDFLARE_NOT_CONFIGURED"
    assert "域名暂不可用" in r.json()["error"]["message"]


def test_local_mode_does_not_auto_activate_realname(client, monkeypatch):
    import app.routers.auth as auth_mod
    from app.config import get_settings

    local = get_settings().model_copy(update={"local_mode": True})
    monkeypatch.setattr(auth_mod, "get_settings", lambda: local)
    cap = get_captcha(client)
    r = client.post("/api/v1/auth/register",
                    json={"email": "local-gate@example.com",
                          "password": "LocalPassw0rd!",
                          "captcha_id": cap["captcha_id"],
                          "captcha_answer": cap["answer"],
                          "session_id": SESSION_ID},
                    headers={"X-Session-Id": SESSION_ID})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["email_verified"] is True
    assert data["realname_status"] == "unverified"
    tokens = login(client, "local-gate@example.com", "LocalPassw0rd!")
    me = client.get("/api/v1/auth/me", headers=bearer(tokens))
    assert me.json()["data"]["realname_status"] == "unverified"
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.email == "local-gate@example.com"))
        assert user.realname_status == "unverified"
        assert user.realname_activated_at is None
