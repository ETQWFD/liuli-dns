"""Start and stop the private local API used by the standalone desktop client."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PySide6.QtCore import QObject, Property, Signal

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class LocalService(QObject):
    """Owns the bundled FastAPI process when the API base is loopback.

    A remote API base is left untouched. If a loopback API is already healthy
    (for example a developer started it manually), this object reuses it and
    never kills a process it did not spawn.
    """

    readyChanged = Signal()
    errorChanged = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._ready = False
        self._error = ""
        self._proc: subprocess.Popen | None = None
        self._base = str(getattr(settings, "apiBase", "") or "").rstrip("/")
        self._parsed = urlsplit(self._base)
        self._port = self._parsed.port or 8000

    @Property(bool, notify=readyChanged)
    def ready(self) -> bool:
        return self._ready

    @Property(str, notify=errorChanged)
    def error(self) -> str:
        return self._error

    def _is_local(self) -> bool:
        return (
            self._parsed.scheme == "http"
            and (self._parsed.hostname or "").lower() in LOCAL_HOSTS
            and self._parsed.path.rstrip("/").endswith("/api/v1")
        )

    def _healthy(self) -> bool:
        try:
            resp = httpx.get(
                f"{self._base}/meta/version",
                timeout=1.2,
                trust_env=False,
            )
            return resp.status_code == 200 and bool(resp.json().get("ok"))
        except Exception:
            return False

    def _data_dir(self) -> Path:
        configured = os.environ.get("LIULI_LOCAL_DATA")
        if configured:
            return Path(configured).expanduser()
        if os.name == "nt":
            return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "LiuliDNS" / "server"
        return Path.home() / ".local" / "share" / "liuli-dns" / "server"

    def _command(self) -> tuple[list[str], Path] | None:
        root = Path(__file__).resolve().parents[3]
        if getattr(sys, "frozen", False):
            binary = Path(sys.executable).parent / "liuli-dns-server"
            if binary.exists():
                return [str(binary)], Path(sys.executable).parent
            return None
        exe = Path(sys.executable)
        if os.name == "nt" and exe.parent.name.lower() == "runtime":
            # pythonw.exe can fail to initialise redirected std handles on
            # some Windows builds.  A console interpreter hidden with
            # CREATE_NO_WINDOW is the reliable path for the server child.
            console_exe = exe.parent / "python.exe"
            if console_exe.exists():
                exe = console_exe
            app_root = exe.parent.parent
            script = app_root / "app" / "server_entry.py"
            if script.exists():
                return [str(exe), str(script)], app_root / "app"
            return None
        script = root / "server_entry.py"
        if script.exists():
            return [str(exe), str(script)], root
        return None

    def start(self, tick=None) -> None:
        if not self._is_local():
            self._ready = True
            self.readyChanged.emit()
            return
        if self._healthy():
            self._ready = True
            self.readyChanged.emit()
            return
        command = self._command()
        if command is None:
            self._error = "本机服务文件缺失，请重新安装"
            self.errorChanged.emit()
            return
        cmd, cwd = command
        data = self._data_dir()
        data.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["LIULI_LOCAL_DATA"] = str(data)
        env["LIULI_LOCAL_PORT"] = str(self._port)
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        try:
            child_log = open(data / "server-child.log", "ab", buffering=0)
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=env,
                stdout=child_log,
                stderr=child_log,
                **kwargs,
            )
            child_log.close()
        except Exception as exc:
            self._error = f"本机服务启动失败：{exc}"
            self.errorChanged.emit()
            return
        for _ in range(90):
            if tick is not None:
                tick()
            if self._healthy():
                self._ready = True
                self.readyChanged.emit()
                return
            if self._proc.poll() is not None:
                break
            time.sleep(0.5)
        self._error = "本机服务启动超时，日志见用户数据目录 server.log"
        self.errorChanged.emit()

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=4)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
