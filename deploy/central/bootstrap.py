#!/usr/bin/env python3
"""Generate central .env secrets and local admin credentials exactly once."""
from __future__ import annotations

import argparse
import base64
import getpass
import os
import secrets
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.security import hash_password  # noqa: E402

import pyotp  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=str(Path(__file__).parent / "central.env"))
    ap.add_argument("--data-dir", default=str(Path(__file__).parent / "data"))
    ap.add_argument("--email", default="2416444244@qq.com")
    ap.add_argument("--admin-url", default="https://admin.example.com/admin")
    ap.add_argument("--api-url", default="https://api.asnia.cc")
    ap.add_argument("--password", default="")
    args = ap.parse_args()

    env = Path(args.env_file)
    data = Path(args.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    if env.exists():
        print(f"{env} already exists; refusing to overwrite secrets", file=sys.stderr)
        return 2

    password = args.password or ("ADM-" + secrets.token_urlsafe(20))
    totp = pyotp.random_base32()
    values = {
        "LIULI_APP_ENV": "prod",
        "LIULI_SERVER_ROLE": "control",
        "LIULI_LOCAL_MODE": "0",
        # Small-platform convenience: no SMTP required. Identity is still
        # checked manually through the ID email. Set to 0 when SMTP is ready.
        "LIULI_AUTO_VERIFY_EMAIL": "1",
        "LIULI_DATABASE_URL": f"sqlite:///{(data / 'liuli.db').as_posix()}",
        "LIULI_MAIL_OUTBOX_DIR": str(data / "outbox"),
        "LIULI_SECRET_KEY": secrets.token_hex(48),
        "LIULI_CERT_MASTER_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
        "LIULI_CODE_PEPPER": secrets.token_hex(32),
        "LIULI_DOC_PEPPER": secrets.token_hex(32),
        "LIULI_ADMIN_EMAIL": args.email,
        "LIULI_ADMIN_PASSWORD_HASH": hash_password(password),
        "LIULI_ADMIN_TOTP_SECRET": totp,
        "LIULI_ADMIN_PUBLIC_URL": args.admin_url,
        "LIULI_REALNAME_INBOX": args.email,
        "LIULI_PUBLIC_BASE_URL": args.api_url,
        "LIULI_PLATFORM_DOMAIN": "asnia.cc",
        "LIULI_PLATFORM_ZONE_ID": "",
        "LIULI_CLOUDFLARE_ACCOUNT_ID": "",
        "LIULI_CLOUDFLARE_API_TOKEN": "",
        "LIULI_TUNNEL_PROXY_PORT": "8787",
        "LIULI_TUNNEL_CONTROL_PORT": "8788",
        "LIULI_TUNNEL_WARN_CONNECTIONS": "800",
        "LIULI_TUNNEL_MAX_CONNECTIONS": "1000",
        "LIULI_DNSHE_API_KEY": "",
        "LIULI_DNSHE_API_SECRET": "",
    }
    lines = ["# LiuliDNS central control plane. NEVER commit this file.", ""]
    for key, value in values.items():
        lines.append(f"{key}={shlex.quote(str(value))}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(env, 0o600)
    except OSError:
        pass

    cred = data / "admin-credentials.txt"
    cred.write_text(
        "LiuliDNS operator console\n"
        f"URL: {args.admin_url}\n"
        f"Admin email: {args.email}\n"
        f"Password: {password}\n"
        f"TOTP secret (base32): {totp}\n"
        f"TOTP URI: {pyotp.TOTP(totp).provisioning_uri(name=args.email, issuer_name='LiuliDNS')}\n"
        "Use password + TOTP to sign in. Never put this file in the repository.\n",
        encoding="utf-8",
    )
    try:
        os.chmod(cred, 0o600)
    except OSError:
        pass
    print(f"env: {env}")
    print(f"credentials: {cred} (0600)")
    print(f"admin URL: {args.admin_url}")
    print(f"admin password: {password}")
    print(f"TOTP secret: {totp}")
    print("Next: fill LIULI_CLOUDFLARE_* and LIULI_PLATFORM_ZONE_ID in the env file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
