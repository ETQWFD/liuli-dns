from __future__ import annotations

import re

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import get_sessionmaker
from app.models import ActivationCode, RealnameSubmission, User
from app.security import hmac_code, utcnow
from tests.conftest import admin_login, bearer, get_captcha, login, make_user, register

CODE_RE = re.compile(r'id="code">([A-Z0-9-]+)<')


def _approved(user_id: int) -> None:
    with get_sessionmaker()() as db:
        u = db.get(User, user_id)
        u.realname_status = "approved"
        db.commit()


def _extract_admin_code(client, user_no: str) -> str:
    r = client.post("/admin/codes", data={"user_no": user_no})
    assert r.status_code == 200, r.text
    m = CODE_RE.search(r.text)
    assert m, r.text
    return m.group(1)


def test_submit_stores_only_hmac(client, db):
    tokens, uid = make_user(client, "rn1@example.com")
    doc = "110101199001011234"
    r = client.post("/api/v1/realname/submissions",
                    json={"doc_type": "id_card", "doc_number": doc}, headers=bearer(tokens))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "pending"
    assert doc not in r.text
    sub = db.scalar(select(RealnameSubmission).where(RealnameSubmission.user_id == uid))
    assert sub.doc_number_hmac != doc
    assert len(sub.doc_number_hmac) == 64
    assert sub.doc_last4 == "1234"
    # No full document number is persisted anywhere.
    assert "doc_number" not in RealnameSubmission.__table__.columns
    assert doc not in str(sub.__dict__)


def test_full_activation_flow(client, db):
    tokens, uid = make_user(client, "rn2@example.com")
    client.post("/api/v1/realname/submissions",
                json={"doc_type": "id_card", "doc_number": "110101199001011234"},
                headers=bearer(tokens))
    _approved(uid)
    with get_sessionmaker()() as s:
        user_no = s.get(User, uid).user_no
    admin_login(client)
    code = _extract_admin_code(client, user_no)

    r = client.post("/api/v1/realname/activate", json={"code": code}, headers=bearer(tokens))
    assert r.status_code == 200, r.text
    assert "终身有效" in r.json()["data"]["message"]

    with get_sessionmaker()() as s:
        user = s.get(User, uid)
        assert user.realname_status == "active"
        assert user.realname_activated_at is not None
        row = s.scalar(select(ActivationCode).where(ActivationCode.user_id == uid))
        assert row.status == "used"
        assert row.used_at is not None
        assert code.replace("-", "") not in row.code_hmac
        assert len(row.code_hmac) == 64

    # Re-activation is rejected because the account is already active.
    r2 = client.post("/api/v1/realname/activate", json={"code": code}, headers=bearer(tokens))
    assert r2.status_code == 409

    # A fresh login still reports active (lifetime validity).
    toks2 = login(client, "rn2@example.com")
    me = client.get("/api/v1/auth/me", headers=bearer(toks2))
    assert me.json()["data"]["realname_status"] == "active"


def test_code_is_bound_to_user(client, db):
    tokens_a, uid_a = make_user(client, "rna@example.com", realname=False)
    _approved(uid_a)
    with get_sessionmaker()() as s:
        user_no_a = s.get(User, uid_a).user_no
    admin_login(client)
    code = _extract_admin_code(client, user_no_a)

    tokens_b, uid_b = make_user(client, "rnb@example.com")
    _approved(uid_b)
    r = client.post("/api/v1/realname/activate", json={"code": code}, headers=bearer(tokens_b))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "CODE_INVALID"


def test_used_code_rejected(client, db):
    tokens, uid = make_user(client, "rnc@example.com")
    _approved(uid)
    with get_sessionmaker()() as s:
        user_no = s.get(User, uid).user_no
    admin_login(client)
    code = _extract_admin_code(client, user_no)
    assert client.post("/api/v1/realname/activate", json={"code": code},
                       headers=bearer(tokens)).status_code == 200
    # Force status back to approved to exercise the "used" branch.
    with get_sessionmaker()() as s:
        s.get(User, uid).realname_status = "approved"
        s.commit()
    r = client.post("/api/v1/realname/activate", json={"code": code}, headers=bearer(tokens))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CODE_USED"


def test_failed_attempts_lock_code(client, db):
    tokens, uid = make_user(client, "rnd@example.com")
    _approved(uid)
    with get_sessionmaker()() as s:
        user_no = s.get(User, uid).user_no
    admin_login(client)
    real = _extract_admin_code(client, user_no)

    for _ in range(5):
        client.post("/api/v1/realname/activate", json={"code": "AAAAA-AAAAA-AAAAA-AAAAA"},
                    headers=bearer(tokens))
    with get_sessionmaker()() as s:
        row = s.scalar(select(ActivationCode).where(ActivationCode.user_id == uid))
        assert row.locked_until is not None

    from app.ratelimit import limiter

    limiter.reset(f"realname_activate:user:{uid}")
    r = client.post("/api/v1/realname/activate", json={"code": real}, headers=bearer(tokens))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "CODE_LOCKED"


def test_activation_requires_approval(client, db):
    tokens, uid = make_user(client, "rne@example.com")
    with get_sessionmaker()() as s:
        code = "ABCDE-FGHJK-LMNPQ-RSTUV"
        s.add(ActivationCode(user_id=uid, user_no=s.get(User, uid).user_no,
                             code_hmac=hmac_code(code), status="unused"))
        s.commit()
    r = client.post("/api/v1/realname/activate", json={"code": code}, headers=bearer(tokens))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "REALNAME_INVALID_STATE"


def test_activation_hmac_is_globally_unique(client, db):
    tokens, uid = make_user(client, "rnf@example.com")
    code = "ABCDE-FGHJK-LMNPQ-RSTUV"
    with get_sessionmaker()() as s:
        s.add(ActivationCode(user_id=uid, user_no=s.get(User, uid).user_no,
                             code_hmac=hmac_code(code), status="unused"))
        s.commit()
    with get_sessionmaker()() as s:
        s.add(ActivationCode(user_id=uid, user_no="U-OTHER", code_hmac=hmac_code(code),
                             status="unused"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_status_contains_guidance_and_no_pii(client):
    tokens, _ = make_user(client, "rng@example.com")
    r = client.get("/api/v1/realname/status", headers=bearer(tokens))
    data = r.json()["data"]
    assert data["status"] == "unverified"
    assert "平台人工审核" in " ".join(data["instructions"])
    assert "110101" not in r.text
