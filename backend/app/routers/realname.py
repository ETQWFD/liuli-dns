"""Realname submission, manual review status, one-time activation code."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..config import get_settings
from ..db import get_db
from ..deps import ip_hash_of, require_verified
from ..errors import AppError, E
from ..models import ActivationCode, RealnameSubmission, User
from ..ratelimit import enforce_user
from ..respond import ok_
from ..schemas import ActivateIn, RealnameStatusOut, RealnameSubmitIn, SimpleOk
from ..security import hmac_code, hmac_document, utcnow

router = APIRouter(prefix="/realname", tags=["realname"])


def _latest(db: Session, user_id: int) -> RealnameSubmission | None:
    return db.scalar(
        select(RealnameSubmission)
        .where(RealnameSubmission.user_id == user_id)
        .order_by(RealnameSubmission.id.desc())
    )


def _status(db: Session, user: User) -> RealnameStatusOut:
    s = get_settings()
    sub = _latest(db, user.id)
    instructions = [
        f"1. 在本页复制“我的用户编号”：{user.user_no}。",
        f"2. 用你的注册邮箱发送邮件到 {s.realname_inbox}，主题写“实名审核 + 你的编号”。",
        "3. 邮件必须附上身份证正面和反面照片，要求画面清晰、四角完整、文字可辨认；邮件正文也必须写上你的用户编号。",
        "4. 没有附用户编号的邮件无法对应账号，不能为你生成激活码。",
        "5. 管理员人工审核，通常 1～5 个工作日内答复；审核通过后会收到一次性激活码。",
        "6. 把激活码粘贴到本页上方的输入框并点击“激活”，系统会真实校验；激活成功后终身有效。",
        "7. 身份证照片仅用于本次人工审核，审核完成后会删除；平台数据库不保存证件原图，只保留审核状态、审核时间和必要的脱敏记录。平台审核不是官方权威核验。",
    ]
    return RealnameStatusOut(
        status=user.realname_status,
        user_no=user.user_no,
        activated_at=user.realname_activated_at,
        submitted_at=sub.submitted_at if sub else None,
        reviewed_at=sub.reviewed_at if sub else None,
        reject_reason=sub.reject_reason if sub and sub.status == "rejected" else None,
        inbox=s.realname_inbox,
        instructions=instructions,
    )


@router.post("/submissions")
def submit(payload: RealnameSubmitIn, request: Request,
           user: User = Depends(require_verified), db: Session = Depends(get_db)):
    enforce_user(user.id, "realname_submit", 3, 86400)
    if user.realname_status == "active":
        raise AppError(E["REALNAME_INVALID_STATE"], "实名已激活，无需重复提交", 409)
    if user.realname_status in ("pending", "approved"):
        return ok_(_status(db, user).model_dump(mode="json"))

    doc = payload.doc_number.strip()
    last4 = payload.doc_last4.strip().upper()[-4:]
    if doc:
        if payload.doc_type == "id_card" and not (15 <= len(doc) <= 18):
            raise AppError(E["VALIDATION"], "证件号码长度不合法", 422)
        if payload.doc_type != "id_card" and not (5 <= len(doc) <= 20):
            raise AppError(E["VALIDATION"], "证件号码长度不合法", 422)
        last4 = doc[-4:].upper()
    hmac_value = hmac_document(doc) if doc else ""

    db.add(
        RealnameSubmission(
            user_id=user.id, status="pending", doc_type=payload.doc_type,
            doc_number_hmac=hmac_value, doc_last4=last4,
        )
    )
    user.realname_status = "pending"
    write_audit(db, action="realname.submit", actor_id=user.id, target=user.user_no,
                ip_hash=ip_hash_of(request), detail={"doc_type": payload.doc_type})
    db.commit()
    return ok_(_status(db, user).model_dump(mode="json"))


@router.get("/status")
def status(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    return ok_(_status(db, user).model_dump(mode="json"))


def _bump_user_attempts(db: Session, user: User) -> None:
    code = db.scalar(
        select(ActivationCode)
        .where(ActivationCode.user_id == user.id, ActivationCode.status == "unused")
        .order_by(ActivationCode.id.desc())
    )
    if code is None:
        return
    code.attempts += 1
    if code.attempts >= code.max_attempts:
        code.locked_until = utcnow() + timedelta(hours=1)
    db.commit()


@router.post("/activate")
def activate(payload: ActivateIn, request: Request,
             user: User = Depends(require_verified), db: Session = Depends(get_db)):
    enforce_user(user.id, "realname_activate", 5, 3600)
    if user.realname_status == "active":
        raise AppError(E["REALNAME_INVALID_STATE"], "实名已激活", 409)
    if user.realname_status != "approved":
        raise AppError(E["REALNAME_INVALID_STATE"], "实名材料尚未审核通过", 409)

    code = db.scalar(select(ActivationCode).where(ActivationCode.code_hmac == hmac_code(payload.code)))
    if code is None:
        _bump_user_attempts(db, user)
        raise AppError(E["CODE_INVALID"], "激活码无效", 400)
    if code.locked_until and code.locked_until > utcnow():
        raise AppError(E["CODE_LOCKED"], "激活失败次数过多，已临时锁定", 429,
                       {"retry_after_seconds": int((code.locked_until - utcnow()).total_seconds())})
    if code.status == "used":
        raise AppError(E["CODE_USED"], "该激活码已被使用", 409)
    if code.status == "revoked":
        raise AppError(E["CODE_REVOKED"], "该激活码已被吊销", 409)
    if code.user_id != user.id:
        _bump_user_attempts(db, user)
        raise AppError(E["CODE_INVALID"], "激活码无效", 400)

    code.status = "used"
    code.used_at = utcnow()
    code.attempts = 0
    user.realname_status = "active"
    user.realname_activated_at = utcnow()
    write_audit(db, action="realname.activated", actor_id=user.id, target=user.user_no,
                ip_hash=ip_hash_of(request), detail={"code_id": code.id})
    db.commit()
    return ok_(SimpleOk(message="实名已激活，终身有效").model_dump())
