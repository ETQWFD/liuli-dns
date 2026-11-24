"""FastAPI dependencies: bearer auth, realname gate, idempotency."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

import jwt

from .db import get_db
from .errors import AppError, E
from .models import IdempotencyKey, User
from .security import decode_access_token, utcnow
from .ratelimit import client_ip

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AppError(E["AUTH_REQUIRED"], "请先登录", 401, headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise AppError(E["AUTH_REQUIRED"], "登录状态已过期，请重新登录", 401)
    except jwt.InvalidTokenError:
        raise AppError(E["AUTH_REQUIRED"], "登录凭证无效", 401)
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AppError(E["AUTH_REQUIRED"], "账号不可用", 401)
    return user


def require_verified(user: User = Depends(get_current_user)) -> User:
    if user.email_verified_at is None:
        raise AppError(E["AUTH_EMAIL_UNVERIFIED"], "请先完成邮箱验证", 403)
    return user


def require_realname(user: User = Depends(require_verified)) -> User:
    status = "unverified" if user.realname_status == "none" else user.realname_status
    if status != "active":
        raise AppError(
            E["REALNAME_REQUIRED"],
            "请先完成实名认证并输入激活码，未激活前不能创建或管理域名",
            403,
            {"realname_status": status},
        )
    return user


def ip_hash_of(request: Request) -> str:
    from .security import hash_ip

    return hash_ip(client_ip(request))


def idem_key(request: Request, required: bool = False) -> str | None:
    key = request.headers.get("x-idempotency-key", "").strip()
    if not key:
        if required:
            raise AppError(E["VALIDATION"], "缺少 X-Idempotency-Key", 422)
        return None
    if len(key) > 64:
        raise AppError(E["VALIDATION"], "幂等键过长", 422)
    return key


def fingerprint(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def cached_idempotent(
    db: Session, user_id: int, endpoint: str, key: str | None, payload: Any
) -> tuple[dict, int] | None:
    if not key:
        return None
    row = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.key == key,
        )
    )
    if row is None:
        return None
    if row.request_hash != fingerprint(payload):
        raise AppError(E["IDEMPOTENCY_CONFLICT"], "同一幂等键对应了不同的请求内容", 409)
    return (row.response_json or {}, row.status_code or 200)


def store_idempotent(
    db: Session,
    user_id: int,
    endpoint: str,
    key: str | None,
    payload: Any,
    response: dict,
    status_code: int = 200,
) -> None:
    if not key:
        return
    db.add(
        IdempotencyKey(
            user_id=user_id,
            endpoint=endpoint,
            key=key,
            request_hash=fingerprint(payload),
            response_json=response,
            status_code=status_code,
            expires_at=utcnow() + __import__("datetime").timedelta(days=7),
        )
    )
    db.flush()
