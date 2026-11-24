"""Domain onboarding through Cloudflare Tunnel and NS delegation.

Every public hostname must have a Cloudflare DNS record pointing at the
user's single Tunnel and an ingress rule pointing at the Go proxy. A domain is
never marked active merely because a button was clicked.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..config import get_settings
from ..db import get_db
from ..deps import ip_hash_of, require_realname, require_verified
from ..errors import AppError, E
from ..models import Certificate, Domain, User, UserTunnel, ZoneRevision
from ..ratelimit import enforce_user
from ..respond import ok_
from ..schemas import (
    AgentHeartbeatIn, DomainCreateIn, DomainOut, ExternalDomainIn, FreeDomainIn,
    PlatformDomainIn, SimpleOk, UpstreamIn,
)
from ..security import utcnow
from ..services import dnszone
from ..services.cloudflare import CloudflareClient, CloudflareError
from ..services.freedomain import FreeDomainError, get_free_provider
from ..services.tunnel import TunnelManager, get_tunnel_manager
from ..services.verify import check_ns_switched

router = APIRouter(prefix="/domains", tags=["domains"])


def get_owned(db: Session, domain_id: int, user: User, require_active: bool = False) -> Domain:
    d = db.get(Domain, domain_id)
    if d is None or d.user_id != user.id:
        raise AppError(E["NOT_FOUND"], "域名不存在", 404)
    if require_active and d.status != "active":
        raise AppError(E["DOMAIN_NOT_ACTIVE"], "域名尚未生效", 403)
    return d


def _cf() -> CloudflareClient:
    return CloudflareClient()


def _tunnel() -> TunnelManager:
    return get_tunnel_manager()


def _upstream(raw: str) -> str:
    v = (raw or "").strip()
    if not v:
        v = "http://127.0.0.1:8080"
    try:
        u = urlsplit(v)
    except ValueError:
        raise AppError(E["UPSTREAM_INVALID"], "源站地址不合法", 422)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise AppError(E["UPSTREAM_INVALID"], "源站必须是 http(s):// 地址", 422)
    if u.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise AppError(E["UPSTREAM_INVALID"], "源站必须运行在本机 loopback（127.0.0.1/localhost）", 422)
    if u.username or u.password or u.fragment:
        raise AppError(E["UPSTREAM_INVALID"], "源站地址不能包含账号、密码或片段", 422)
    return v.rstrip("/")


def _hosts(db: Session, user: User, extra: str = "") -> list[str]:
    rows = db.scalars(
        select(Domain).where(
            Domain.user_id == user.id,
            Domain.status.in_(("active", "tunnel_pending")),
        )
    ).all()
    hosts = [d.fqdn for d in rows]
    if extra:
        hosts.append(extra)
    return sorted(set(hosts))


def _out(d: Domain) -> DomainOut:
    s = get_settings()
    return DomainOut.from_domain(
        d, list(d.ns_nameservers_json or s.nameserver_list), s.platform_domain,
        tunnel_status="active" if d.status == "active" else d.stage,
    )


def _count(db: Session, user: User) -> int:
    return db.scalar(select(func.count(Domain.id)).where(Domain.user_id == user.id)) or 0


def _check_limit(db: Session, user: User) -> None:
    if _count(db, user) >= get_settings().tunnel_per_user_domains:
        raise AppError(E["DOMAIN_LIMIT"], "每个账号最多 5 个域名（一级/二级合计）", 409)


def _ensure_tunnel(db: Session, user: User) -> UserTunnel:
    mgr = _tunnel()
    row = mgr.ensure_user_tunnel(db, user)
    mgr.start(db, user)
    return row


def _decorate_error(exc: Exception) -> AppError:
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, CloudflareError):
        return AppError(exc.code, exc.message, exc.status, exc.details)
    return AppError(E["TUNNEL_UNAVAILABLE"], f"域名暂不可用：{exc}", 502)


@router.get("")
def list_domains(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Domain).where(Domain.user_id == user.id).order_by(Domain.id.desc())
    ).all()
    return ok_({"items": [_out(d).model_dump(mode="json") for d in rows]})


@router.get("/tunnel/status")
def tunnel_status(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    s = get_settings()
    data = _tunnel().status(db, user)
    return ok_({
        "configured": bool(data.get("configured")),
        "running": bool(data.get("running")),
        "tunnel_id": data.get("tunnel_id"),
        "active_connections": int(data.get("active_connections") or 0),
        "warn_connections": int(data.get("warn_connections") or s.tunnel_warn_connections),
        "max_connections": int(data.get("max_connections") or s.tunnel_max_connections),
        "warning": bool(data.get("warning")),
        "domain_count": int(data.get("domain_count") or 0),
        "last_error": data.get("last_error"),
        "api_configured": s.tunnel_configured,
    })


@router.post("/tunnel/start")
def tunnel_start(user: User = Depends(require_realname), db: Session = Depends(get_db)):
    try:
        _ensure_tunnel(db, user)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise _decorate_error(exc) from exc
    return ok_(_tunnel().status(db, user))


@router.get("/agent/config")
def agent_config(user: User = Depends(require_realname), db: Session = Depends(get_db)):
    """Desktop tunnel agent pulls its own token and hostname map here."""
    return ok_(_tunnel().agent_config(db, user))


@router.post("/agent/heartbeat")
def agent_heartbeat(payload: AgentHeartbeatIn,
                    user: User = Depends(require_realname), db: Session = Depends(get_db)):
    """Desktop agent reports real process state; the server never invents it."""
    return ok_(_tunnel().agent_heartbeat(db, user, payload.model_dump()))


@router.post("/platform")
def create_platform(payload: PlatformDomainIn, request: Request,
                    user: User = Depends(require_realname), db: Session = Depends(get_db)):
    s = get_settings()
    enforce_user(user.id, "domain_platform_create", 5, 3600)
    _check_limit(db, user)
    prefix = payload.prefix.strip().lower()
    fqdn = f"{prefix}.{s.platform_domain}"
    if db.scalar(select(Domain).where(Domain.fqdn == fqdn)) is not None:
        raise AppError(E["DOMAIN_EXISTS"], "该二级域名已被添加", 409)
    upstream = _upstream(payload.upstream_url)
    cf = _cf()
    try:
        zone = cf.ensure_zone(s.platform_domain, platform=True,
                              platform_zone_id=s.platform_zone_id)
    except Exception as exc:  # noqa: BLE001
        raise _decorate_error(exc) from exc

    d = Domain(
        user_id=user.id, fqdn=fqdn, status="tunnel_pending", kind="platform",
        stage="tunnel_pending", provider="cloudflare", ns_mode="tunnel",
        verify_token=secrets.token_hex(16), cloudflare_zone_id=zone.id,
        upstream_url=upstream,
    )
    db.add(d)
    db.flush()
    db.add(ZoneRevision(domain_id=d.id, version=d.zone_version,
                        snapshot_json={"records": [], "captured_at": utcnow().isoformat()},
                        actor_id=user.id, reason="create"))
    record_id = ""
    try:
        tunnel = _ensure_tunnel(db, user)
        d.tunnel_id = tunnel.tunnel_id
        record_id = cf.ensure_cname(zone.id, fqdn, tunnel.tunnel_id)
        d.cloudflare_record_id = record_id
        _tunnel().configure_ingress(db, user, _hosts(db, user, fqdn))
        _tunnel().ensure_running(db, user)
        d.status = "active"
        d.stage = "active"
        d.verified_at = utcnow()
        d.last_error = None
        _tunnel().sync(db, user)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        try:
            if record_id:
                cf.delete_dns_record(zone.id, record_id)
        except Exception:  # noqa: BLE001
            pass
        raise _decorate_error(exc) from exc
    write_audit(db, action="domain.platform.create", actor_id=user.id, target=fqdn,
                ip_hash=ip_hash_of(request),
                detail={"zone_id": zone.id, "tunnel_id": d.tunnel_id,
                        "upstream": upstream})
    db.commit()
    return ok_(_out(d).model_dump(mode="json"))


@router.post("/external")
def create_external(payload: ExternalDomainIn, request: Request,
                    user: User = Depends(require_realname), db: Session = Depends(get_db)):
    s = get_settings()
    enforce_user(user.id, "domain_external_create", 5, 3600)
    _check_limit(db, user)
    fqdn = dnszone.normalize_fqdn(payload.fqdn)
    if fqdn == s.platform_domain or fqdn.endswith("." + s.platform_domain):
        raise AppError(E["DOMAIN_INVALID"], "平台自有域名请使用二级域名入口", 422)
    if db.scalar(select(Domain).where(Domain.fqdn == fqdn)) is not None:
        raise AppError(E["DOMAIN_EXISTS"], "该域名已被添加", 409)
    upstream = _upstream(payload.upstream_url)
    cf = _cf()
    try:
        zone = cf.ensure_zone(fqdn)
    except Exception as exc:  # noqa: BLE001
        raise _decorate_error(exc) from exc
    if not zone.nameservers:
        raise AppError(E["CLOUDFLARE_API_ERROR"], "域名暂不可用：Cloudflare 未返回 NS 地址", 502)
    d = Domain(
        user_id=user.id, fqdn=fqdn, status="ns_pending", kind="external",
        stage="ns_pending", provider="cloudflare", ns_mode="tunnel",
        verify_token=secrets.token_hex(16), cloudflare_zone_id=zone.id,
        upstream_url=upstream, ns_nameservers_json=zone.nameservers,
    )
    db.add(d)
    db.flush()
    db.add(ZoneRevision(domain_id=d.id, version=d.zone_version,
                        snapshot_json={"records": [], "captured_at": utcnow().isoformat()},
                        actor_id=user.id, reason="create"))
    write_audit(db, action="domain.external.create", actor_id=user.id, target=fqdn,
                ip_hash=ip_hash_of(request),
                detail={"zone_id": zone.id, "nameservers": zone.nameservers})
    db.commit()
    return ok_(_out(d).model_dump(mode="json"))


@router.post("/free")
def create_free(payload: FreeDomainIn, request: Request,
                user: User = Depends(require_realname), db: Session = Depends(get_db)):
    s = get_settings()
    enforce_user(user.id, "domain_free_create", 3, 3600)
    _check_limit(db, user)
    if not (s.dnshe_api_key and s.dnshe_api_secret):
        raise AppError(E["FREE_DOMAIN_UNAVAILABLE"], "该前缀暂不可用：免费域名服务未配置", 503)
    provider = get_free_provider()
    created: dict = {}
    try:
        created = provider.register(payload.prefix.strip().lower(), payload.suffix.strip().lower())
        fqdn = str(created.get("full_domain") or "").lower()
        if not fqdn:
            raise FreeDomainError("该前缀暂不可用：平台未返回域名")
        if db.scalar(select(Domain).where(Domain.fqdn == fqdn)) is not None:
            try:
                provider.delete(int(created.get("subdomain_id") or 0))
            except Exception:  # noqa: BLE001
                pass
            raise AppError(E["DOMAIN_EXISTS"], "该域名已被添加", 409)
        cf = _cf()
        zone = cf.ensure_zone(fqdn)
        provider.set_nameservers(int(created.get("subdomain_id") or 0), zone.nameservers)
    except FreeDomainError as exc:
        raise AppError(E["FREE_DOMAIN_UNAVAILABLE"], exc.message, 502) from exc
    except Exception as exc:  # noqa: BLE001
        try:
            provider.delete(int(created.get("subdomain_id") or 0))
        except Exception:  # noqa: BLE001
            pass
        raise _decorate_error(exc) from exc
    d = Domain(
        user_id=user.id, fqdn=fqdn, status="ns_pending", kind="free",
        stage="ns_pending", provider="free", ns_mode="tunnel",
        verify_token=secrets.token_hex(16), cloudflare_zone_id=zone.id,
        upstream_url=_upstream(payload.upstream_url), ns_nameservers_json=zone.nameservers,
    )
    db.add(d)
    db.flush()
    db.add(ZoneRevision(domain_id=d.id, version=d.zone_version,
                        snapshot_json={"records": [], "captured_at": utcnow().isoformat()},
                        actor_id=user.id, reason="create"))
    write_audit(db, action="domain.free.create", actor_id=user.id, target=fqdn,
                ip_hash=ip_hash_of(request), detail={"provider": "free"})
    db.commit()
    return ok_(_out(d).model_dump(mode="json"))


@router.post("")
def create_domain_compat(payload: DomainCreateIn, request: Request,
                         user: User = Depends(require_realname), db: Session = Depends(get_db)):
    """Compatibility alias for the old ``POST /domains`` action.

    It now uses the external-domain Cloudflare/NS path; it cannot create a
    dangling local-only domain.
    """
    return create_external(ExternalDomainIn(fqdn=payload.fqdn,
                                            upstream_url=payload.upstream_url),
                           request, user, db)


@router.get("/{domain_id}")
def domain_detail(domain_id: int, user: User = Depends(require_verified),
                  db: Session = Depends(get_db)):
    return ok_(_out(get_owned(db, domain_id, user)).model_dump(mode="json"))


@router.patch("/{domain_id}/upstream")
def update_upstream(domain_id: int, payload: UpstreamIn, request: Request,
                    user: User = Depends(require_realname), db: Session = Depends(get_db)):
    d = get_owned(db, domain_id, user)
    d.upstream_url = _upstream(payload.upstream_url)
    if d.status == "active":
        try:
            _tunnel().sync(db, user)
        except Exception as exc:  # noqa: BLE001
            d.last_error = str(exc)[:500]
            db.commit()
            raise _decorate_error(exc) from exc
    write_audit(db, action="domain.upstream", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request), detail={"upstream": d.upstream_url})
    db.commit()
    return ok_(_out(d).model_dump(mode="json"))


@router.post("/{domain_id}/verify")
def verify_domain(domain_id: int, request: Request,
                  user: User = Depends(require_realname), db: Session = Depends(get_db)):
    """Verify external NS delegation; platform domains are already live."""
    d = get_owned(db, domain_id, user)
    if d.kind == "platform":
        return ok_(_out(d).model_dump(mode="json"))
    if d.status == "active":
        return ok_(_out(d).model_dump(mode="json"))
    expected = list(d.ns_nameservers_json or [])
    if not expected:
        raise AppError(E["DOMAIN_NS_PENDING"], "等待 NS 切换：尚未取得 Cloudflare NS 地址", 409,
                       {"ns_expected": []})
    ok_ns, got = check_ns_switched(d.fqdn, expected)
    d.ns_last_checked_at = utcnow()
    if not ok_ns:
        d.last_error = "等待 NS 切换"
        db.commit()
        raise AppError(E["DOMAIN_NS_PENDING"], "等待 NS 切换：请将注册商 NS 改为这两个地址", 409,
                       {"ns_expected": expected, "ns_found": got})
    cf = _cf()
    try:
        tunnel = _ensure_tunnel(db, user)
        d.tunnel_id = tunnel.tunnel_id
        record_id = cf.ensure_cname(d.cloudflare_zone_id or "", d.fqdn, tunnel.tunnel_id)
        d.cloudflare_record_id = record_id
        _tunnel().configure_ingress(db, user, _hosts(db, user, d.fqdn))
        _tunnel().ensure_running(db, user)
        d.status = "active"
        d.stage = "active"
        d.verified_at = utcnow()
        d.last_error = None
        _tunnel().sync(db, user)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise _decorate_error(exc) from exc
    write_audit(db, action="domain.verified", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request),
                detail={"ns_found": got, "ns_expected": expected})
    db.commit()
    return ok_(_out(d).model_dump(mode="json"))


@router.post("/{domain_id}/verify-ns")
def verify_ns_alias(domain_id: int, request: Request,
                    user: User = Depends(require_realname), db: Session = Depends(get_db)):
    return verify_domain(domain_id, request, user, db)


@router.post("/{domain_id}/reconcile")
def reconcile(domain_id: int, request: Request,
              user: User = Depends(require_realname), db: Session = Depends(get_db)):
    d = get_owned(db, domain_id, user)
    version, records = dnszone.reconcile(db, d, user.id)
    write_audit(db, action="domain.reconcile", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request), detail={"version": version})
    db.commit()
    return ok_({"version": version, "records": len(records)})


@router.get("/{domain_id}/revisions")
def revisions(domain_id: int, user: User = Depends(require_verified),
              db: Session = Depends(get_db)):
    d = get_owned(db, domain_id, user)
    rows = dnszone.revision_list(db, d.id)
    return ok_({
        "items": [
            {"version": r.version, "reason": r.reason, "created_at": r.created_at.isoformat(),
             "record_count": len((r.snapshot_json or {}).get("records", []))}
            for r in rows
        ]
    })


@router.delete("/{domain_id}")
def delete_domain(domain_id: int, request: Request,
                  user: User = Depends(require_realname), db: Session = Depends(get_db)):
    d = get_owned(db, domain_id, user)
    cert_count = db.scalar(select(func.count(Certificate.id)).where(Certificate.domain_id == d.id)) or 0
    try:
        _cf().delete_dns_record(d.cloudflare_zone_id or "", d.cloudflare_record_id or "")
    except Exception:  # noqa: BLE001
        pass
    write_audit(db, action="domain.delete", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request), detail={"certificates": cert_count})
    db.delete(d)
    db.commit()
    try:
        _tunnel().sync(db, user)
    except Exception:  # noqa: BLE001
        pass
    return ok_(SimpleOk(message="域名已删除").model_dump())
