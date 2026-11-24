"""Registration, login, refresh rotation, email verification, password reset."""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..captcha import captcha_store
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, ip_hash_of
from ..errors import AppError, E
from ..mailer import reset_email, send_email, verification_email
from ..models import EmailToken, Session as LoginSession, User
from ..ratelimit import client_ip, enforce
from ..respond import ok_
from ..schemas import (
    CaptchaOut, LoginIn, RefreshIn, RegisterIn, SimpleOk, TokenOut, UserOut,
)
from ..security import (
    generate_activation_code, hash_password, hash_token, new_access_token,
    new_refresh_token, normalize_code, utcnow, verify_password,
)
from ..services.verify import check_a  # noqa: F401  (kept for future email domain hints)

router = APIRouter(prefix="/auth", tags=["auth"])
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _new_user_no(db: Session) -> str:
    for _ in range(6):
        suffix = "".join(secrets.choice(CODE_LETTERS) for _ in range(6))
        no = f"U-{utcnow().year}-{suffix}"
        if db.scalar(select(User).where(User.user_no == no)) is None:
            return no
    raise AppError(E["INTERNAL"], "无法分配用户编号", 500)


def _email_code() -> str:
    raw = "".join(secrets.choice(CODE_LETTERS) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def _issue_email_token(db: Session, user: User, kind: str) -> str:
    code = _email_code()
    ttl = 3600 if kind == "reset" else get_settings().email_token_ttl_seconds
    db.add(
        EmailToken(
            user_id=user.id, kind=kind, token_hash=hash_token(normalize_code(code)),
            expires_at=utcnow() + timedelta(seconds=ttl),
        )
    )
    return code


def _consume_captcha(request: Request, captcha_id: str | None, answer: str | None) -> None:
    session_id = request.headers.get("x-session-id")
    enforce(f"captcha:ip:{client_ip(request)}", 30, 60, "验证请求过于频繁")
    if not captcha_id or not answer:
        challenge = captcha_store.issue(session_id)
        raise AppError(E["CAPTCHA_REQUIRED"], "请完成人机验证", 400, {"captcha": challenge})
    if not captcha_store.verify(captcha_id, answer, session_id):
        challenge = captcha_store.issue(session_id)
        raise AppError(E["CAPTCHA_INVALID"], "人机验证不正确或已失效", 400, {"captcha": challenge})


def _tokens(db: Session, user: User, request: Request) -> TokenOut:
    raw_refresh, refresh_hash = new_refresh_token()
    s = get_settings()
    db.add(
        LoginSession(
            user_id=user.id, refresh_hash=refresh_hash,
            ua_hash=hash_token(request.headers.get("user-agent", "")[:300]),
            ip_hash=ip_hash_of(request),
            expires_at=utcnow() + timedelta(seconds=s.refresh_ttl_seconds),
        )
    )
    db.flush()
    return TokenOut(
        access_token=new_access_token(user.id, user.role),
        refresh_token=raw_refresh,
        expires_in=s.access_ttl_seconds,
        user=UserOut.from_user(user),
    )


@router.post("/captcha")
def issue_captcha(request: Request):
    enforce(f"captcha_issue:ip:{client_ip(request)}", 30, 60, "验证请求过于频繁")
    data = captcha_store.issue(request.headers.get("x-session-id"))
    return ok_(CaptchaOut(**data))


@router.post("/register")
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    enforce(f"register:ip:{client_ip(request)}", 3, 3600, "注册过于频繁，请稍后再试")
    _consume_captcha(request, payload.captcha_id, payload.captcha_answer)
    email = payload.email.lower().strip()
    s = get_settings()

    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        if s.local_mode:
            # Local single-user mode may skip SMTP, but it MUST NOT silently
            # grant real-name status. The account still has to submit
            # documents and receive an administrator-issued activation code.
            existing.email_verified_at = existing.email_verified_at or utcnow()
            db.commit()
            return ok_({
                "message": "本机模式：邮箱已验证；实名仍需人工审核和激活码，请提交实名材料",
                "email_verified": True,
                "local_mode": True,
                "realname_status": existing.realname_status,
            })
        if existing.email_verified_at is None:
            code = _issue_email_token(db, existing, "verify")
            subject, text = verification_email(code)
            send_email(existing.email, subject, text)
            db.commit()
        # Same response regardless of account existence (no enumeration).
        return ok_(SimpleOk(message="如果该邮箱可用，验证邮件已发送").model_dump())

    user = User(
        user_no=_new_user_no(db),
        email=email,
        password_hash=hash_password(payload.password),
        locale=payload.locale if payload.locale in ("zh_CN", "en_US", "zh_TW") else "zh_CN",
    )
    if s.local_mode:
        # Only the email step is local-friendly. Real-name remains unverified
        # by default and requires a human-reviewed, one-time activation code.
        user.email_verified_at = utcnow()
    db.add(user)
    db.flush()
    code = _issue_email_token(db, user, "verify")
    subject, text = verification_email(code)
    send_email(user.email, subject, text)
    write_audit(
        db, action="user.register", actor_id=user.id, target=user.user_no,
        ip_hash=ip_hash_of(request), detail={"locale": user.locale},
    )
    db.commit()
    if s.local_mode:
        return ok_({
            "message": "本机模式：注册成功、邮箱已验证；请完成实名审核并输入激活码后再创建域名",
            "email_verified": True,
            "local_mode": True,
            "realname_status": user.realname_status,
        })
    return ok_(SimpleOk(message="注册成功，请查收邮箱验证码").model_dump())


@router.post("/verify-email")
def verify_email(payload: dict, request: Request, db: Session = Depends(get_db)):
    enforce(f"verify_email:ip:{client_ip(request)}", 10, 3600, "验证尝试过于频繁")
    code = normalize_code(str(payload.get("code", "")))
    if not code:
        raise AppError(E["VALIDATION"], "请输入验证码", 422)
    row = db.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == hash_token(code), EmailToken.kind == "verify"
        )
    )
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise AppError(E["AUTH_INVALID"], "验证码无效或已过期", 400)
    user = db.get(User, row.user_id)
    if user is None:
        raise AppError(E["AUTH_INVALID"], "验证码无效", 400)
    row.used_at = utcnow()
    user.email_verified_at = user.email_verified_at or utcnow()
    write_audit(db, action="user.email_verified", actor_id=user.id, target=user.user_no,
                ip_hash=ip_hash_of(request))
    db.commit()
    return ok_({"verified": True, "email": user.email})


