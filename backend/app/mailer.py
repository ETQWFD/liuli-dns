"""Mail delivery with a dev-mode outbox (no SMTP credentials in code)."""

from __future__ import annotations

import html
import json
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from .config import get_settings
from .security import mask_email, utcnow

log = logging.getLogger("liuli.mail")

# Dev/test outbox (in-memory, bounded). Tests read tokens from here.
outbox: list[dict] = []
_MAX_OUTBOX = 200


def send_email(to: str, subject: str, text: str, html_body: str | None = None) -> bool:
    s = get_settings()
    message = EmailMessage()
    message["From"] = s.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    if not s.smtp_host:
        outbox.append({"to": to, "subject": subject, "text": text, "at": utcnow().isoformat()})
        if len(outbox) > _MAX_OUTBOX:
            outbox.pop(0)
        try:
            d = Path(s.mail_outbox_dir)
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"{utcnow():%Y%m%dT%H%M%S%f}.json"
            path.write_text(json.dumps(outbox[-1], ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            log.warning("dev outbox write failed")
        log.info("dev mail to=%s subject=%s", mask_email(to), subject)
        return True

    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(message)
        log.info("mail sent to=%s subject=%s", mask_email(to), subject)
        return True
    except Exception:
        log.exception("mail delivery failed to=%s", mask_email(to))
        return False


def verification_email(token: str) -> tuple[str, str]:
    text = (
        "你好，\n\n请在 24 小时内打开客户端，输入以下邮箱验证码：\n\n"
        f"    {token}\n\n"
        "验证码一次性使用，请勿转发。如果这不是你的操作，请忽略本邮件。\n"
        "本邮件由系统自动发送。\n"
    )
    return "验证你的 LiuliDNS 邮箱", text


def reset_email(token: str) -> tuple[str, str]:
    return (
        "重置你的 LiuliDNS 密码",
        "请在 1 小时内打开客户端，输入以下重置码：\n\n"
        f"    {token}\n\n"
        "重置码一次性使用。若非本人操作，请忽略本邮件。\n",
    )


def realname_approved_email(user_no: str) -> tuple[str, str]:
    return (
        "实名审核已通过",
        f"你的用户编号 {user_no} 已通过平台人工审核。请登录客户端，"
        "由管理员获取一次性激活码后在「实名认证」页激活。\n"
        "平台审核不代表官方权威核验。\n",
    )


def cert_expiry_email(domain: str, days: int, not_after: str) -> tuple[str, str]:
    return (
        f"证书即将到期：{domain}",
        f"域名 {domain} 的证书将在 {days} 天后到期（{not_after} UTC）。"
        "请在客户端「证书」页上传新证书并启用。\n",
    )


def escape(value: str) -> str:
    return html.escape(value, quote=True)
