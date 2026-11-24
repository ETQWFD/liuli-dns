"""Audit trail helpers. Never store tokens, passwords or document numbers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog
from .security import redact_value


def write_audit(
    db: Session,
    *,
    action: str,
    actor_id: int | None = None,
    actor_type: str = "user",
    target: str | None = None,
    ip_hash: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            target=target,
            ip_hash=ip_hash,
            detail_json=redact_value(detail or {}),
        )
    )
    db.flush()
