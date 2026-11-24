"""Public metadata and health endpoints (no secrets)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..logging_setup import request_id_ctx
from ..respond import ok_

router = APIRouter(tags=["meta"])


@router.get("/meta/version")
def version():
    s = get_settings()
    return ok_({
        "name": s.app_name,
        "version": s.app_version,
        "env": s.app_env,
        "request_id": request_id_ctx.get(),
    })


@router.get("/meta/public")
def public_config():
    s = get_settings()
    return ok_({
        "name": s.app_name,
        "version": s.app_version,
        "platform_domain": s.platform_domain,
        "nameservers": s.nameserver_list,
        "realname_inbox": s.realname_inbox,
        "admin_url": s.admin_public_url,
        "capabilities": {
            "registrar": False,
            "dns_records": ["A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA"],
            "acme_auto": False,
            "certificate_upload": True,
            "tunnel": True,
            "tunnel_configured": s.tunnel_configured,
            "platform_secondary_domains": True,
            "free_domain": bool(s.dnshe_api_key and s.dnshe_api_secret),
            "ipv4_origin": False,
        },
        "disclaimer": (
            "平台审核非官方权威核验；所有公网域名必须通过 Cloudflare Tunnel，"
            "不依赖公网 IPv4 或开放入站端口；免费版无 SLA，国内访问速度和稳定性不承诺。"
        ),
    })


@router.get("/healthz")
def healthz(request: Request, db: Session = Depends(get_db)):
    request_id_ = request_id_ctx.get()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return ok_({"status": "ok" if db_ok else "degraded", "db": db_ok, "request_id": request_id_})
