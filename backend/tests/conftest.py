"""Test bootstrap: env must be set before app modules read Settings."""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import pyotp
import pytest
from argon2 import PasswordHasher

TEST_DB = Path("/tmp/liuli_test.db")
ADMIN_PASSWORD = "Adm1n!StrongPassw0rd"
ADMIN_TOTP_SECRET = "JBSWY3DPEHPK3PXP"

os.environ.update({
    "LIULI_APP_ENV": "test",
    "LIULI_DATABASE_URL": f"sqlite:///{TEST_DB}",
    "LIULI_SECRET_KEY": "unit-test-secret-key-please-change-32b",
    "LIULI_CERT_MASTER_KEY": base64.urlsafe_b64encode(b"k" * 32).decode(),
    "LIULI_CODE_PEPPER": "unit-test-code-pepper",
    "LIULI_DOC_PEPPER": "unit-test-doc-pepper",
    "LIULI_PLATFORM_DOMAIN": "liuli.test",
    "LIULI_NS_HOSTNAMES": "ns1.liuli.test,ns2.liuli.test",
    "LIULI_SMTP_HOST": "",
    "LIULI_MAIL_OUTBOX_DIR": "/tmp/liuli_outbox",
    "LIULI_ADMIN_EMAIL": "admin@liuli.test",
    "LIULI_ADMIN_PASSWORD_HASH": PasswordHasher().hash(ADMIN_PASSWORD),
    "LIULI_ADMIN_TOTP_SECRET": ADMIN_TOTP_SECRET,
    "LIULI_GLOBAL_IP_PER_MINUTE": "100000",
    "LIULI_GLOBAL_INSTANCE_PER_MINUTE": "100000",
    "LIULI_DNS_QPS_PER_IP": "1000",
})

from fastapi.testclient import TestClient  # noqa: E402

from app.captcha import captcha_store  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.mailer import outbox  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.ratelimit import limiter  # noqa: E402

SESSION_ID = "pytest-session"


class FakeCloudflare:
    """Deterministic Cloudflare adapter for API-level tests.

    It still walks the same zone/CNAME/ingress methods as production code;
    no test claims a real Cloudflare deployment.
    """

    def ensure_zone(self, name: str, *, platform: bool = False, platform_zone_id: str = ""):
        return __import__("app.services.cloudflare", fromlist=["CFZone"]).CFZone(
            id="zone-test", name=name, nameservers=["ns1.liuli.test", "ns2.liuli.test"]
        )

    def ensure_cname(self, zone_id: str, fqdn: str, tunnel_id: str) -> str:
        return f"record-{fqdn}"

    def configure_ingress(self, tunnel_id: str, hostnames: list[str], proxy_port: int) -> None:
        return None

    def delete_dns_record(self, zone_id: str, record_id: str) -> None:
        return None


class FakeTunnelManager:
    def __init__(self):
        self.tunnel_id = "tunnel-test"

    def ensure_user_tunnel(self, db, user):
        return __import__("types").SimpleNamespace(tunnel_id=self.tunnel_id)

    def start(self, db, user):
        return self.status(db, user)

    def status(self, db, user):
        return {
            "configured": True, "running": True, "tunnel_id": self.tunnel_id,
            "active_connections": 0, "warn_connections": 800,
            "max_connections": 1000, "warning": False, "domain_count": 0,
            "last_error": "",
        }

    def configure_ingress(self, db, user, hostnames):
        return None

    def ensure_running(self, db, user):
        return None

    def sync(self, db, user):
        return None


@pytest.fixture(autouse=True)
def fake_cloudflare_and_tunnel(monkeypatch):
    import app.routers.domains as domains_mod

    monkeypatch.setattr(domains_mod, "_cf", lambda: FakeCloudflare())
    monkeypatch.setattr(domains_mod, "_tunnel", lambda: FakeTunnelManager())



@pytest.fixture(scope="session")
def client():
    if TEST_DB.exists():
        TEST_DB.unlink()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_state(client):
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
    limiter.reset()
    captcha_store.clear()
    outbox.clear()
    client.cookies.clear()
    yield


def _solve(question: str) -> str:
    m = re.match(r"(\d+) ([+x-]) (\d+) = \?", question.strip())
    assert m, question
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    return str(a + b if op == "+" else a - b if op == "-" else a * b)


def get_captcha(client) -> dict:
    r = client.post("/api/v1/auth/captcha", headers={"X-Session-Id": SESSION_ID})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    data["answer"] = _solve(data["question"])
    return data


def last_email_code(to: str) -> str:
    for mail in reversed(outbox):
        if mail["to"] == to:
            m = re.search(r"(\b[A-Z0-9]{5}-[A-Z0-9]{5}\b)", mail["text"])
            assert m, mail["text"]
            return m.group(1)
    raise AssertionError(f"no email for {to}")


def register(client, email: str, password: str = "UserPassw0rd!") -> None:
    cap = get_captcha(client)
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "captcha_id": cap["captcha_id"],
              "captcha_answer": cap["answer"], "session_id": SESSION_ID},
        headers={"X-Session-Id": SESSION_ID},
    )
    assert r.status_code == 200, r.text
    code = last_email_code(email)
    r = client.post("/api/v1/auth/verify-email", json={"code": code})
    assert r.status_code == 200, r.text


def login(client, email: str, password: str = "UserPassw0rd!") -> dict:
    cap = get_captcha(client)
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "captcha_id": cap["captcha_id"],
              "captcha_answer": cap["answer"]},
        headers={"X-Session-Id": SESSION_ID},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def make_user(client, email: str, realname: bool = False):
    register(client, email)
    tokens = login(client, email)
    user_id = tokens["user"]["id"]
    if realname:
        with get_sessionmaker()() as db:
            u = db.get(User, user_id)
            u.realname_status = "active"
            from app.security import utcnow

            u.realname_activated_at = utcnow()
            db.commit()
    return tokens, user_id


def admin_login(client) -> None:
    r = client.post("/admin/login", data={"password": ADMIN_PASSWORD}, follow_redirects=False)
    assert r.status_code == 303, r.text
    otp = pyotp.TOTP(ADMIN_TOTP_SECRET).now()
    r = client.post("/admin/2fa", data={"otp": otp}, follow_redirects=False)
    assert r.status_code == 303, r.text


@pytest.fixture
def db():
    with get_sessionmaker()() as session:
        yield session
