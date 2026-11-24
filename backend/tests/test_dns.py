from __future__ import annotations

import dnslib
from dnslib import DNSRecord, RCODE, QTYPE

from app.db import get_sessionmaker
from app.dns.server import AuthoritativeResolver, DNSRateLimiter, ZoneStore
from app.models import Domain
from app.security import utcnow
from tests.conftest import bearer, make_user


class FakeHandler:
    client_address = ("198.51.100.9", 5353)


def _seed(client, tokens, fqdn: str, records: list[dict], key: str) -> int:
    r = client.post("/api/v1/domains", json={"fqdn": fqdn}, headers=bearer(tokens))
    assert r.status_code == 200, r.text
    did = r.json()["data"]["id"]
    with get_sessionmaker()() as db:
        d = db.get(Domain, did)
        d.status = "active"
        d.verified_at = utcnow()
        db.commit()
    h = {**bearer(tokens), "X-Idempotency-Key": key}
    r = client.post(f"/api/v1/domains/{did}/records/batch",
                    json={"records": records, "mode": "replace"}, headers=h)
    assert r.status_code == 200, r.text
    return did


def _resolver(per_ip: int = 1000) -> AuthoritativeResolver:
    store = ZoneStore(refresh_seconds=1, ns_hosts=["ns1.liuli.test", "ns2.liuli.test"])
    store.refresh()
    return AuthoritativeResolver(store, DNSRateLimiter(per_ip, 1000), "liuli.test")


def _q(resolver, name: str, rtype: str = "A") -> DNSRecord:
    return resolver.resolve(DNSRecord.question(name, rtype), FakeHandler())


def test_a_aaaa_cname_txt_mx(client):
    tokens, _ = make_user(client, "dns1@example.com", realname=True)
    _seed(client, tokens, "dns1.test", [
        {"name": "@", "type": "A", "ttl": 300, "value": "203.0.113.10"},
        {"name": "v6", "type": "AAAA", "ttl": 300, "value": "2001:db8::1"},
        {"name": "alias", "type": "CNAME", "ttl": 300, "value": "dns1.test"},
        {"name": "@", "type": "TXT", "ttl": 300, "value": "v=spf1 -all"},
        {"name": "@", "type": "MX", "ttl": 300, "value": "mail.dns1.test", "priority": 10},
    ], "dns-1")
    resolver = _resolver()

    a = _q(resolver, "dns1.test", "A")
    assert RCODE.get(a.header.rcode) == "NOERROR"
    assert a.header.aa == 1
    assert len(a.rr) == 1
    assert str(a.rr[0].rdata) == "203.0.113.10"

    aaaa = _q(resolver, "v6.dns1.test", "AAAA")
    assert len(aaaa.rr) == 1
    assert str(aaaa.rr[0].rdata) == "2001:db8::1"

    cn = _q(resolver, "alias.dns1.test", "A")
    assert len(cn.rr) == 1
    assert QTYPE.get(cn.rr[0].rtype) == "CNAME"

    txt = _q(resolver, "dns1.test", "TXT")
    assert "v=spf1 -all" in str(txt.rr[0].rdata)

    mx = _q(resolver, "dns1.test", "MX")
    assert "mail.dns1.test" in str(mx.rr[0].rdata)


def test_soa_ns_and_nodata(client):
    tokens, _ = make_user(client, "dns2@example.com", realname=True)
    did = _seed(client, tokens, "dns2.test", [
        {"name": "@", "type": "A", "ttl": 300, "value": "203.0.113.20"},
    ], "dns-2")
    resolver = _resolver()
    soa = _q(resolver, "dns2.test", "SOA")
    assert QTYPE.get(soa.rr[0].rtype) == "SOA"
    assert "hostmaster.liuli.test" in str(soa.rr[0].rdata)

    ns = _q(resolver, "dns2.test", "NS")
    assert len(ns.rr) == 2

    nodata = _q(resolver, "dns2.test", "AAAA")
    assert RCODE.get(nodata.header.rcode) == "NOERROR"
    assert len(nodata.rr) == 0 and len(nodata.auth) == 1
    assert len(nodata.auth) == 1

    nx = _q(resolver, "a.b.dns2.test", "A")
    assert RCODE.get(nx.header.rcode) == "NXDOMAIN"


def test_wildcard(client):
    tokens, _ = make_user(client, "dns3@example.com", realname=True)
    _seed(client, tokens, "wild.test", [
        {"name": "*", "type": "A", "ttl": 300, "value": "203.0.113.30"},
        {"name": "*.deep", "type": "A", "ttl": 300, "value": "203.0.113.31"},
    ], "dns-3")
    resolver = _resolver()
    one = _q(resolver, "foo.wild.test", "A")
    assert len(one.rr) == 1
    assert str(one.rr[0].rdata) == "203.0.113.30"
    two = _q(resolver, "x.deep.wild.test", "A")
    assert str(two.rr[0].rdata) == "203.0.113.31"
    none = _q(resolver, "a.b.wild.test", "A")
    assert RCODE.get(none.header.rcode) == "NXDOMAIN"


def test_refuses_outside_zone_and_any(client):
    tokens, _ = make_user(client, "dns4@example.com", realname=True)
    _seed(client, tokens, "dns4.test", [
        {"name": "@", "type": "A", "ttl": 300, "value": "203.0.113.40"},
    ], "dns-4")
    resolver = _resolver()
    outside = _q(resolver, "example.org", "A")
    assert RCODE.get(outside.header.rcode) == "REFUSED"
    assert outside.header.ra == 0
    assert outside.header.rd == 0
    anyq = resolver.resolve(DNSRecord.question("dns4.test", "ANY"), FakeHandler())
    assert RCODE.get(anyq.header.rcode) == "REFUSED"


def test_rate_limit(client):
    tokens, _ = make_user(client, "dns5@example.com", realname=True)
    _seed(client, tokens, "dns5.test", [
        {"name": "@", "type": "A", "ttl": 300, "value": "203.0.113.50"},
    ], "dns-5")
    resolver = _resolver(per_ip=1)
    first = _q(resolver, "dns5.test", "A")
    assert RCODE.get(first.header.rcode) == "NOERROR"
    second = _q(resolver, "dns5.test", "A")
    assert RCODE.get(second.header.rcode) == "REFUSED"


def test_pending_domain_not_served(client):
    tokens, _ = make_user(client, "dns6@example.com", realname=True)
    r = client.post("/api/v1/domains", json={"fqdn": "pending.test"}, headers=bearer(tokens))
    assert r.status_code == 200
    resolver = _resolver()
    out = _q(resolver, "pending.test", "A")
    assert RCODE.get(out.header.rcode) == "REFUSED"
