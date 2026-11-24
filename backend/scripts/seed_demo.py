"""Seed a demo account/domain for local DNS testing.

NEVER run this against production. It bypasses review/verification on purpose.
Usage:
    LIULI_DATABASE_URL=sqlite:///./data/liuli.db python scripts/seed_demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import get_sessionmaker, init_db  # noqa: E402
from app.models import DnsRecord, Domain, User, ZoneRevision  # noqa: E402
from app.security import hash_password, utcnow  # noqa: E402
from app.services import dnszone  # noqa: E402


def main() -> None:
    email = os.environ.get("LIULI_DEMO_EMAIL", "demo@liuli.dev")
    password = os.environ.get("LIULI_DEMO_PASSWORD", "DemoPassw0rd!")
    fqdn = os.environ.get("LIULI_DEMO_DOMAIN", "demo.liuli.test")
    init_db()
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                user_no="U-DEMO-000001", email=email, password_hash=hash_password(password),
                email_verified_at=utcnow(), realname_status="active",
                realname_activated_at=utcnow(),
            )
            db.add(user)
            db.flush()
            print(f"created user {email} / {password}")

        domain = db.scalar(select(Domain).where(Domain.fqdn == fqdn))
        if domain is None:
            import secrets

            domain = Domain(
                user_id=user.id, fqdn=fqdn, status="active", ns_mode="delegated",
                verify_token=secrets.token_hex(16), verified_at=utcnow(),
            )
            db.add(domain)
            db.flush()
            db.add(ZoneRevision(domain_id=domain.id, version=1,
                                snapshot_json={"records": [], "captured_at": utcnow().isoformat()},
                                actor_id=user.id, reason="seed"))
            db.commit()
            print(f"created domain {fqdn}")

        if not db.scalars(select(DnsRecord).where(DnsRecord.domain_id == domain.id)).all():
            dnszone.apply_batch(
                db, domain,
                [
                    {"name": "@", "type": "A", "ttl": 300, "value": "203.0.113.10"},
                    {"name": "www", "type": "A", "ttl": 300, "value": "203.0.113.10"},
                    {"name": "@", "type": "MX", "ttl": 300, "value": "mail.liuli.test", "priority": 10},
                    {"name": "@", "type": "TXT", "ttl": 300, "value": "v=spf1 -all"},
                    {"name": "blog", "type": "CNAME", "ttl": 300, "value": "pages.example.com"},
                ],
                "replace", user.id, reason="seed",
            )
            db.commit()
            print("records seeded")
        print(f"user_no={user.user_no} domain={domain.fqdn} version={domain.zone_version}")


if __name__ == "__main__":
    main()
