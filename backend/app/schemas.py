"""Pydantic request/response models."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

RECORD_TYPES = ("A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA")


class CaptchaOut(BaseModel):
    captcha_id: str
    question: str
    expires_in: int


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    captcha_id: str = Field(min_length=8, max_length=64)
    captcha_answer: str = Field(min_length=1, max_length=16)
    session_id: str | None = Field(default=None, max_length=64)
    locale: str = "zh_CN"

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v) or not re.search(r"[0-9]", v):
            raise ValueError("密码需同时包含字母与数字")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    captcha_id: str | None = None
    captcha_answer: str | None = None
    session_id: str | None = None


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class UserOut(BaseModel):
    id: int
    user_no: str
    email: str
    email_verified: bool
    realname_status: str
    realname_activated_at: datetime | None
    created_at: datetime

    @classmethod
    def from_user(cls, u) -> "UserOut":  # noqa: ANN001
        status = u.realname_status
        if status == "none":  # legacy local-build value
            status = "unverified"
        return cls(
            id=u.id,
            user_no=u.user_no,
            email=u.email,
            email_verified=u.email_verified_at is not None,
            realname_status=status,
            realname_activated_at=u.realname_activated_at,
            created_at=u.created_at,
        )


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class SimpleOk(BaseModel):
    ok: bool = True
    message: str = "ok"


class RealnameSubmitIn(BaseModel):
    doc_type: Literal["id_card", "passport"]
    doc_number: str = Field(min_length=6, max_length=40)


class RealnameStatusOut(BaseModel):
    status: str
    activated_at: datetime | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    reject_reason: str | None = None
    inbox: str | None = None
    instructions: list[str] = []


class ActivateIn(BaseModel):
    code: str = Field(min_length=8, max_length=40)


class DomainCreateIn(BaseModel):
    fqdn: str = Field(min_length=3, max_length=253)
    ns_mode: Literal["delegated", "local_lab", "tunnel"] = "tunnel"
    upstream_url: str = Field(default="http://127.0.0.1:8080", max_length=255)


class PlatformDomainIn(BaseModel):
    prefix: str = Field(min_length=1, max_length=63)
    upstream_url: str = Field(default="http://127.0.0.1:8080", max_length=255)

    @field_validator("prefix")
    @classmethod
    def _label(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.match(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", v):
            raise ValueError("前缀只能是小写字母、数字和中间连字符")
        return v


class ExternalDomainIn(BaseModel):
    fqdn: str = Field(min_length=3, max_length=253)
    upstream_url: str = Field(default="http://127.0.0.1:8080", max_length=255)


class FreeDomainIn(BaseModel):
    prefix: str = Field(min_length=1, max_length=63)
    suffix: str = Field(default="de5.net", max_length=64)
    upstream_url: str = Field(default="http://127.0.0.1:8080", max_length=255)


class UpstreamIn(BaseModel):
    upstream_url: str = Field(min_length=1, max_length=255)


class TunnelStatusOut(BaseModel):
    configured: bool
    running: bool
    tunnel_id: str | None = None
    active_connections: int = 0
    warn_connections: int = 800
    max_connections: int = 1000
    warning: bool = False
    domain_count: int = 0
    last_error: str | None = None


class VerificationOut(BaseModel):
    mode: str
    nameservers: list[str]
    txt_name: str
    txt_value: str
    verified_at: datetime | None = None


class DomainOut(BaseModel):
    id: int
    fqdn: str
    status: str
    kind: str
    stage: str
    provider: str
    ns_mode: str
    zone_version: int
    verification: VerificationOut
    tunnel_id: str | None = None
    public_url: str | None = None
    ns_nameservers: list[str] = Field(default_factory=list)
    upstream_url: str = "http://127.0.0.1:8080"
    last_error: str | None = None
    tunnel_status: str = "unknown"
    created_at: datetime

    @classmethod
    def from_domain(cls, d, ns: list[str], platform: str, with_token: bool = True,
                    tunnel_status: str = "unknown") -> "DomainOut":  # noqa: ANN001
        stage = getattr(d, "stage", None) or ("active" if d.status == "active" else "pending")
        kind = getattr(d, "kind", None) or "external"
        nameservers = list(getattr(d, "ns_nameservers_json", None) or [])
        if kind == "external" and not nameservers:
            nameservers = list(ns)
        return cls(
            id=d.id,
            fqdn=d.fqdn,
            status=d.status,
            kind=kind,
            stage=stage,
            provider=getattr(d, "provider", None) or "cloudflare",
            ns_mode=d.ns_mode,
            zone_version=d.zone_version,
            tunnel_id=getattr(d, "tunnel_id", None),
            public_url=f"https://{d.fqdn}",
            ns_nameservers=nameservers,
            upstream_url=getattr(d, "upstream_url", None) or "http://127.0.0.1:8080",
            last_error=getattr(d, "last_error", None),
            tunnel_status=tunnel_status,
            verification=VerificationOut(
                mode="ns" if kind != "platform" else "tunnel",
                nameservers=nameservers if kind == "external" else [],
                txt_name=f"_liuli-verify.{d.fqdn}",
                txt_value=d.verify_token if with_token else "***",
                verified_at=d.verified_at,
            ),
            created_at=d.created_at,
        )


class RecordIn(BaseModel):
    name: str = Field(default="@", max_length=253)
    type: str = Field(min_length=1, max_length=8)
    ttl: int = Field(default=300, ge=60, le=86400)
    value: str = Field(min_length=1, max_length=2048)
    priority: int | None = Field(default=None, ge=0, le=65535)


class RecordOut(BaseModel):
    id: int
    name: str
    type: str
    ttl: int
    value: str
    priority: int | None

    @classmethod
    def from_record(cls, r) -> "RecordOut":  # noqa: ANN001
        return cls(
            id=r.id, name=r.name, type=r.type, ttl=r.ttl, value=r.value,
            priority=(r.priority or None),
        )


class RecordsBatchIn(BaseModel):
    records: list[RecordIn] = Field(max_length=200)
    mode: Literal["merge", "replace"] = "merge"
    reason: str = Field(default="apply", max_length=64)


class ZoneVersionOut(BaseModel):
    version: int
    records: list[RecordOut]
    created_at: datetime | None = None


class CertificateOut(BaseModel):
    id: int
    common_name: str
    sans: list[str]
    serial: str
    fingerprint_sha256: str
    not_before: datetime
    not_after: datetime
    status: str
    source: str
    created_at: datetime
    days_left: int

    @classmethod
    def from_cert(cls, c, days_left: int) -> "CertificateOut":  # noqa: ANN001
        return cls(
            id=c.id, common_name=c.common_name, sans=list(c.sans_json or []), serial=c.serial,
            fingerprint_sha256=c.fingerprint_sha256, not_before=c.not_before,
            not_after=c.not_after, status=c.status, source=c.source,
            created_at=c.created_at, days_left=days_left,
        )


class AuditOut(BaseModel):
    id: int
    actor_type: str
    action: str
    target: str | None
    detail: dict
    created_at: datetime
