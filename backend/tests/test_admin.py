from __future__ import annotations

import pyotp
from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import ActivationCode, AuditLog, RealnameSubmission, User
from tests.conftest import ADMIN_PASSWORD, ADMIN_TOTP_SECRET, admin_login, bearer, make_user

CODE_RE = __import__("re").compile(r'id="code">([A-Z0-9-]+)<')


def test_admin_requires_login(client):
    r = client.get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "管理员登录" in r.text


def test_admin_wrong_password(client):
    r = client.post("/admin/login", data={"password": "WrongPassw0rd!"})
    assert r.status_code == 401
    assert "密码不正确" in r.text


def test_admin_wrong_totp(client):
    r = client.post("/admin/login", data={"password": ADMIN_PASSWORD}, follow_redirects=False)
    assert r.status_code == 303
    r = client.post("/admin/2fa", data={"otp": "000000"})
    assert r.status_code == 401


def test_full_admin_workflow(client, db):
    tokens, uid = make_user(client, "adminflow@example.com")
    r = client.post("/api/v1/realname/submissions",
                    json={"doc_type": "passport", "doc_number": "P12345678"},
                    headers=bearer(tokens))
    assert r.status_code == 200
    sub = db.scalar(select(RealnameSubmission).where(RealnameSubmission.user_id == uid))
    user_no = db.get(User, uid).user_no

    admin_login(client)
    dash = client.get("/admin/dashboard")
    assert dash.status_code == 200
    assert user_no in dash.text

    r = client.post(f"/admin/realname/{sub.id}/review",
                    data={"decision": "approve", "reason": ""}, follow_redirects=False)
    assert r.status_code == 303
    with get_sessionmaker()() as s:
        assert s.get(User, uid).realname_status == "approved"

    r = client.post("/admin/codes", data={"user_no": user_no})
    assert r.status_code == 200
    m = CODE_RE.search(r.text)
    assert m
    code = m.group(1)

    r = client.post("/api/v1/realname/activate", json={"code": code}, headers=bearer(tokens))
    assert r.status_code == 200
    with get_sessionmaker()() as s:
        assert s.get(User, uid).realname_status == "active"
        assert s.scalar(select(ActivationCode).where(ActivationCode.user_id == uid)).status == "used"

    audit = client.get("/admin/audit")
    assert audit.status_code == 200
    assert "admin.realname.approve" in audit.text
    assert "admin.code.issue" in audit.text
    with get_sessionmaker()() as s:
        actions = {a.action for a in s.scalars(select(AuditLog)).all()}
    assert "admin.realname.approve" in actions
    assert "admin.code.issue" in actions


def test_admin_cannot_generate_for_unapproved(client, db):
    tokens, uid = make_user(client, "adminflow2@example.com")
    user_no = db.get(User, uid).user_no
    admin_login(client)
    r = client.post("/admin/codes", data={"user_no": user_no}, follow_redirects=False)
    assert r.status_code == 303
    assert "error=" in r.headers["location"]


def test_code_revoke_and_reset(client, db):
    tokens, uid = make_user(client, "adminflow3@example.com")
    with get_sessionmaker()() as s:
        s.get(User, uid).realname_status = "approved"
        s.commit()
    user_no = db.get(User, uid).user_no
    admin_login(client)
    r = client.post("/admin/codes", data={"user_no": user_no})
    code = CODE_RE.search(r.text).group(1)
    with get_sessionmaker()() as s:
        row = s.scalar(select(ActivationCode).where(ActivationCode.user_id == uid))
        cid = row.id
    r = client.post(f"/admin/codes/{cid}/revoke", follow_redirects=False)
    assert r.status_code == 303
    with get_sessionmaker()() as s:
        assert s.get(ActivationCode, cid).status == "revoked"
    r = client.post(f"/admin/codes/{cid}/reset-attempts", follow_redirects=False)
    assert r.status_code == 303
