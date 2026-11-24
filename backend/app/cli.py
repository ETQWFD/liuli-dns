"""Offline operator CLI: password hash, TOTP secret, maintenance."""

from __future__ import annotations

import argparse
import getpass
import sys

import pyotp
from argon2 import PasswordHasher

from .config import get_settings
from .db import get_sessionmaker, init_db
from .jobs import run_maintenance


def _check_strength(password: str) -> None:
    classes = sum([
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ])
    if len(password) < 14 or classes < 3:
        raise SystemExit("密码至少 14 位，且包含大小写/数字/符号中的至少三类")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="liuli-admin", description="LiuliDNS operator CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_hash = sub.add_parser("hash-password", help="generate an Argon2id hash for LIULI_ADMIN_PASSWORD_HASH")
    p_hash.add_argument("password", nargs="?")

    sub.add_parser("gen-totp", help="generate a base32 TOTP secret + provisioning URI")

    p_admin = sub.add_parser("init-admin", help="print admin env lines")
    p_admin.add_argument("--email", default="admin@example.com")
    p_admin.add_argument("--password", default=None)

    sub.add_parser("maintenance", help="run one maintenance pass")

    args = parser.parse_args(argv)
    s = get_settings()

    if args.cmd == "hash-password":
        pw = args.password or getpass.getpass("Password: ")
        _check_strength(pw)
        print(PasswordHasher().hash(pw))
        return 0

    if args.cmd == "gen-totp":
        secret = pyotp.random_base32()
        uri = pyotp.TOTP(secret).provisioning_uri(name=s.admin_email or "admin", issuer_name="LiuliDNS")
        print(f"LIULI_ADMIN_TOTP_SECRET={secret}")
        print(f"otpauth://... {uri}")
        return 0

    if args.cmd == "init-admin":
        pw = args.password or getpass.getpass("Admin password: ")
        _check_strength(pw)
        secret = pyotp.random_base32()
        print("# add these to your environment / .env (never commit them)")
        print(f"LIULI_ADMIN_EMAIL={args.email}")
        print(f"LIULI_ADMIN_PASSWORD_HASH={PasswordHasher().hash(pw)}")
        print(f"LIULI_ADMIN_TOTP_SECRET={secret}")
        print(f"# TOTP URI: {pyotp.TOTP(secret).provisioning_uri(name=args.email, issuer_name='LiuliDNS')}")
        return 0

    if args.cmd == "maintenance":
        init_db()
        with get_sessionmaker()() as db:
            print(run_maintenance(db))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
