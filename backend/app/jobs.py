"""Background maintenance: expiry reminders, cleanup, cert status."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_sessionmaker
from .mailer import cert_expiry_email, send_email
from .models import (
    Certificate, Domain, EmailToken, IdempotencyKey, Notification, Session as LoginSession, User,
)
from .security import utcnow

log = logging.getLogger("liuli.jobs")
THRESHOLDS = (30, 14, 7, 3, 1)


def run_maintenance(db: Session) -> dict:
    now = utcnow()
    stats = {"certs_expired": 0, "notifications": 0, "sessions_purged": 0}

    for cert in db.scalars(
        select(Certificate).where(Certificate.status == "active", Certificate.not_after <= now)
    ):
        cert.status = "expired"
        stats["certs_expired"] += 1

    s = get_settings()
    soon = db.execute(
        select(Certificate).where(Certificate.status == "active",
                                   Certificate.not_after <= now + timedelta(days=31))
    ).scalars().all()
    for cert in soon:
        days = max(0, (cert.not_after - now).days)
        for threshold in THRESHOLDS:
            if days > threshold:
                continue
            kind = f"cert_expiry:{cert.id}:{threshold}"
            exists = db.scalar(select(Notification).where(Notification.kind == kind))
            if exists is not None:
                continue
            dom = db.get(Domain, cert.domain_id)
            owner = db.get(User, dom.user_id) if dom else None
            n = Notification(
                user_id=dom.user_id if dom else 0, kind=kind,
                payload_json={"cert_id": cert.id, "domain": dom.fqdn if dom else "",
                              "threshold": threshold, "not_after": cert.not_after.isoformat()},
                scheduled_at=now,
            )
            db.add(n)
            if owner and dom:
                subject, text = cert_expiry_email(dom.fqdn, days, cert.not_after.isoformat())
                if send_email(owner.email, subject, text):
                    n.sent_at = utcnow()
                    n.status = "sent"
                else:
                    n.status = "failed"
            stats["notifications"] += 1

    old_sessions = db.execute(
        delete(LoginSession).where(LoginSession.expires_at < now - timedelta(days=7))
    ).rowcount
    stats["sessions_purged"] = old_sessions or 0
    db.execute(delete(EmailToken).where(EmailToken.expires_at < now - timedelta(days=7)))
    db.execute(delete(IdempotencyKey).where(IdempotencyKey.expires_at < now))
    db.commit()
    log.info("maintenance done %s", stats)
    return stats


async def maintenance_loop() -> None:
    s = get_settings()
    while True:
        try:
            with get_sessionmaker()() as db:
                run_maintenance(db)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("maintenance loop error")
        await asyncio.sleep(max(60, s.maintenance_interval_seconds))
