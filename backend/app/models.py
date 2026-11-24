"""Database models. Naive UTC datetimes; sensitive values stored hashed/encrypted only."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .security import utcnow


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_no: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    realname_status: Mapped[str] = mapped_column(String(16), default="unverified")  # unverified/pending/approved/rejected/active
    realname_activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locale: Mapped[str] = mapped_column(String(8), default="zh_CN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    domains: Mapped[list["Domain"]] = relationship(back_populates="owner")


class UserTunnel(Base):
    """One Cloudflare Tunnel per user; all of the user's domains share it."""

    __tablename__ = "user_tunnels"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    tunnel_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tunnel_name: Mapped[str] = mapped_column(String(128))
    token_cipher: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="stopped")
    # Control-plane mode: the desktop agent owns cloudflared. These fields
    # are reported by that agent, never assumed by the central server.
    agent_last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    agent_running: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_active_connections: Mapped[int] = mapped_column(Integer, default=0)
    agent_domain_count: Mapped[int] = mapped_column(Integer, default=0)
    agent_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ua_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # verify / reset
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RealnameSubmission(Base):
    __tablename__ = "realname_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    doc_type: Mapped[str] = mapped_column(String(16))
    # Only HMAC + last 4 digits; never the document image or the full number.
    doc_number_hmac: Mapped[str] = mapped_column(String(64), index=True)
    doc_last4: Mapped[str] = mapped_column(String(4))
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ActivationCode(Base):
    __tablename__ = "activation_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_no: Mapped[str] = mapped_column(String(24), index=True)
    code_hmac: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="unused", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    issued_by: Mapped[str] = mapped_column(String(64), default="admin")


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fqdn: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    # pending / ns_pending / tunnel_pending / active / error.  Only "active"
    # means both the DNS record and the Tunnel ingress are live.
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    kind: Mapped[str] = mapped_column(String(16), default="external")  # platform/external/free
    stage: Mapped[str] = mapped_column(String(24), default="pending")
    provider: Mapped[str] = mapped_column(String(16), default="cloudflare")
    ns_mode: Mapped[str] = mapped_column(String(16), default="tunnel")
    verify_token: Mapped[str] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    zone_version: Mapped[int] = mapped_column(Integer, default=1)
    cloudflare_zone_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cloudflare_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tunnel_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    upstream_url: Mapped[str] = mapped_column(String(255), default="http://127.0.0.1:8080")
    ns_nameservers_json: Mapped[list] = mapped_column(JSON, default=list)
    ns_last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="domains")
    records: Mapped[list["DnsRecord"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan"
    )


class DnsRecord(Base):
    __tablename__ = "dns_records"
    __table_args__ = (
        UniqueConstraint("domain_id", "name", "type", "value", "priority", name="uq_record"),
        Index("ix_records_domain", "domain_id", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(253), default="@")
    type: Mapped[str] = mapped_column(String(8))
    ttl: Mapped[int] = mapped_column(Integer, default=300)
    value: Mapped[str] = mapped_column(Text)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    domain: Mapped[Domain] = relationship(back_populates="records")


class ZoneRevision(Base):
    __tablename__ = "zone_revisions"
    __table_args__ = (UniqueConstraint("domain_id", "version", name="uq_zone_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[dict] = mapped_column(JSON)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(64), default="apply")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="upload")
    common_name: Mapped[str] = mapped_column(String(253))
    sans_json: Mapped[list] = mapped_column(JSON, default=list)
    serial: Mapped[str] = mapped_column(String(128))
    fingerprint_sha256: Mapped[str] = mapped_column(String(95), index=True)
    not_before: Mapped[datetime] = mapped_column(DateTime)
    not_after: Mapped[datetime] = mapped_column(DateTime, index=True)
    cert_pem: Mapped[str] = mapped_column(Text)
    chain_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AES-256-GCM ciphertext. NEVER returned by any API.
    key_cipher: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="user")  # user/admin/system
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(253), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "endpoint", "key", name="uq_idem"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(String(128))
    key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
