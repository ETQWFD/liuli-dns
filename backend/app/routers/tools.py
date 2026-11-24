"""Diagnostic tools: DNS lookup, port reachability, certificate inspection.

Port checks only target domains owned by the caller and only public unicast
addresses, which blocks SSRF into loopback/private networks.
"""

from __future__ import annotations

import ipaddress
import socket
import time

from fastapi import APIRouter, Depends, File, UploadFile
from cryptography.hazmat.primitives import hashes
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_verified
from ..errors import AppError, E
from ..models import User
from ..ratelimit import enforce_user
from ..respond import ok_
from ..services import certs as certsvc
from ..services.verify import check_a, query
from .domains import get_owned

router = APIRouter(prefix="/tools", tags=["tools"])
VALID_TYPES = {"A", "AAAA", "CNAME", "TXT", "MX", "NS", "CAA", "SRV"}


@router.get("/dns-check")
def dns_check(name: str, type: str = "A", user: User = Depends(require_verified)):
    enforce_user(user.id, "tool_dns", 60, 3600)
    rtype = type.strip().upper()
    if rtype not in VALID_TYPES:
        raise AppError(E["VALIDATION"], "不支持的查询类型", 422)
    n = name.strip().lower().rstrip(".")
    if not n or len(n) > 253 or ".." in n:
        raise AppError(E["VALIDATION"], "域名不合法", 422)
    answers = query(n, rtype)
    return ok_({"name": n, "type": rtype, "answers": answers, "count": len(answers)})


@router.post("/port-check")
def port_check(payload: dict, user: User = Depends(require_verified),
               db: Session = Depends(get_db)):
    enforce_user(user.id, "tool_port", 30, 3600)
    domain_id = int(payload.get("domain_id", 0))
    port = int(payload.get("port", 0))
    if not 1 <= port <= 65535:
        raise AppError(E["VALIDATION"], "端口需在 1～65535", 422)
    d = get_owned(db, domain_id, user)
    addrs = [a for a in check_a(d.fqdn) if _is_public(a)]
    if not addrs:
        raise AppError(E["DOMAIN_VERIFY_FAILED"], "域名未解析到可用公网地址", 409)
    results = []
    for addr in addrs[:3]:
        started = time.monotonic()
        try:
            with socket.create_connection((addr, port), timeout=3.0):
                ok_flag, err = True, None
        except OSError as exc:
            ok_flag, err = False, exc.strerror or "connection failed"
        results.append({
            "address": addr, "port": port, "reachable": ok_flag,
            "latency_ms": int((time.monotonic() - started) * 1000), "error": err,
        })
    return ok_({"domain": d.fqdn, "results": results,
                "note": "仅代表本服务器到目标的 TCP 连通性，不构成公网可达承诺"})


@router.post("/cert-inspect")
async def cert_inspect(cert: UploadFile = File(...), user: User = Depends(require_verified)):
    enforce_user(user.id, "tool_cert", 30, 3600)
    pem = await cert.read()
    try:
        parsed = certsvc.parse_certificate(pem)
    except AppError:
        raise
    cn, sans = certsvc._names(parsed)  # noqa: SLF001 - internal helper is intentional here
    from ..security import utcnow
    from ..services.certs import _naive

    return ok_({
        "common_name": cn, "sans": sans, "serial": format(parsed.serial_number, "x"),
        "fingerprint_sha256": parsed.fingerprint(hashes.SHA256()).hex().upper(),
        "not_before": _naive(parsed.not_valid_before_utc).isoformat(),
        "not_after": _naive(parsed.not_valid_after_utc).isoformat(),
        "days_left": max(0, (_naive(parsed.not_valid_after_utc) - utcnow()).days),
    })


def _is_public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )
