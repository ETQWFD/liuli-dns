from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Certificate, Domain
from app.security import decrypt_secret, utcnow
from tests.conftest import bearer, make_user


def _cert(domain: str, days: int = 365, key=None):
    if key is None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Liuli Test"),
        x509.NameAttribute(NameOID.COMMON_NAME, domain),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(domain)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem, key


def _domain(client, tokens, fqdn="cert.example.com") -> int:
    r = client.post("/api/v1/domains", json={"fqdn": fqdn}, headers=bearer(tokens))
    assert r.status_code == 200, r.text
    did = r.json()["data"]["id"]
    with get_sessionmaker()() as db:
        d = db.get(Domain, did)
        d.status = "active"
        d.verified_at = utcnow()
        db.commit()
    return did


def _upload(client, tokens, did, cert_pem, key_pem, chain=None, password=None):
    files = {
        "cert": ("cert.pem", cert_pem, "application/x-pem-file"),
        "key": ("key.pem", key_pem, "application/x-pem-file"),
    }
    if chain:
        files["chain"] = ("chain.pem", chain, "application/x-pem-file")
    data = {"password": password} if password else {}
    return client.post(f"/api/v1/domains/{did}/certificates",
                       files=files, data=data, headers=bearer(tokens))


def test_upload_encrypts_private_key(client, db):
    tokens, _ = make_user(client, "c1@example.com", realname=True)
    did = _domain(client, tokens)
    cert_pem, key_pem, _ = _cert("cert.example.com")
    r = _upload(client, tokens, did, cert_pem, key_pem)
    assert r.status_code == 200, r.text
    body = r.text
    assert "PRIVATE KEY" not in body
    assert "key_cipher" not in body
    data = r.json()["data"]
    assert data["common_name"] == "cert.example.com"
    assert "cert.example.com" in data["sans"]
    assert data["days_left"] >= 360

    row = db.scalar(select(Certificate).where(Certificate.domain_id == did))
    assert row.key_cipher.startswith("v1:")
    assert "PRIVATE KEY" not in row.key_cipher
    plain = decrypt_secret(row.key_cipher)
    assert "BEGIN PRIVATE KEY" in plain

    lst = client.get(f"/api/v1/domains/{did}/certificates", headers=bearer(tokens))
    assert lst.status_code == 200
    assert "PRIVATE KEY" not in lst.text
    assert len(lst.json()["data"]["items"]) == 1


def test_key_mismatch_and_domain_mismatch(client):
    tokens, _ = make_user(client, "c2@example.com", realname=True)
    did = _domain(client, tokens)
    cert_pem, _, _ = _cert("cert.example.com")
    _, other_key, _ = _cert("cert.example.com")
    r = _upload(client, tokens, did, cert_pem, other_key)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CERT_KEY_MISMATCH"

    other_cert, other_key2, _ = _cert("other.example.com")
    r = _upload(client, tokens, did, other_cert, other_key2)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CERT_DOMAIN_MISMATCH"


def test_certificate_requires_active_domain(client):
    tokens, _ = make_user(client, "c3@example.com", realname=True)
    r = client.post("/api/v1/domains", json={"fqdn": "pending.example.com"}, headers=bearer(tokens))
    did = r.json()["data"]["id"]
    cert_pem, key_pem, _ = _cert("pending.example.com")
    r = _upload(client, tokens, did, cert_pem, key_pem)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "DOMAIN_NOT_ACTIVE"


def test_replace_and_activate(client, db):
    tokens, _ = make_user(client, "c4@example.com", realname=True)
    did = _domain(client, tokens)
    c1, k1, _ = _cert("cert.example.com", days=300)
    c2, k2, _ = _cert("cert.example.com", days=90)
    r1 = _upload(client, tokens, did, c1, k1)
    assert r1.status_code == 200
    cid1 = r1.json()["data"]["id"]
    r2 = _upload(client, tokens, did, c2, k2)
    assert r2.status_code == 200
    cid2 = r2.json()["data"]["id"]

    with get_sessionmaker()() as s:
        statuses = {c.id: c.status for c in s.scalars(select(Certificate)).all()}
    assert statuses[cid1] == "replaced"
    assert statuses[cid2] == "active"

    r = client.post(f"/api/v1/domains/{did}/certificates/{cid1}/activate", headers=bearer(tokens))
    assert r.status_code == 200
    with get_sessionmaker()() as s:
        assert s.get(Certificate, cid1).status == "active"
        assert s.get(Certificate, cid2).status == "replaced"


def test_expiring(client):
    tokens, _ = make_user(client, "c5@example.com", realname=True)
    did = _domain(client, tokens)
    cert_pem, key_pem, _ = _cert("cert.example.com", days=10)
    r = _upload(client, tokens, did, cert_pem, key_pem)
    assert r.status_code == 200
    r = client.get("/api/v1/certificates/expiring?days=45", headers=bearer(tokens))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["domain"] == "cert.example.com"


def test_delete_certificate(client):
    tokens, _ = make_user(client, "c6@example.com", realname=True)
    did = _domain(client, tokens)
    cert_pem, key_pem, _ = _cert("cert.example.com")
    r = _upload(client, tokens, did, cert_pem, key_pem)
    cid = r.json()["data"]["id"]
    r = client.delete(f"/api/v1/domains/{did}/certificates/{cid}", headers=bearer(tokens))
    assert r.status_code == 200
    with get_sessionmaker()() as s:
        assert s.get(Certificate, cid) is None


def test_acme_is_explicitly_unavailable(client):
    tokens, _ = make_user(client, "c7@example.com", realname=True)
    did = _domain(client, tokens)
    r = client.post(f"/api/v1/domains/{did}/certificates/acme/order", headers=bearer(tokens))
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "CERT_NOT_CONFIGURED"
    assert "上传" in r.json()["error"]["message"]
