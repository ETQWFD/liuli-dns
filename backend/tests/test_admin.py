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
    assert "后台地址" in r.text
    assert "身份证审核邮箱" in r.text


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


def test_admin_users_page_and_offline_approval(client, db):
    tokens, uid = make_user(client, "offline@example.com")
    user_no = db.get(User, uid).user_no
    admin_login(client)
    page = client.get("/admin/users")
    assert page.status_code == 200
    assert user_no in page.text
    assert "offline@example.com" in page.text
    assert "复制编号" in page.text
    assert "标记邮件审核通过" in page.text

    r = client.post(f"/admin/users/{uid}/approve-offline",
                    data={"note": "邮件人工审核"},
                    headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/admin/users?msg=")
    assert "%" in r.headers["location"]
    with get_sessionmaker()() as s:
        user = s.get(User, uid)
        assert user.realname_status == "approved"
        sub = s.scalar(select(RealnameSubmission).where(
            RealnameSubmission.user_id == uid, RealnameSubmission.status == "approved"))
        assert sub is not None and sub.doc_number_hmac == ""

    r = client.post("/admin/codes", data={"user_no": user_no})
    assert r.status_code == 200
    code = CODE_RE.search(r.text).group(1)
    r = client.post("/api/v1/realname/activate", json={"code": code}, headers=bearer(tokens))
    assert r.status_code == 200
    with get_sessionmaker()() as s:
        assert s.get(User, uid).realname_status == "active"


def test_duplicate_unused_code_is_blocked(client, db):
    tokens, uid = make_user(client, "dupecode@example.com")
    with get_sessionmaker()() as s:
        s.get(User, uid).realname_status = "approved"
        s.commit()
    user_no = db.get(User, uid).user_no
    admin_login(client)
    r = client.post("/admin/codes", data={"user_no": user_no})
    assert r.status_code == 200
    first = CODE_RE.search(r.text).group(1)
    r = client.post("/admin/codes", data={"user_no": user_no}, follow_redirects=False)
    assert r.status_code == 303
    assert "已有未使用激活码" in __import__("urllib.parse").parse.unquote(r.headers["location"])
    with get_sessionmaker()() as s:
        row = s.scalar(select(ActivationCode).where(ActivationCode.user_id == uid))
        cid = row.id
    assert client.post(f"/admin/codes/{cid}/revoke", follow_redirects=False).status_code == 303
    r = client.post("/admin/codes", data={"user_no": user_no})
    assert r.status_code == 200
    second = CODE_RE.search(r.text).group(1)
    assert second != first


def test_agent_config_requires_activation(client):
    tokens, uid = make_user(client, "agentconfig@example.com")
    # Email verified but realname not active -> the control-plane endpoint must refuse.
    r = client.get("/api/v1/domains/agent/config", headers=bearer(tokens))
    assert r.status_code == 403
    with get_sessionmaker()() as s:
        s.get(User, uid).realname_status = "active"
        s.commit()
    r = client.get("/api/v1/domains/agent/config", headers=bearer(tokens))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["token"] == "fake-tunnel-token-for-agent-test"
    assert "cloudflare" not in str(data).lower()
