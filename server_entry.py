#!/usr/bin/env python3
"""Run the LiuliDNS API as the desktop client's private local service.

This is only used for the standalone desktop build. It listens on loopback,
stores everything under the per-user data directory, and enables the backend's
explicit local_mode so email verification does not depend on an external mail
server. Real-name status remains unverified until a human operator approves the
submission and issues a one-time activation code in /admin. The local admin
credentials are generated once and written to a 0600 file for the machine owner.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sys
from pathlib import Path


def _data_dir() -> Path:
    configured = os.environ.get("LIULI_LOCAL_DATA")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "LiuliDNS" / "server"
    return Path.home() / ".local" / "share" / "liuli-dns" / "server"


def _secret_file(data: Path) -> dict:
    path = data / "secrets.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    values = {
        "secret_key": secrets.token_hex(48),
        "cert_master_key": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
        "code_pepper": secrets.token_hex(32),
        "doc_pepper": secrets.token_hex(32),
    }
    path.write_text(json.dumps(values, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return values


def _ensure_local_admin(data: Path, secrets_data: dict) -> None:
    """Create a local operator account; never auto-approves any user."""
    if os.environ.get("LIULI_LOCAL_ADMIN", "1") == "0":
        return
    if os.environ.get("LIULI_ADMIN_PASSWORD_HASH") and os.environ.get("LIULI_ADMIN_TOTP_SECRET"):
        return
    import base64
    import secrets as pysecrets
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from backend.app.security import hash_password

    cred_path = data / "admin-credentials.txt"
    if not secrets_data.get("admin_password_hash") or not secrets_data.get("admin_totp_secret"):
        password = "ADM-" + pysecrets.token_urlsafe(14)
        totp_secret = base64.b32encode(pysecrets.token_bytes(20)).decode("ascii").rstrip("=")
        secrets_data["admin_password_hash"] = hash_password(password)
        secrets_data["admin_totp_secret"] = totp_secret
        (data / "secrets.json").write_text(json.dumps(secrets_data, indent=2), encoding="utf-8")
        cred_path.write_text(
            "LiuliDNS local operator console\n"
            "URL: " + os.environ.get("LIULI_ADMIN_PUBLIC_URL",
                "http://127.0.0.1:" + os.environ.get("LIULI_LOCAL_PORT", "8000") + "/admin") + "\n"
            f"Password: {password}\n"
            f"TOTP secret (base32): {totp_secret}\n"
            "This account reviews real-name submissions and issues activation codes.\n",
            encoding="utf-8",
        )
        try:
            os.chmod(cred_path, 0o600)
        except OSError:
            pass
    os.environ["LIULI_ADMIN_PASSWORD_HASH"] = secrets_data["admin_password_hash"]
    os.environ["LIULI_ADMIN_TOTP_SECRET"] = secrets_data["admin_totp_secret"]
    os.environ.setdefault("LIULI_ADMIN_EMAIL", "local-admin@liuli.local")


def main() -> None:
    data = _data_dir()
    data.mkdir(parents=True, exist_ok=True)
    secrets_data = _secret_file(data)
    _ensure_local_admin(data, secrets_data)
    outbox = data / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)

    log_path = data / "server.log"
    log = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log

    port = int(os.environ.get("LIULI_LOCAL_PORT", "8000"))
    os.environ["LIULI_APP_ENV"] = "dev"
    os.environ["LIULI_LOCAL_MODE"] = "1"
    os.environ["LIULI_SECRET_KEY"] = secrets_data["secret_key"]
    os.environ["LIULI_CERT_MASTER_KEY"] = secrets_data["cert_master_key"]
    os.environ["LIULI_CODE_PEPPER"] = secrets_data["code_pepper"]
    os.environ["LIULI_DOC_PEPPER"] = secrets_data["doc_pepper"]
    os.environ["LIULI_DATABASE_URL"] = "sqlite:///" + (data / "liuli.db").as_posix()
    os.environ["LIULI_MAIL_OUTBOX_DIR"] = str(outbox)
    os.environ.setdefault("LIULI_REALNAME_INBOX", "2416444244@qq.com")
    os.environ.setdefault("LIULI_ADMIN_PUBLIC_URL",
                          f"http://127.0.0.1:{port}/admin")
    os.environ["LIULI_PUBLIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    os.environ["LIULI_DNS_PORT"] = "5353"
    os.environ["LIULI_PUBLIC_IP"] = "127.0.0.1"

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from backend.app.main import app  # noqa: E402
    import uvicorn  # noqa: E402

    print(f"LiuliDNS local API starting on 127.0.0.1:{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
