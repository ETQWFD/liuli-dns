"""Python control plane for the single Go Tunnel supervisor per user.

The Go binary owns the cloudflared process and the local reverse proxy. Python
only writes a non-secret mapping file and a 0600 token file, then talks to the
Go control port. The Cloudflare API token itself never reaches the client.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import AppError, E
from ..models import Domain, User, UserTunnel
from ..security import decrypt_secret, encrypt_secret, utcnow
from .cloudflare import CloudflareClient, CloudflareError

log = logging.getLogger("liuli.tunnel")


def _fallback_state_dir() -> Path:
    configured = os.environ.get("LIULI_LOCAL_DATA")
    if configured:
        return Path(configured).expanduser() / "tunnel"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "LiuliDNS" / "server" / "tunnel"
    return Path.home() / ".local" / "share" / "liuli-dns" / "server" / "tunnel"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


class TunnelManager:
    def __init__(self) -> None:
        s = get_settings()
        self.settings = s
        self.state_dir = Path(s.tunnel_state_dir).expanduser() if s.tunnel_state_dir else _fallback_state_dir()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._proc: subprocess.Popen | None = None

    @property
    def remote_control(self) -> bool:
        return self.settings.server_role == "control"

    # ---- filesystem / binaries ----
    def binary(self) -> Path | None:
        s = self.settings
        candidates: list[Path] = []
        if s.tunnel_binary:
            candidates.append(Path(s.tunnel_binary).expanduser())
        if getattr(__import__("sys"), "frozen", False):
            candidates.append(Path(__import__("sys").executable).parent / "liuli-tunnel")
            if os.name == "nt":
                candidates.append(Path(__import__("sys").executable).parent / "liuli-tunnel.exe")
        candidates += [
            _project_root() / "build-tools" / "tunnel-dist" / "liuli-tunnel",
            _project_root() / "build-tools" / "tunnel-dist" / "liuli-tunnel.exe",
            Path("/usr/lib/liuli-dns/liuli-tunnel"),
        ]
        for p in candidates:
            if p.exists() and p.is_file():
                return p
        return None

    def cloudflared(self) -> Path | None:
        s = self.settings
        if s.cloudflared_binary:
            return Path(s.cloudflared_binary).expanduser()
        found = shutil.which("cloudflared")
        if found:
            return Path(found)
        names = ["cloudflared.exe", "cloudflared"] if os.name == "nt" else ["cloudflared"]
        roots = [
            Path(__import__("sys").executable).parent if getattr(__import__("sys"), "frozen", False) else None,
            _project_root(),
            _project_root() / "build-tools",
            _project_root() / "build-tools" / "win-stage",
            Path("/usr/lib/liuli-dns"),
        ]
        extra = ["cloudflared-linux-amd64", "cloudflared-windows-amd64.exe"]
        for root in roots:
            if root is None:
                continue
            for name in names + extra:
                p = root / name
                if p.exists() and p.is_file():
                    return p
        return None

    def _token_path(self) -> Path:
        return self.state_dir / "tunnel-token"

    def _config_path(self) -> Path:
        return self.state_dir / "tunnel.json"

    def _domains_path(self) -> Path:
        return self.state_dir / "domains.json"

    def _control_url(self, path: str = "/health") -> str:
        return f"http://127.0.0.1:{self.settings.tunnel_control_port}{path}"

    # ---- status ----
    def _http_status(self) -> dict:
        try:
            with httpx.Client(timeout=2.0, trust_env=False) as client:
                r = client.get(self._control_url("/status"))
                if r.status_code == 200:
                    return r.json()
        except Exception:  # noqa: BLE001
            pass
        return {}

    def status(self, db: Session, user: User) -> dict:
        row = db.scalar(select(UserTunnel).where(UserTunnel.user_id == user.id))
        if self.remote_control:
            fresh = bool(
                row and row.agent_last_seen_at
                and (utcnow() - row.agent_last_seen_at).total_seconds()
                <= self.settings.agent_stale_seconds
            )
            running = bool(row and row.agent_running and fresh)
            return {
                "configured": bool(row),
                "running": running,
                "tunnel_id": row.tunnel_id if row else None,
                "active_connections": int(row.agent_active_connections or 0) if row else 0,
                "warn_connections": self.settings.tunnel_warn_connections,
                "max_connections": self.settings.tunnel_max_connections,
                "warning": bool(
                    row and row.agent_active_connections >= self.settings.tunnel_warn_connections
                ),
                "domain_count": int(row.agent_domain_count or 0) if row else 0,
                "last_error": (
                    (row.agent_error if row and row.agent_error else
                     ("本机隧道代理尚未连接" if row else "尚未创建 Tunnel"))
                ),
                "agent_last_seen_at": row.agent_last_seen_at.isoformat() if row and row.agent_last_seen_at else None,
            }
        live = self._http_status()
        if live:
            live["configured"] = bool(live.get("configured") and row)
            live["tunnel_id"] = row.tunnel_id if row else None
            return live
        return {
            "configured": bool(row),
            "running": False,
            "tunnel_id": row.tunnel_id if row else None,
            "active_connections": 0,
            "warn_connections": self.settings.tunnel_warn_connections,
            "max_connections": self.settings.tunnel_max_connections,
            "warning": False,
            "domain_count": 0,
            "last_error": "本机隧道进程未运行" if row else "尚未创建 Tunnel",
        }

    # ---- tunnel provisioning ----
    def ensure_user_tunnel(self, db: Session, user: User) -> UserTunnel:
        row = db.scalar(select(UserTunnel).where(UserTunnel.user_id == user.id))
        if row is not None:
            return row
        s = self.settings
        if not s.tunnel_configured:
            raise AppError(E["CLOUDFLARE_NOT_CONFIGURED"],
                           "域名暂不可用：服务端未配置 Cloudflare API 与 Tunnel", 503)
        cf = CloudflareClient()
        name = f"liuli-{user.user_no.lower()}"
        info = cf.create_tunnel(name)
        row = UserTunnel(
            user_id=user.id,
            tunnel_id=info.id,
            tunnel_name=name,
            token_cipher=encrypt_secret(info.token),
            status="stopped",
        )
        db.add(row)
        db.flush()
        return row

    def _write_token(self, row: UserTunnel) -> None:
        token = decrypt_secret(row.token_cipher)
        p = self._token_path()
        p.write_text(token, encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    def _write_domains(self, db: Session, user: User) -> int:
        rows = db.scalars(
            select(Domain).where(
                Domain.user_id == user.id,
                Domain.status.in_(("active", "tunnel_pending")),
            )
        ).all()
        items = []
        for d in rows:
            if not d.upstream_url:
                continue
            items.append({"hostname": d.fqdn, "upstream": d.upstream_url})
        payload = {"domains": items}
        self._domains_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        return len(items)

    def _write_config(self, row: UserTunnel) -> None:
        cf = self.cloudflared()
        binary = self.binary()
        cfg = {
            "cloudflared": str(cf) if cf else "",
            "token_file": str(self._token_path()),
            "proxy_listen": f"127.0.0.1:{self.settings.tunnel_proxy_port}",
            "control_listen": f"127.0.0.1:{self.settings.tunnel_control_port}",
            "domains_file": str(self._domains_path()),
            "state_dir": str(self.state_dir),
            "warn_connections": self.settings.tunnel_warn_connections,
            "max_connections": self.settings.tunnel_max_connections,
            "restart_limit": 20,
        }
        self._config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        if binary is None:
            raise AppError(E["TUNNEL_UNAVAILABLE"],
                           "域名暂不可用：本机未找到 liuli-tunnel 服务", 503)

    def start(self, db: Session, user: User) -> dict:
        row = db.scalar(select(UserTunnel).where(UserTunnel.user_id == user.id))
        if row is None:
            raise AppError(E["TUNNEL_UNAVAILABLE"],
                           "域名暂不可用：尚未创建 Tunnel", 503)
        if self.remote_control:
            return self.status(db, user)
        live = self._http_status()
        if live.get("ok") or live.get("running"):
            self._write_token(row)
            self._write_domains(db, user)
            self._call_reload()
            return self.status(db, user)
        self._write_token(row)
        self._write_domains(db, user)
        self._write_config(row)
        binary = self.binary()
        if binary is None:
            raise AppError(E["TUNNEL_UNAVAILABLE"],
                           "域名暂不可用：本机未找到 liuli-tunnel 服务", 503)
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        log_path = self.state_dir / "supervisor.log"
        log = open(log_path, "ab", buffering=0)
        try:
            self._proc = subprocess.Popen(
                [str(binary), "run", "--config", str(self._config_path())],
                cwd=str(self.state_dir),
                stdout=log,
                stderr=log,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            log.close()
            raise AppError(E["TUNNEL_UNAVAILABLE"],
                           f"域名暂不可用：隧道服务启动失败：{exc}", 503)
        log.close()
        for _ in range(45):
            live = self._http_status()
            if live.get("running"):
                break
            if live.get("last_error"):
                break
            time.sleep(0.2)
        return self.status(db, user)

    def _call_reload(self) -> None:
        try:
            with httpx.Client(timeout=2.0, trust_env=False) as client:
                client.post(self._control_url("/reload"))
        except Exception:  # noqa: BLE001
            pass

    def sync(self, db: Session, user: User) -> None:
        row = db.scalar(select(UserTunnel).where(UserTunnel.user_id == user.id))
        if row is None:
            return
        if self.remote_control:
            return
        self._write_token(row)
        self._write_domains(db, user)
        self._call_reload()

    def ensure_running(self, db: Session, user: User) -> None:
        if self.remote_control:
            # The desktop agent reports its own state via heartbeat. The
            # control plane still configured DNS/ingress for the hostname.
            return
        status = self.start(db, user)
        if not status.get("running"):
            raise AppError(
                E["TUNNEL_UNAVAILABLE"],
                "域名暂不可用：Tunnel 未运行，请查看本机隧道日志",
                503,
                {"last_error": status.get("last_error")},
            )

    def configure_ingress(self, db: Session, user: User, hostnames: list[str]) -> None:
        row = db.scalar(select(UserTunnel).where(UserTunnel.user_id == user.id))
        if row is None:
            raise AppError(E["TUNNEL_UNAVAILABLE"], "域名暂不可用：尚未创建 Tunnel", 503)
        try:
            CloudflareClient().configure_ingress(
                row.tunnel_id, hostnames, self.settings.tunnel_proxy_port
            )
        except CloudflareError as exc:
            raise AppError(exc.code, exc.message, exc.status, exc.details) from exc

    def agent_config(self, db: Session, user: User) -> dict:
        """Return the per-user tunnel token and hostname map to the desktop agent.

        This is only meaningful in control-plane deployments. The Cloudflare
        API token never appears here; the user receives only their own Tunnel
        token, which they could already obtain from Cloudflare.
        """
        row = db.scalar(select(UserTunnel).where(UserTunnel.user_id == user.id))
        if row is None:
            raise AppError(E["TUNNEL_UNAVAILABLE"], "尚未创建 Tunnel，请先在域名页启动隧道", 409)
        domains = [
            {"hostname": d.fqdn, "upstream": d.upstream_url}
            for d in db.scalars(
                select(Domain).where(
                    Domain.user_id == user.id,
                    Domain.status.in_(("active", "tunnel_pending")),
                )
            ).all()
            if d.upstream_url
        ]
        return {
            "configured": True,
            "tunnel_id": row.tunnel_id,
            "token": decrypt_secret(row.token_cipher),
            "proxy_port": self.settings.tunnel_proxy_port,
            "control_port": self.settings.tunnel_control_port,
            "warn_connections": self.settings.tunnel_warn_connections,
            "max_connections": self.settings.tunnel_max_connections,
            "domains": domains,
        }

    def agent_heartbeat(self, db: Session, user: User, payload: dict) -> dict:
        row = db.scalar(select(UserTunnel).where(UserTunnel.user_id == user.id))
        if row is None:
            raise AppError(E["TUNNEL_UNAVAILABLE"], "尚未创建 Tunnel", 409)
        row.agent_last_seen_at = utcnow()
        row.agent_running = bool(payload.get("running"))
        row.agent_active_connections = max(0, int(payload.get("active_connections") or 0))
        row.agent_domain_count = max(0, int(payload.get("domain_count") or 0))
        row.agent_error = (str(payload.get("last_error") or "")[:500] or None)
        row.agent_version = (str(payload.get("version") or "")[:32] or None)
        row.status = "running" if row.agent_running else "stopped"
        db.commit()
        return self.status(db, user)

    def stop(self) -> None:
        try:
            with httpx.Client(timeout=2.0, trust_env=False) as client:
                client.post(self._control_url("/stop"))
        except Exception:  # noqa: BLE001
            pass
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass


def get_tunnel_manager() -> TunnelManager:
    return TunnelManager()
