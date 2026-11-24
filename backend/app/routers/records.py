"""DNS record CRUD, transactional batch apply and rollback."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..db import get_db
from ..deps import (
    cached_idempotent, idem_key, ip_hash_of, require_realname, require_verified, store_idempotent,
)
from ..errors import AppError, E
from ..models import User
from ..ratelimit import enforce_user
from ..respond import ok_
from ..schemas import RecordIn, RecordOut, RecordsBatchIn, SimpleOk, ZoneVersionOut
from ..services import dnszone
from .domains import get_owned

router = APIRouter(prefix="/domains/{domain_id}/records", tags=["records"])


@router.get("")
def list_records(domain_id: int, user: User = Depends(require_verified),
                 db: Session = Depends(get_db)):
    d = get_owned(db, domain_id, user)
    rows = dnszone.current_records(db, d.id)
    return ok_({"items": [RecordOut.from_record(r).model_dump() for r in rows], "version": d.zone_version})


@router.post("")
def create_record(domain_id: int, payload: RecordIn, request: Request,
                  user: User = Depends(require_realname), db: Session = Depends(get_db)):
    enforce_user(user.id, f"record_write:{domain_id}", 60, 3600)
    d = get_owned(db, domain_id, user)
    version, rows = dnszone.apply_batch(
        db, d, [payload.model_dump()], "merge", user.id, reason="add"
    )
    write_audit(db, action="record.add", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request), detail={"type": payload.type, "name": payload.name})
    db.commit()
    return ok_({"version": version, "items": [RecordOut.from_record(r).model_dump() for r in rows]})


@router.patch("/{record_id}")
def update_record(domain_id: int, record_id: int, payload: RecordIn, request: Request,
                  user: User = Depends(require_realname), db: Session = Depends(get_db)):
    enforce_user(user.id, f"record_write:{domain_id}", 60, 3600)
    d = get_owned(db, domain_id, user)
    rows = dnszone.current_records(db, d.id)
    target = []
    found = False
    for r in rows:
        if r.id == record_id:
            found = True
            target.append(payload.model_dump())
        else:
            target.append({"name": r.name, "type": r.type, "ttl": r.ttl,
                           "value": r.value, "priority": r.priority or 0})
    if not found:
        raise AppError(E["NOT_FOUND"], "记录不存在", 404)
    version, new_rows = dnszone.apply_batch(db, d, target, "replace", user.id, reason="update")
    write_audit(db, action="record.update", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request), detail={"record_id": record_id, "type": payload.type})
    db.commit()
    return ok_({"version": version, "items": [RecordOut.from_record(r).model_dump() for r in new_rows]})


@router.delete("/{record_id}")
def delete_record(domain_id: int, record_id: int, request: Request,
                  user: User = Depends(require_realname), db: Session = Depends(get_db)):
    enforce_user(user.id, f"record_write:{domain_id}", 60, 3600)
    d = get_owned(db, domain_id, user)
    rows = dnszone.current_records(db, d.id)
    target = []
    found = False
    for r in rows:
        if r.id == record_id:
            found = True
            continue
        target.append({"name": r.name, "type": r.type, "ttl": r.ttl,
                       "value": r.value, "priority": r.priority or 0})
    if not found:
        raise AppError(E["NOT_FOUND"], "记录不存在", 404)
    version, new_rows = dnszone.apply_batch(db, d, target, "replace", user.id, reason="delete")
    write_audit(db, action="record.delete", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request), detail={"record_id": record_id})
    db.commit()
    return ok_({"version": version, "items": [RecordOut.from_record(r).model_dump() for r in new_rows]})


@router.post("/batch")
def batch(domain_id: int, payload: RecordsBatchIn, request: Request,
          user: User = Depends(require_realname), db: Session = Depends(get_db)):
    enforce_user(user.id, f"record_batch:{domain_id}", 30, 3600)
    d = get_owned(db, domain_id, user)
    key = idem_key(request, required=True)
    body = payload.model_dump()
    cached = cached_idempotent(db, user.id, "records.batch", key, body)
    if cached is not None:
        return ok_(cached[0])

    version, rows = dnszone.apply_batch(
        db, d, body["records"], payload.mode, user.id, reason=payload.reason
    )
    data = {
        "version": version,
        "items": [RecordOut.from_record(r).model_dump() for r in rows],
        "mode": payload.mode,
    }
    write_audit(db, action="record.batch", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request),
                detail={"count": len(body["records"]), "mode": payload.mode, "version": version})
    store_idempotent(db, user.id, "records.batch", key, body, data, 200)
    db.commit()
    return ok_(data)


@router.post("/rollback/{version}")
def rollback(domain_id: int, version: int, request: Request,
             user: User = Depends(require_realname), db: Session = Depends(get_db)):
    d = get_owned(db, domain_id, user)
    new_version, rows = dnszone.rollback(db, d, version, user.id)
    write_audit(db, action="record.rollback", actor_id=user.id, target=d.fqdn,
                ip_hash=ip_hash_of(request), detail={"from_version": version, "to_version": new_version})
    db.commit()
    return ok_({"version": new_version,
                "items": [RecordOut.from_record(r).model_dump() for r in rows]})
