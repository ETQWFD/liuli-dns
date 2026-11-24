"""Server-rendered admin console: password + TOTP + audit trail.

The admin identity lives only in environment variables; it is never a normal
user account and cannot be created through the public API.
"""

from __future__ import annotations

import html
from datetime import timedelta
from pathlib import Path

import pyotp
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..config import get_settings
from ..db import get_db
from ..errors import AppError, E
from ..mailer import realname_approved_email, send_email
from ..models import (
    ActivationCode, AuditLog, Certificate, Domain, RealnameSubmission, User,
)
from ..ratelimit import client_ip, enforce
from ..security import (
    generate_activation_code, hash_ip, hmac_code, mask_email, utcnow, verify_password,
)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
COOKIE = "liuli_admin"
PENDING = "liuli_admin_pw"
SALT = "liuli-admin-session"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt=SALT)


def _admin(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=get_settings().admin_session_ttl_seconds)
    except BadSignature:
        return None
    return data if data.get("role") == "admin" else None


def _guard(request: Request) -> None:
    s = get_settings()
    if not s.admin_password_hash or not s.admin_totp_secret:
        raise HTTPException(503, "后台未配置管理员密码或 TOTP 密钥")
    if _admin(request) is None:
        raise HTTPException(303, headers={"Location": "/admin/login"})


def _set_cookie(response, name: str, value: str, max_age: int) -> None:
    s = get_settings()
    response.set_cookie(
        name, value, max_age=max_age, httponly=True, samesite="strict", secure=s.is_prod, path="/admin"
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def admin_root(request: Request):
    _guard(request)
    return RedirectResponse("/admin/dashboard", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    s = get_settings()
    configured = bool(s.admin_password_hash and s.admin_totp_secret)
    return templates.TemplateResponse(
        request=request, name="login.html",
        context={"configured": configured, "error": None, "admin_email": s.admin_email},
    )


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form(...)):
    s = get_settings()
    enforce(f"admin_login:{client_ip(request)}", 5, 60, "后台登录尝试过于频繁")
    if not s.admin_password_hash or not s.admin_totp_secret:
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"configured": False, "error": "后台未配置", "admin_email": s.admin_email},
            status_code=503,
        )
    if not verify_password(password, s.admin_password_hash):
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"configured": True, "error": "密码不正确", "admin_email": s.admin_email},
            status_code=401,
        )
    response = RedirectResponse("/admin/2fa", status_code=303)
    token = _serializer().dumps({"role": "pending", "email": s.admin_email})
    _set_cookie(response, PENDING, token, 300)
    return response


@router.get("/2fa", response_class=HTMLResponse)
def twofa_page(request: Request):
    if not request.cookies.get(PENDING):
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(request=request, name="twofa.html", context={"error": None})


@router.post("/2fa", response_class=HTMLResponse)
def twofa(request: Request, otp: str = Form(...)):
    s = get_settings()
    enforce(f"admin_2fa:{client_ip(request)}", 5, 60, "验证尝试过于频繁")
    pending = request.cookies.get(PENDING)
    if not pending:
        return RedirectResponse("/admin/login", status_code=303)
    try:
        data = _serializer().loads(pending, max_age=300)
    except BadSignature:
        return RedirectResponse("/admin/login", status_code=303)
    if data.get("role") != "pending":
        return RedirectResponse("/admin/login", status_code=303)
    if not pyotp.TOTP(s.admin_totp_secret).verify(otp.strip().replace(" ", ""), valid_window=1):
        return templates.TemplateResponse(
            request=request, name="twofa.html", context={"error": "动态口令不正确"}, status_code=401
        )
    response = RedirectResponse("/admin/dashboard", status_code=303)
    token = _serializer().dumps({"role": "admin", "email": s.admin_email})
    _set_cookie(response, COOKIE, token, s.admin_session_ttl_seconds)
    response.delete_cookie(PENDING, path="/admin")
    write_audit_standalone(action="admin.login", target=mask_email(s.admin_email),
                           ip=client_ip(request))
    return response


def write_audit_standalone(action: str, target: str, ip: str, detail: dict | None = None) -> None:
    from ..db import get_sessionmaker

    with get_sessionmaker()() as db:
        write_audit(db, action=action, actor_type="admin", target=target,
                    ip_hash=hash_ip(ip), detail=detail or {})
        db.commit()