@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    enforce(f"login:ip:{ip}", 20, 60, "登录尝试过于频繁，请稍后再试")
    _consume_captcha(request, payload.captcha_id, payload.captcha_answer)

    email = payload.email.lower().strip()
    enforce(f"login:account:{email}", 5, 60, "该账号尝试过于频繁，请稍后再试")
    user = db.scalar(select(User).where(User.email == email))

    if user is not None and user.locked_until and user.locked_until > utcnow():
        retry = int((user.locked_until - utcnow()).total_seconds())
        raise AppError(E["AUTH_LOCKED"], "账号暂时锁定，请稍后再试", 429,
                       {"retry_after_seconds": retry}, {"Retry-After": str(max(1, retry))})

    # Constant-ish response for unknown accounts.
    valid = bool(user) and verify_password(payload.password, user.password_hash if user else "")
    if not valid:
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= 10:
                user.locked_until = utcnow() + timedelta(minutes=15)
                user.failed_login_count = 0
                write_audit(db, action="auth.lockout", actor_id=user.id,
                            target=user.user_no, ip_hash=ip_hash_of(request))
            db.commit()
        raise AppError(E["AUTH_INVALID"], "邮箱或密码不正确", 401)

    if not user.is_active:
        raise AppError(E["AUTH_INVALID"], "账号不可用", 401)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    tokens = _tokens(db, user, request)
    write_audit(db, action="auth.login", actor_id=user.id, target=user.user_no,
                ip_hash=ip_hash_of(request))
    db.commit()
    return ok_(tokens.model_dump(mode="json"))


@router.post("/refresh")
def refresh(payload: RefreshIn, request: Request, db: Session = Depends(get_db)):
    enforce(f"refresh:ip:{client_ip(request)}", 60, 3600, "刷新过于频繁")
    h = hash_token(payload.refresh_token)
    row = db.scalar(select(LoginSession).where(LoginSession.refresh_hash == h))
    if row is None:
        raise AppError(E["AUTH_REQUIRED"], "登录状态无效，请重新登录", 401)
    if row.revoked_at is not None:
        # Token reuse: revoke all sessions of that user (likely stolen token).
        for s in db.scalars(select(LoginSession).where(LoginSession.user_id == row.user_id)):
            s.revoked_at = s.revoked_at or utcnow()
        db.commit()
        raise AppError(E["AUTH_REQUIRED"], "登录状态已失效，请重新登录", 401)
    if row.expires_at <= utcnow():
        raise AppError(E["AUTH_REQUIRED"], "登录已过期，请重新登录", 401)
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AppError(E["AUTH_REQUIRED"], "账号不可用", 401)
    row.revoked_at = utcnow()
    tokens = _tokens(db, user, request)
    db.commit()
    return ok_(tokens.model_dump(mode="json"))


@router.post("/logout")
def logout(payload: RefreshIn, db: Session = Depends(get_db)):
    row = db.scalar(
        select(LoginSession).where(LoginSession.refresh_hash == hash_token(payload.refresh_token))
    )
    if row is not None:
        row.revoked_at = utcnow()
        db.commit()
    return ok_(SimpleOk().model_dump())


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return ok_(UserOut.from_user(user).model_dump(mode="json"))


@router.post("/password/forgot")
def forgot(payload: dict, request: Request, db: Session = Depends(get_db)):
    enforce(f"forgot:ip:{client_ip(request)}", 5, 3600, "请求过于频繁")
    email = str(payload.get("email", "")).lower().strip()
    if email:
        enforce(f"forgot:email:{email}", 3, 3600, "请求过于频繁")
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            code = _issue_email_token(db, user, "reset")
            subject, text = reset_email(code)
            send_email(user.email, subject, text)
            db.commit()
    return ok_(SimpleOk(message="如果该邮箱已注册，重置邮件已发送").model_dump())


@router.post("/password/reset")
def reset_password(payload: dict, db: Session = Depends(get_db)):
    code = normalize_code(str(payload.get("code", "")))
    new_password = str(payload.get("password", ""))
    if len(new_password) < 10 or not any(c.isalpha() for c in new_password) or not any(
        c.isdigit() for c in new_password
    ):
        raise AppError(E["VALIDATION"], "新密码需至少 10 位并同时包含字母与数字", 422)
    row = db.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == hash_token(code), EmailToken.kind == "reset"
        )
    )
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise AppError(E["AUTH_INVALID"], "重置码无效或已过期", 400)
    user = db.get(User, row.user_id)
    if user is None:
        raise AppError(E["AUTH_INVALID"], "重置码无效", 400)
    row.used_at = utcnow()
    user.password_hash = hash_password(new_password)
    for s in db.scalars(select(LoginSession).where(LoginSession.user_id == user.id)):
        s.revoked_at = s.revoked_at or utcnow()
    db.commit()
    return ok_(SimpleOk(message="密码已重置，请重新登录").model_dump())


@router.get("/health")
def health(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return ok_({"auth": "ok"})
