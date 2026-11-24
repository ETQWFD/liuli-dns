"""Desktop-side tunnel agent for a remote LiuliDNS control plane.

In standalone mode the bundled Python server owns cloudflared. In a multi-user
deployment the central server only manages accounts, real-name review and
Cloudflare DNS/ingress. Each user's computer must run its own cloudflared, so
this class pulls the user's own Tunnel token + hostname map and starts the
bundled Go supervisor locally. The Cloudflare API token never reaches the
desktop.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger("liuli.agent")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
VERSION = "0.2.2"


class TunnelAgent(QObject):
    statusChanged = Signal(bool, str)

    def __init__(self, settings, parent=None):  # noqa: ANN001
        super().__init__(parent)
        self.settings = settings
        self._base = str(getattr(settings, "apiBase", "") or "").rstrip("/")
        self._access = ""
        self._remote = self._is_remote(self._base)
        self._busy = False
        self._pending = False
        self._proc: subprocess.Popen | None = None
        self._last_status: dict = {}
        self._status_error = ""
        self._state_dir = self._default_dir()
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self.heartbeat)
        self._start_after: QTimer | None = None

    # ---------- paths ----------
    @staticmethod
    def _is_remote(base: str) -> bool:
        try:
            p = urlsplit(base)
            return bool(p.hostname) and p.hostname.lower() not in LOCAL_HOSTS
        except ValueError:
            return False

    @staticmethod
    def _default_dir() -> Path:
        configured = os.environ.get("LIULI_AGENT_DATA")
        if configured:
            return Path(configured).expanduser()
        if os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            return base / "LiuliDNS" / "agent"
        return Path.home() / ".local" / "share" / "liuli-dns" / "agent"

    @staticmethod
    def _roots() -> list[Path]:
        exe = Path(sys.executable)
        roots = [exe.parent]
        if getattr(sys, "frozen", False):
            roots.append(Path(getattr(sys, "_MEIPASS", exe.parent)))
            roots.append(exe.parent / "runtime")
        roots += [
            Path("/usr/lib/liuli-dns"),
            Path(__file__).resolve().parents[3] / "build-tools" / "tunnel-dist",
            Path(__file__).resolve().parents[3],
            Path(__file__).resolve().parents[3] / "build-tools",
            Path(__file__).resolve().parents[3] / "build-tools" / "win-stage",
            Path(__file__).resolve().parents[3] / "build-tools" / "win-stage" / "runtime",
        ]
        return roots

    def _find(self, names: list[str], env_names: tuple[str, ...] = ()) -> Path | None:
        for env_name in env_names:
            path = os.environ.get(env_name, "").strip()
            if path:
                p = Path(path).expanduser()
                if p.exists() and p.is_file():
                    return p
        for root in self._roots():
            for name in names:
                p = root / name
                if p.exists() and p.is_file():
                    return p
        return None

    def _tunnel_bin(self) -> Path | None:
        return self._find(["liuli-tunnel", "liuli-tunnel.exe"], ("LIULI_TUNNEL_BIN",))

    def _cloudflared(self) -> Path | None:
        return self._find(["cloudflared", "cloudflared.exe",
                           "cloudflared-linux-amd64", "cloudflared-windows-amd64.exe"],
                          ("LIULI_CLOUDFLARED_BIN", "LIULI_CLOUDFLARED"))

    # ---------- session ----------
    def set_session(self, base: str, access_token: str) -> None:
        self._base = (base or "").rstrip("/")
        self._access = access_token or ""
        self._remote = self._is_remote(self._base)
        if not self._remote:
            self._timer.stop()
            # Switching from a central server back to a local API must not
            # leave a previously spawned tunnel or token behind.
            self.stop()
            return
        self._timer.start()
        # Let login settle before touching the network.
        if self._start_after is not None:
            self._start_after.stop()
        self._start_after = QTimer(self)
        self._start_after.setSingleShot(True)
        self._start_after.timeout.connect(self.sync)
        self._start_after.start(600)

    def clear_session(self) -> None:
        self._access = ""
        self._timer.stop()
        self.stop()

    # ---------- control ----------
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access}", "Accept": "application/json"}

    def _portal(self, path: str) -> str:
        return self._base + "/" + path.lstrip("/")

    def _http(self, path: str) -> dict:
        with httpx.Client(timeout=3.0, trust_env=False) as c:
            r = c.get(self._portal(path), headers=self._headers())
        if r.status_code == 401:
            raise RuntimeError("登录状态已过期，等待客户端刷新令牌")
        if r.status_code != 200:
            raise RuntimeError(f"控制面返回 HTTP {r.status_code}")
        data = r.json()
        if not data.get("ok"):
            err = data.get("error") or {}
            raise RuntimeError(str(err.get("message") or "控制面拒绝了隧道配置"))
        return data.get("data") or {}

    def sync(self) -> None:
        if not self._remote or not self._access:
            return
        if self._busy:
            self._pending = True
            return
        self._busy = True
        threading.Thread(target=self._sync_worker, daemon=True).start()

    def _sync_worker(self) -> None:
        try:
            try:
                cfg = self._http("/domains/agent/config")
            except Exception as exc:  # noqa: BLE001
                self._set_status(False, str(exc)[:500])
                return
            self._state_dir.mkdir(parents=True, exist_ok=True)
            token = str(cfg.get("token") or "")
            if not token:
                self._set_status(False, "控制面未返回 Tunnel token")
                return
            (self._state_dir / "tunnel-token").write_text(token, encoding="utf-8")
            try:
                os.chmod(self._state_dir / "tunnel-token", 0o600)
            except OSError:
                pass
            domains = {"domains": [
                {"hostname": str(d.get("hostname") or ""),
                 "upstream": str(d.get("upstream") or "")}
                for d in (cfg.get("domains") or []) if d.get("hostname") and d.get("upstream")
            ]}
            (self._state_dir / "domains.json").write_text(
                json.dumps(domains, ensure_ascii=False, indent=2), encoding="utf-8")
            tunnel = self._tunnel_bin()
            cf = self._cloudflared()
            if tunnel is None:
                self._set_status(False, "安装包缺少 liuli-tunnel，请重新安装")
                return
            if cf is None:
                self._set_status(False, "安装包缺少 cloudflared，请重新安装")
                return
            control_port = int(cfg.get("control_port") or 8788)
            cfg_json = {
                "cloudflared": str(cf),
                "token_file": str(self._state_dir / "tunnel-token"),
                "proxy_listen": f"127.0.0.1:{int(cfg.get('proxy_port') or 8787)}",
                "control_listen": f"127.0.0.1:{control_port}",
                "domains_file": str(self._state_dir / "domains.json"),
                "state_dir": str(self._state_dir),
                "warn_connections": int(cfg.get("warn_connections") or 800),
                "max_connections": int(cfg.get("max_connections") or 1000),
                "restart_limit": 20,
            }
            cfg_path = self._state_dir / "tunnel.json"
            cfg_path.write_text(json.dumps(cfg_json, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            status = self._local_status(control_port)
            if status.get("running"):
                self._reload(control_port)
            elif self._proc is None or self._proc.poll() is not None:
                self._start(cfg_path)
                # A freshly spawned Go supervisor needs a moment to start the
                # proxy and cloudflared. Do not tell the UI "connected" before
                # the local control endpoint confirms it.
                for _ in range(20):
                    time.sleep(0.2)
                    status = self._local_status(control_port)
                    if status.get("running") or status.get("last_error"):
                        break
            self._set_status(bool(status.get("running")),
                             str(status.get("last_error") or "")[:500])
        finally:
            self._busy = False
            if self._pending:
                self._pending = False
                self.sync()

    def _local_status(self, control_port: int) -> dict:
        try:
            with httpx.Client(timeout=1.5, trust_env=False) as c:
                r = c.get(f"http://127.0.0.1:{control_port}/status")
            if r.status_code == 200:
                return r.json()
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _reload(self, control_port: int) -> None:
        try:
            with httpx.Client(timeout=1.5, trust_env=False) as c:
                c.post(f"http://127.0.0.1:{control_port}/reload")
        except Exception:  # noqa: BLE001
            pass

    def _start(self, cfg_path: Path) -> None:
        tunnel = self._tunnel_bin()
        if tunnel is None:
            self._set_status(False, "安装包缺少 liuli-tunnel")
            return
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        log_path = self._state_dir / "agent.log"
        log_file = open(log_path, "ab", buffering=0)
        try:
            self._proc = subprocess.Popen(
                [str(tunnel), "run", "--config", str(cfg_path)],
                cwd=str(self._state_dir), stdout=log_file, stderr=log_file, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self._set_status(False, f"本机隧道启动失败：{exc}")
        finally:
            log_file.close()

    def heartbeat(self) -> None:
        if not self._remote or not self._access:
            return
        threading.Thread(target=self._heartbeat_worker, daemon=True).start()

    def _heartbeat_worker(self) -> None:
        base = self._base
        token = self._access
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as c:
                # Determine the control port from our saved config; if it is
                # not present yet the sync worker has not run.
                try:
                    cfg = json.loads((self._state_dir / "tunnel.json").read_text(encoding="utf-8"))
                    port = int(cfg.get("control_listen", "127.0.0.1:8788").rsplit(":", 1)[1])
                except Exception:  # noqa: BLE001
                    port = 8788
                status = {}
                try:
                    r = c.get(f"http://127.0.0.1:{port}/status", timeout=1.5)
                    if r.status_code == 200:
                        status = r.json()
                except Exception:  # noqa: BLE001
                    pass
                body = {
                    "running": bool(status.get("running", False)),
                    "active_connections": int(status.get("active_connections") or 0),
                    "domain_count": int(status.get("domain_count") or 0),
                    "last_error": str(status.get("last_error") or "")[:500],
                    "version": VERSION,
                }
                c.post(base + "/domains/agent/heartbeat", headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/json",
                }, json=body)
        except Exception:  # noqa: BLE001
            log.debug("tunnel heartbeat failed", exc_info=True)

    def _set_status(self, ok: bool, message: str) -> None:
        self._last_status = {"running": ok, "error": message}
        self._status_error = message
        try:
            self.statusChanged.emit(ok, message)
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=8, check=False)
                else:
                    # The supervisor starts a new session, so kill its whole
                    # process group (incl. cloudflared) rather than only the
                    # Go parent. This prevents orphan tunnels after logout.
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    if os.name != "nt":
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        try:
            (self._state_dir / "tunnel-token").unlink(missing_ok=True)
        except OSError:
            pass