@router.get("/logout")
def logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(COOKIE, path="/admin")
    response.delete_cookie(PENDING, path="/admin")
    return response


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    pending = db.execute(
        select(RealnameSubmission, User)
        .join(User, User.id == RealnameSubmission.user_id)
        .where(RealnameSubmission.status == "pending")
        .order_by(RealnameSubmission.id)
    ).all()
    recent_users = db.scalars(select(User).order_by(User.id.desc()).limit(15)).all()
    counts = {
        "users": db.scalar(select(func.count(User.id))) or 0,
        "domains": db.scalar(select(func.count(Domain.id))) or 0,
        "certs": db.scalar(select(func.count(Certificate.id))
                           .where(Certificate.status == "active")) or 0,
        "pending": len(pending),
    }
    codes = db.scalars(select(ActivationCode).order_by(ActivationCode.id.desc()).limit(15)).all()
    audit_rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(12)).all()
    doings = []
    for cert in db.scalars(
        select(Certificate).where(Certificate.status == "active")
        .order_by(Certificate.not_after).limit(8)
    ):
        dom = db.get(Domain, cert.domain_id)
        doings.append({"domain": dom.fqdn if dom else "-", "not_after": cert.not_after,
                       "days": (cert.not_after - utcnow()).days})
    return templates.TemplateResponse(
        request=request, name="dashboard.html",
        context={
            "counts": counts, "pending": pending, "users": recent_users, "codes": codes,
            "audit": audit_rows, "expiring": doings,
            "msg": request.query_params.get("msg"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/realname/{sub_id}/review")
def review(sub_id: int, request: Request, decision: str = Form(...),
           reason: str = Form(""), db: Session = Depends(get_db)):
    _guard(request)
    sub = db.get(RealnameSubmission, sub_id)
    if sub is None or sub.status != "pending":
        return RedirectResponse("/admin/dashboard?error=审核记录不存在或已处理", status_code=303)
    user = db.get(User, sub.user_id)
    if user is None:
        return RedirectResponse("/admin/dashboard?error=用户不存在", status_code=303)
    if decision == "approve":
        sub.status = "approved"
        sub.reviewed_at = utcnow()
        sub.reviewer = "admin"
        user.realname_status = "approved"
        subject, text = realname_approved_email(user.user_no)
        send_email(user.email, subject, text)
        msg = f"已通过 {user.user_no}，请生成激活码"
    else:
        sub.status = "rejected"
        sub.reviewed_at = utcnow()
        sub.reviewer = "admin"
        sub.reject_reason = reason.strip()[:255] or "材料不清晰"
        user.realname_status = "rejected"
        msg = f"已驳回 {user.user_no}"
    write_audit(db, action=f"admin.realname.{decision}", actor_type="admin",
                target=user.user_no, ip_hash=hash_ip(client_ip(request)),
                detail={"submission_id": sub.id, "reason": reason[:100]})
    db.commit()
    return RedirectResponse(f"/admin/dashboard?msg={msg}", status_code=303)


@router.post("/codes", response_class=HTMLResponse)
def create_code(request: Request, user_no: str = Form(...), db: Session = Depends(get_db)):
    _guard(request)
    user = db.scalar(select(User).where(User.user_no == user_no.strip().upper()))
    if user is None:
        return RedirectResponse("/admin/dashboard?error=用户编号不存在", status_code=303)
    if user.realname_status == "active":
        return RedirectResponse("/admin/dashboard?error=该用户已激活实名", status_code=303)
    if user.realname_status != "approved":
        return RedirectResponse("/admin/dashboard?error=该用户尚未通过审核", status_code=303)

    raw = None
    for _ in range(6):
        candidate = generate_activation_code()
        h = hmac_code(candidate)
        if db.scalar(select(ActivationCode).where(ActivationCode.code_hmac == h)) is None:
            raw = candidate
            code_row = ActivationCode(
                user_id=user.id, user_no=user.user_no, code_hmac=h,
                status="unused", issued_by="admin",
            )
            db.add(code_row)
            db.flush()
            break
    if raw is None:  # pragma: no cover - astronomically unlikely
        raise AppError(E["INTERNAL"], "激活码生成失败，请重试", 500)

    write_audit(db, action="admin.code.issue", actor_type="admin", target=user.user_no,
                ip_hash=hash_ip(client_ip(request)),
                detail={"code_id": code_row.id, "code_hmac_prefix": code_row.code_hmac[:8]})
    db.commit()
    return templates.TemplateResponse(
        request=request, name="code.html",
        context={"user": user, "code": raw, "code_id": code_row.id},
    )


@router.post("/codes/{code_id}/revoke")
def revoke(code_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    row = db.get(ActivationCode, code_id)
    if row is None:
        return RedirectResponse("/admin/dashboard?error=激活码不存在", status_code=303)
    row.status = "revoked"
    row.revoked_at = utcnow()
    write_audit(db, action="admin.code.revoke", actor_type="admin", target=row.user_no,
                ip_hash=hash_ip(client_ip(request)), detail={"code_id": code_id})
    db.commit()
    return RedirectResponse("/admin/dashboard?msg=激活码已吊销", status_code=303)


@router.post("/codes/{code_id}/reset-attempts")
def reset_attempts(code_id: int, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    row = db.get(ActivationCode, code_id)
    if row is None:
        return RedirectResponse("/admin/dashboard?error=激活码不存在", status_code=303)
    row.attempts = 0
    row.locked_until = None
    write_audit(db, action="admin.code.reset_attempts", actor_type="admin", target=row.user_no,
                ip_hash=hash_ip(client_ip(request)), detail={"code_id": code_id})
    db.commit()
    return RedirectResponse("/admin/dashboard?msg=已重置失败次数", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)).all()
    return templates.TemplateResponse(
        request=request, name="audit.html",
        context={"rows": rows, "now": utcnow()},
    )
