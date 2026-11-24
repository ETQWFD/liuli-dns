from __future__ import annotations

from app.db import get_sessionmaker
from app.models import Domain
from app.security import utcnow
from tests.conftest import bearer, make_user


def _make_domain(client, tokens, fqdn="example.com") -> int:
    r = client.post("/api/v1/domains", json={"fqdn": fqdn}, headers=bearer(tokens))
    assert r.status_code == 200, r.text
    did = r.json()["data"]["id"]
    with get_sessionmaker()() as db:
        d = db.get(Domain, did)
        d.status = "active"
        d.verified_at = utcnow()
        db.commit()
    return did


def test_create_domain_requires_realname(client):
    tokens, _ = make_user(client, "d0@example.com", realname=False)
    r = client.post("/api/v1/domains", json={"fqdn": "nope.com"}, headers=bearer(tokens))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "REALNAME_REQUIRED"


def test_create_and_verify_domain(client, monkeypatch):
    tokens, _ = make_user(client, "d1@example.com", realname=True)
    r = client.post("/api/v1/domains", json={"fqdn": "Example.COM."}, headers=bearer(tokens))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["fqdn"] == "example.com"
    assert data["status"] == "ns_pending"
    assert data["verification"]["nameservers"] == ["ns1.liuli.test", "ns2.liuli.test"]
    assert data["verification"]["txt_name"] == "_liuli-verify.example.com"

    import app.routers.domains as dom_mod

    monkeypatch.setattr(dom_mod, "check_ns_switched", lambda *a, **k: (True, ["ns1.liuli.test", "ns2.liuli.test"]))
    r = client.post(f"/api/v1/domains/{data['id']}/verify", headers=bearer(tokens))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "active"

    dup = client.post("/api/v1/domains", json={"fqdn": "example.com"}, headers=bearer(tokens))
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "DOMAIN_EXISTS"


def test_invalid_domain(client):
    tokens, _ = make_user(client, "d2@example.com", realname=True)
    for bad in ("localhost", "-bad.com", "bad trailer.com", "a..b.com"):
        r = client.post("/api/v1/domains", json={"fqdn": bad}, headers=bearer(tokens))
        assert r.status_code == 422, (bad, r.text)
    r = client.post("/api/v1/domains", json={"fqdn": "liuli.test"}, headers=bearer(tokens))
    assert r.status_code == 422


