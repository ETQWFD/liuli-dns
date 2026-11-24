from __future__ import annotations

import re

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import User
from tests.conftest import get_captcha, last_email_code, login, register, SESSION_ID


def test_captcha_is_single_use(client):
    cap = get_captcha(client)
    email = "captcha@example.com"
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "UserPassw0rd!", "captcha_id": cap["captcha_id"],
              "captcha_answer": cap["answer"], "session_id": SESSION_ID},
        headers={"X-Session-Id": SESSION_ID},
    )
    assert r.status_code == 200
    r2 = client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "UserPassw0rd!",
              "captcha_id": cap["captcha_id"], "captcha_answer": cap["answer"],
              "session_id": SESSION_ID},
        headers={"X-Session-Id": SESSION_ID},
    )
    assert r2.status_code == 400
    assert r2.json()["error"]["code"] == "CAPTCHA_INVALID"


def test_register_verify_login_me(client):
    email = "alice@example.com"
    register(client, email)
    tokens = login(client, email)
    assert tokens["user"]["email_verified"] is True
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["data"]["email"] == email
    assert me.json()["data"]["realname_status"] == "unverified"


def test_duplicate_email_is_not_enumerated(client, db):
    email = "dupe@example.com"
    register(client, email)
    cap = get_captcha(client)
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email.upper(), "password": "UserPassw0rd!", "captcha_id": cap["captcha_id"],
              "captcha_answer": cap["answer"]},
        headers={"X-Session-Id": SESSION_ID},
    )
    assert r.status_code == 200
    assert "如果该邮箱可用" in r.json()["data"]["message"]
    users = db.scalars(select(User).where(User.email == email)).all()
    assert len(users) == 1


def test_wrong_password_then_success(client):
    email = "wrong@example.com"
    register(client, email)
    cap = get_captcha(client)
    bad = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassw0rd", "captcha_id": cap["captcha_id"],
              "captcha_answer": cap["answer"]},
        headers={"X-Session-Id": SESSION_ID},
    )
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "AUTH_INVALID"
    tokens = login(client, email)
    assert tokens["access_token"]


def test_refresh_rotation_and_reuse_detection(client):
    email = "refresh@example.com"
    register(client, email)
    tokens = login(client, email)
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    new_tokens = r1.json()["data"]
    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    # Replaying the old refresh token revokes the whole session family.
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})
    assert r3.status_code == 401


def test_logout_revokes_refresh(client):
    email = "logout@example.com"
    register(client, email)
    tokens = login(client, email)
    r = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401


def test_password_reset_flow(client):
    email = "reset@example.com"
    register(client, email)
    r = client.post("/api/v1/auth/password/forgot", json={"email": email})
    assert r.status_code == 200
    mail = [m for m in __import__("app.mailer", fromlist=["outbox"]).outbox if m["to"] == email][-1]
    code = re.search(r"([A-Z0-9]{5}-[A-Z0-9]{5})", mail["text"]).group(1)
    r = client.post("/api/v1/auth/password/reset", json={"code": code, "password": "NewPassw0rd!"})
    assert r.status_code == 200
    # Old password no longer works.
    cap = get_captcha(client)
    bad = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "UserPassw0rd!", "captcha_id": cap["captcha_id"],
              "captcha_answer": cap["answer"]},
        headers={"X-Session-Id": SESSION_ID},
    )
    assert bad.status_code == 401
    tokens = login(client, email, "NewPassw0rd!")
    assert tokens["user"]["email"] == email


def test_me_requires_bearer(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_REQUIRED"


def test_email_code_single_use(client):
    email = "single@example.com"
    cap = get_captcha(client)
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "UserPassw0rd!", "captcha_id": cap["captcha_id"],
              "captcha_answer": cap["answer"]},
        headers={"X-Session-Id": SESSION_ID},
    )
    code = last_email_code(email)
    r1 = client.post("/api/v1/auth/verify-email", json={"code": code})
    assert r1.status_code == 200
    r2 = client.post("/api/v1/auth/verify-email", json={"code": code})
    assert r2.status_code == 400


def test_health_and_meta(client):
    assert client.get("/healthz").status_code == 200
    r = client.get("/api/v1/meta/public")
    data = r.json()["data"]
    assert data["capabilities"]["registrar"] is False
    assert "private" not in str(data).lower()
    # 后台入口不能通过公开元数据下发给普通客户端。
    assert "admin_url" not in data
    assert "admin.asnia.cc" not in str(data)
    assert data["version"] == "0.2.2"
