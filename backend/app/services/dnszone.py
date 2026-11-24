"""DNS zone validation, snapshots, transactional apply and rollback."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..errors import AppError, E
from ..models import DnsRecord, Domain, ZoneRevision
from ..security import utcnow

LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
ALLOWED_TYPES = {"A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA"}
MAX_RECORDS = 500


def normalize_fqdn(raw: str) -> str:
    s = (raw or "").strip().lower().rstrip(".")
    if not s or len(s) > 253:
        raise AppError(E["DOMAIN_INVALID"], "域名长度不合法", 422)
    try:
        s.encode("ascii")
    except UnicodeEncodeError:
        raise AppError(E["DOMAIN_INVALID"], "请使用 Punycode（xn--）形式的国际化域名", 422)
    labels = s.split(".")
    if len(labels) < 2:
        raise AppError(E["DOMAIN_INVALID"], "请输入完整的一级域名，例如 example.com", 422)
    for label in labels:
        if not LABEL_RE.match(label):
            raise AppError(E["DOMAIN_INVALID"], f"域名标签不合法：{label}", 422)
    if not re.search(r"[a-z]", labels[-1]):
        raise AppError(E["DOMAIN_INVALID"], "顶级域不合法", 422)
    return s


def normalize_name(raw: str, fqdn: str) -> str:
    s = (raw or "@").strip().lower().rstrip(".")
    if s in ("", "@"):
        return "@"
    if s == fqdn:
        return "@"
    if s.endswith("." + fqdn):
        s = s[: -len(fqdn) - 1]
    if s == "*":
        return "*"
    if s.startswith("*."):
        prefix = "*"
        rest = s[2:]
        if not rest:
            raise AppError(E["RECORD_INVALID"], "通配记录不合法", 422)
        for label in rest.split("."):
            if not LABEL_RE.match(label):
                raise AppError(E["RECORD_INVALID"], "记录名不合法", 422)
        return f"*.{rest}"
    for label in s.split("."):
        if not LABEL_RE.match(label):
            raise AppError(E["RECORD_INVALID"], f"记录名不合法：{label}", 422)
    return s


def _target_fqdn(value: str) -> str:
    v = value.strip().lower().rstrip(".")
    if not v or len(v) > 253:
        raise AppError(E["RECORD_INVALID"], "目标域名不合法", 422)
    for label in v.split("."):
        if not LABEL_RE.match(label):
            raise AppError(E["RECORD_INVALID"], f"目标域名不合法：{v}", 422)
    return v


def validate_record(raw: dict[str, Any], fqdn: str) -> dict[str, Any]:
    rtype = str(raw.get("type", "")).strip().upper()
    if rtype not in ALLOWED_TYPES:
        raise AppError(E["RECORD_INVALID"], f"不支持的记录类型：{rtype}", 422)
    name = normalize_name(str(raw.get("name", "@")), fqdn)
    ttl = int(raw.get("ttl", 300))
    if ttl < 60 or ttl > 86400:
        raise AppError(E["RECORD_INVALID"], "TTL 需在 60～86400 秒之间", 422)
    value = str(raw.get("value", "")).strip()
    if not value or len(value) > 2048:
        raise AppError(E["RECORD_INVALID"], "记录值不合法", 422)
    priority = raw.get("priority")
    priority = 0 if priority in (None, "") else int(priority)
    if priority < 0 or priority > 65535:
        raise AppError(E["RECORD_INVALID"], "优先级不合法", 422)

    if rtype == "A":
        try:
            ipaddress.IPv4Address(value)
        except ValueError:
            raise AppError(E["RECORD_INVALID"], "A 记录必须是合法 IPv4 地址", 422)
    elif rtype == "AAAA":
        try:
            ipaddress.IPv6Address(value)
        except ValueError:
            raise AppError(E["RECORD_INVALID"], "AAAA 记录必须是合法 IPv6 地址", 422)
    elif rtype in ("CNAME", "NS", "MX"):
        value = _target_fqdn(value)
        owner = fqdn if name == "@" else f"{name}.{fqdn}"
        if rtype == "CNAME" and value == owner:
            raise AppError(E["RECORD_INVALID"], "CNAME 不能指向自身", 422)
        if rtype == "MX":
            if not priority:
                raise AppError(E["RECORD_INVALID"], "MX 记录需要优先级", 422)
    elif rtype == "TXT":
        if len(value) > 1024:
            raise AppError(E["RECORD_INVALID"], "TXT 内容过长", 422)
    elif rtype == "SRV":
        parts = value.split()
        if len(parts) != 3:
            raise AppError(E["RECORD_INVALID"], "SRV 值格式应为「权重 端口 目标」", 422)
        weight, port, target = parts
        if not weight.isdigit() or not port.isdigit() or not (0 <= int(port) <= 65535):
            raise AppError(E["RECORD_INVALID"], "SRV 端口或权重不合法", 422)
        value = f"{int(weight)} {int(port)} {_target_fqdn(target)}"
    elif rtype == "CAA":
        parts = value.split(None, 2)
        if len(parts) != 3 or not parts[0].isdigit() or parts[1] not in ("issue", "issuewild", "iodef"):
            raise AppError(E["RECORD_INVALID"], "CAA 值格式应为「0 issue ca.example」", 422)
        clean = parts[2].strip('"')
        value = f"{int(parts[0])} {parts[1]} {clean}"

    if name != "@" and name.startswith("*."):
        pass  # wildcard only as left-most label, enforced above
    return {"name": name, "type": rtype, "ttl": ttl, "value": value, "priority": priority}


def _check_set(records: list[dict[str, Any]]) -> None:
    if len(records) > MAX_RECORDS:
        raise AppError(E["RECORD_INVALID"], f"单个域名最多 {MAX_RECORDS} 条记录", 422)
    cname_names = {r["name"] for r in records if r["type"] == "CNAME"}
    if any(n == "@" for n in cname_names):
        raise AppError(E["RECORD_INVALID"], "根记录（@）不能设置 CNAME", 422)
    if len(cname_names) != len([r for r in records if r["type"] == "CNAME"]):
        raise AppError(E["RECORD_CONFLICT"], "同一名称只能有一条 CNAME", 409)
    for name in cname_names:
        if any(r["name"] == name and r["type"] != "CNAME" for r in records):
            raise AppError(E["RECORD_CONFLICT"], f"{name} 存在 CNAME 与其它类型冲突", 409)


def snapshot(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "name": r["name"], "type": r["type"], "ttl": r["ttl"],
                "value": r["value"], "priority": r["priority"],
            }
            for r in records
        ),
        key=lambda r: (r["name"], r["type"], r["value"], r["priority"] or 0),
    )


def current_records(db: Session, domain_id: int) -> list[DnsRecord]:
    return list(
        db.scalars(
            select(DnsRecord).where(DnsRecord.domain_id == domain_id).order_by(DnsRecord.id)
        )
    )


def record_dicts(db: Session, domain_id: int) -> list[dict[str, Any]]:
    return [
        {"name": r.name, "type": r.type, "ttl": r.ttl, "value": r.value, "priority": r.priority or 0}
        for r in current_records(db, domain_id)
    ]


def apply_batch(
    db: Session,
    domain: Domain,
    incoming: list[dict[str, Any]],
    mode: str,
    actor_id: int,
    reason: str = "apply",
) -> tuple[int, list[DnsRecord]]:
    """Validate and apply in a single DB transaction managed by the caller."""
    validated = [validate_record(r, domain.fqdn) for r in incoming]
    if mode == "merge":
        target = record_dicts(db, domain.id)
        seen = {(r["name"], r["type"], r["value"], r["priority"] or 0) for r in target}
        for r in validated:
            key = (r["name"], r["type"], r["value"], r["priority"] or 0)
            if key in seen:
                for existing in target:
                    if (existing["name"], existing["type"], existing["value"], existing["priority"] or 0) == key:
                        existing["ttl"] = r["ttl"]
            else:
                target.append(r)
                seen.add(key)
    else:
        target = validated

    keys = {(r["name"], r["type"], r["value"], r["priority"] or 0) for r in target}
    if len(keys) != len(target):
        raise AppError(E["RECORD_CONFLICT"], "存在重复记录", 409)
    _check_set(target)

    existing_rows = current_records(db, domain.id)
    keep: dict[tuple, DnsRecord] = {}
    for row in existing_rows:
        k = (row.name, row.type, row.value, row.priority or 0)
        if k in keys:
            keep[k] = row
        else:
            db.delete(row)
    for r in target:
        k = (r["name"], r["type"], r["value"], r["priority"] or 0)
        row = keep.get(k)
        if row is None:
            db.add(
                DnsRecord(
                    domain_id=domain.id, name=r["name"], type=r["type"], ttl=r["ttl"],
                    value=r["value"], priority=r["priority"],
                )
            )
        elif row.ttl != r["ttl"]:
            row.ttl = r["ttl"]
            row.updated_at = utcnow()

    domain.zone_version += 1
    db.flush()
    db.add(
        ZoneRevision(
            domain_id=domain.id, version=domain.zone_version,
            snapshot_json={"records": snapshot(target), "captured_at": utcnow().isoformat()},
            actor_id=actor_id, reason=reason,
        )
    )
    db.flush()
    return domain.zone_version, current_records(db, domain.id)


def rollback(db: Session, domain: Domain, version: int, actor_id: int) -> tuple[int, list[DnsRecord]]:
    rev = db.scalar(
        select(ZoneRevision).where(
            ZoneRevision.domain_id == domain.id, ZoneRevision.version == version
        )
    )
    if rev is None:
        raise AppError(E["NOT_FOUND"], "指定版本不存在", 404)
    records = (rev.snapshot_json or {}).get("records", [])
    validated = [validate_record(r, domain.fqdn) for r in records]
    _check_set(validated)
    db.execute(delete(DnsRecord).where(DnsRecord.domain_id == domain.id))
    for r in validated:
        db.add(
            DnsRecord(
                domain_id=domain.id, name=r["name"], type=r["type"], ttl=r["ttl"],
                value=r["value"], priority=r["priority"],
            )
        )
    domain.zone_version += 1
    db.flush()
    db.add(
        ZoneRevision(
            domain_id=domain.id, version=domain.zone_version,
            snapshot_json={"records": snapshot(validated), "captured_at": utcnow().isoformat()},
            actor_id=actor_id, reason=f"rollback:{version}",
        )
    )
    db.flush()
    return domain.zone_version, current_records(db, domain.id)


def reconcile(db: Session, domain: Domain, actor_id: int) -> tuple[int, list[DnsRecord]]:
    """Rebuild a snapshot from the DB (the DB is the source of truth)."""
    rows = record_dicts(db, domain.id)
    cleaned = [validate_record(r, domain.fqdn) for r in rows]
    _check_set(cleaned)
    domain.zone_version += 1
    db.flush()
    db.add(
        ZoneRevision(
            domain_id=domain.id, version=domain.zone_version,
            snapshot_json={"records": snapshot(cleaned), "captured_at": utcnow().isoformat()},
            actor_id=actor_id, reason="reconcile",
        )
    )
    db.flush()
    return domain.zone_version, current_records(db, domain.id)


def revision_list(db: Session, domain_id: int, limit: int = 20) -> list[ZoneRevision]:
    return list(
        db.scalars(
            select(ZoneRevision)
            .where(ZoneRevision.domain_id == domain_id)
            .order_by(ZoneRevision.version.desc())
            .limit(limit)
        )
    )