def test_batch_idempotency_and_rollback(client):
    tokens, _ = make_user(client, "d3@example.com", realname=True)
    did = _make_domain(client, tokens, "batch.example.com")
    headers = {**bearer(tokens), "X-Idempotency-Key": "key-1"}
    body = {
        "records": [
            {"name": "@", "type": "A", "ttl": 300, "value": "203.0.113.10"},
            {"name": "www", "type": "CNAME", "ttl": 300, "value": "batch.example.com"},
            {"name": "@", "type": "MX", "ttl": 300, "value": "mail.example.com", "priority": 10},
            {"name": "@", "type": "TXT", "ttl": 300, "value": "v=spf1 -all"},
        ],
        "mode": "replace",
    }
    r = client.post(f"/api/v1/domains/{did}/records/batch", json=body, headers=headers)
    assert r.status_code == 200, r.text
    v1 = r.json()["data"]["version"]
    assert len(r.json()["data"]["items"]) == 4

    r2 = client.post(f"/api/v1/domains/{did}/records/batch", json=body, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["data"]["version"] == v1  # cached, no extra version

    changed = {**body, "records": body["records"][:1]}
    r3 = client.post(f"/api/v1/domains/{did}/records/batch", json=changed, headers=headers)
    assert r3.status_code == 409
    assert r3.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    headers2 = {**bearer(tokens), "X-Idempotency-Key": "key-2"}
    r4 = client.post(f"/api/v1/domains/{did}/records/batch",
                     json={"records": [{"name": "v6", "type": "AAAA", "value": "2001:db8::1"}],
                           "mode": "merge"}, headers=headers2)
    assert r4.status_code == 200
    assert r4.json()["data"]["version"] == v1 + 1

    r5 = client.post(f"/api/v1/domains/{did}/records/rollback/{v1}", headers=bearer(tokens))
    assert r5.status_code == 200
    assert len(r5.json()["data"]["items"]) == 4
    assert r5.json()["data"]["version"] == v1 + 2

    revs = client.get(f"/api/v1/domains/{did}/revisions", headers=bearer(tokens))
    assert revs.status_code == 200
    assert len(revs.json()["data"]["items"]) >= 3


def test_record_validation(client):
    tokens, _ = make_user(client, "d4@example.com", realname=True)
    did = _make_domain(client, tokens, "val.example.com")
    h = {**bearer(tokens), "X-Idempotency-Key": "bad-1"}

    r = client.post(f"/api/v1/domains/{did}/records/batch",
                    json={"records": [{"name": "@", "type": "A", "value": "999.1.1.1"}]}, headers=h)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "RECORD_INVALID"

    h = {**bearer(tokens), "X-Idempotency-Key": "bad-2"}
    r = client.post(f"/api/v1/domains/{did}/records/batch",
                    json={"records": [{"name": "@", "type": "CNAME", "value": "other.com"}]},
                    headers=h)
    assert r.status_code == 422

    h = {**bearer(tokens), "X-Idempotency-Key": "bad-3"}
    r = client.post(f"/api/v1/domains/{did}/records/batch",
                    json={"records": [
                        {"name": "x", "type": "A", "value": "1.2.3.4"},
                        {"name": "x", "type": "CNAME", "value": "other.com"},
                    ]}, headers=h)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "RECORD_CONFLICT"

    h = {**bearer(tokens), "X-Idempotency-Key": "ok-1"}
    r = client.post(f"/api/v1/domains/{did}/records/batch",
                    json={"records": [{"name": "x", "type": "A", "value": "1.2.3.4"}],
                          "mode": "replace"}, headers=h)
    assert r.status_code == 200
    rid = r.json()["data"]["items"][0]["id"]

    r = client.patch(f"/api/v1/domains/{did}/records/{rid}",
                     json={"name": "x", "type": "A", "ttl": 600, "value": "1.2.3.5"},
                     headers=bearer(tokens))
    assert r.status_code == 200
    updated = r.json()["data"]["items"][0]
    assert updated["ttl"] == 600
    rid = updated["id"]

    r = client.delete(f"/api/v1/domains/{did}/records/{rid}", headers=bearer(tokens))
    assert r.status_code == 200
    assert r.json()["data"]["items"] == []


def test_cross_user_isolation(client):
    tokens_a, _ = make_user(client, "d5a@example.com", realname=True)
    tokens_b, _ = make_user(client, "d5b@example.com", realname=True)
    did = _make_domain(client, tokens_a, "private.example.com")
    r = client.get(f"/api/v1/domains/{did}", headers=bearer(tokens_b))
    assert r.status_code == 404
    r = client.delete(f"/api/v1/domains/{did}", headers=bearer(tokens_b))
    assert r.status_code == 404
    r = client.get(f"/api/v1/domains/{did}/records", headers=bearer(tokens_b))
    assert r.status_code == 404


def test_reconcile_and_delete(client):
    tokens, _ = make_user(client, "d6@example.com", realname=True)
    did = _make_domain(client, tokens, "recon.example.com")
    h = {**bearer(tokens), "X-Idempotency-Key": "rec-1"}
    client.post(f"/api/v1/domains/{did}/records/batch",
                json={"records": [{"name": "www", "type": "A", "value": "198.51.100.7"}]},
                headers=h)
    r = client.post(f"/api/v1/domains/{did}/reconcile", headers=bearer(tokens))
    assert r.status_code == 200
    assert r.json()["data"]["records"] == 1
    r = client.delete(f"/api/v1/domains/{did}", headers=bearer(tokens))
    assert r.status_code == 200
    r = client.get(f"/api/v1/domains/{did}", headers=bearer(tokens))
    assert r.status_code == 404
