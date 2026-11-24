"""Certificate upload/replace, expiry listing. Private keys are encrypted at rest
and are never returned by any endpoint."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..db import get_db
from ..deps import ip_hash_of, require_realname, require_verified
from ..errors import AppError, E
from ..models import Certificate, Domain, User
from ..ratelimit import enforce_user
from ..respond import ok_
from ..schemas import CertificateOut, SimpleOk
from ..security import decrypt_secret, encrypt_secret, utcnow
from ..services import certs as certsvc
from .domains import get_owned, _out

router = APIRouter(prefix="/domains/{domain_id}/certificates", tags=["certificates"])
extra_router = APIRouter(prefix="/certificates", tags=["certificates"])


def _meta(c: Certificate) -> CertificateOut:
    return CertificateOut.from_cert(c, certsvc.days_left(c.not_after))


@router.get("")
def list_certs(domain_id: int, user: User = Depends(require_verified),
               db: Session = Depends(get_db)):
    d = get_owned(db, domain_id, user)
    rows = db.scalars(
        select(Certificate).where(Certificate.domain_id == d.id).order_by(Certificate.id.desc())
    ).all()
    return ok_({"items": [_meta(c).model_dump(mode="json") for c in rows]})


@router.post("")
async def upload_cert(
    domain_id: int,
    request: Request,
    cert: UploadFile = File(...),
    key: UploadFile = File(...),
    chain: UploadFile | None = File(None),
    password: str | None = Form(None),
    user: User = Depends(require_realname),
    db: Session = Depends(get_db),
):
    enforce_user(user.id, f"cert_upload:{domain_id}", 10, 3600)
    d = get_owned(db, domain_id, user, require_active=True)

    cert_bytes = await cert.read()
    key_bytes = await key.read()
    chain_bytes = await chain.read() if chain is not None else None
    if not cert_bytes or not key_bytes:
        raise AppError(E["CERT_INVALID"], "证书与私钥不能为空", 422)

    facts = certsvc.validate_for_domain(d.fqdn, cert_bytes, key_bytes, chain_bytes, password)
    key_cipher = encrypt_secret(facts.key_pem)
    del facts.key_pem  # drop the plaintext reference as soon as possible

    existing = db.scalars(
        select(Certificate).where(Certificate.domain_id == d.id, Certificate.status == "active")
    ).all()
    for old in existing:
        old.status = "replaced"
        old.replaced_at = utcnow()

    row = Certificate(
        domain_id=d.id, source="upload", common_name=facts.common_name,
        sans_json=facts.sans, serial=facts.serial, fingerprint_sha256=facts.fingerprint,
        not_before=facts.not_before, not_after=facts.not_after,
        cert_pem=facts.cert_pem, chain_pem=facts.chain_pem, key_cipher=key_cipher,
        status="active",
    )
    db.add(row)
    db.flush()
    write_audit(db, action="cert.upload", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request),
                detail={"cert_id": row.id, "fingerprint": facts.fingerprint,
                        "not_after": facts.not_after.isoformat(), "replaced": len(existing)})
    db.commit()
    return ok_(_meta(row).model_dump(mode="json"))


@router.post("/{cert_id}/activate")
def activate_cert(domain_id: int, cert_id: int, request: Request,
                  user: User = Depends(require_realname), db: Session = Depends(get_db)):
    d = get_owned(db, domain_id, user)
    target = db.get(Certificate, cert_id)
    if target is None or target.domain_id != d.id:
        raise AppError(E["NOT_FOUND"], "证书不存在", 404)
    if target.not_after <= utcnow():
        raise AppError(E["CERT_EXPIRED"], "该证书已过期，不能启用", 422)
    for c in db.scalars(select(Certificate).where(Certificate.domain_id == d.id)):
        if c.id == target.id:
            c.status = "active"
            c.replaced_at = None
        elif c.status == "active":
            c.status = "replaced"
            c.replaced_at = utcnow()
    write_audit(db, action="cert.activate", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request), detail={"cert_id": cert_id})
    db.commit()
    return ok_(_meta(target).model_dump(mode="json"))


@router.delete("/{cert_id}")
def delete_cert(domain_id: int, cert_id: int, request: Request,
                user: User = Depends(require_realname), db: Session = Depends(get_db)):
    d = get_owned(db, domain_id, user)
    row = db.get(Certificate, cert_id)
    if row is None or row.domain_id != d.id:
        raise AppError(E["NOT_FOUND"], "证书不存在", 404)
    write_audit(db, action="cert.delete", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request), detail={"cert_id": cert_id})
    db.delete(row)
    db.commit()
    return ok_(SimpleOk(message="证书已删除").model_dump())


@router.post("/acme/order")
def acme_order(domain_id: int, user: User = Depends(require_realname),
               db: Session = Depends(get_db)):
    """ACME is optional and not bundled in the MVP image.

    The supported production path is manual issuance (e.g. certbot DNS-01)
    followed by uploading the PEM bundle here, so no CA account secrets live
    on the client.
    """
    raise AppError(
        E["CERT_NOT_CONFIGURED"],
        "ACME 自动签发未启用；请使用 DNS-01 手动签发后上传证书",
        501,
        {
            "steps": [
                "在支持 DNS-01 的工具（如 certbot）中为域名申请证书",
                "将 _acme-challenge TXT 记录加入本域名的解析记录",
                "签发成功后上传 fullchain.pem 与 privkey.pem",
            ]
        },
    )


@extra_router.get("/expiring")
def expiring(days: int = 45, user: User = Depends(require_verified),
             db: Session = Depends(get_db)):
    from ..models import Domain as D

    rows = db.execute(
        select(Certificate, D)
        .join(D, D.id == Certificate.domain_id)
        .where(
            D.user_id == user.id,
            Certificate.status == "active",
            Certificate.not_after <= utcnow() + timedelta(days=max(1, min(days, 365))),
        )
        .order_by(Certificate.not_after)
    ).all()
    items = []
    for cert, dom in rows:
        m = _meta(cert).model_dump(mode="json")
        m["domain"] = dom.fqdn
        items.append(m)
    return ok_({"items": items, "checked_at": utcnow().isoformat()})
