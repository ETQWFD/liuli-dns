"""QML ⇄ API bridge. All network calls run on a thread pool; the UI stays smooth.

The bridge holds the access token in memory only and never logs request bodies
that could contain credentials. Idempotency keys are generated per write.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    Property, QObject, QRunnable, QThreadPool, QTimer, QUrl, Signal, Slot,
)
from PySide6.QtGui import QDesktopServices, QGuiApplication

from .core.api import ApiClient, ApiError, base_url_warning
from .core.crash import CrashManager
from .core.localserver import LocalLab
from .core.netutil import add_firewall_rule, port_available, validate_port
from .core.settings import AppSettings
from .core.tokens import TokenStore
from .core.tunnelagent import TunnelAgent

log = logging.getLogger("liuli.bridge")
GITHUB_URL = "https://github.com/ETQWFD/liuli-dns"
MAX_UPLOAD = 96 * 1024


class WorkerSignals(QObject):
    finished = Signal(str, bool, str, str, str, int)


class RequestWorker(QRunnable):
    def __init__(self, base: str, token: str, session_id: str, action: str,
                 method: str, path: str, body: Any, idem: str | None) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self.base = base
        self.token = token
        self.session_id = session_id
        self.action = action
        self.method = method
        self.path = path
        self.body = body
        self.idem = idem

    def run(self) -> None:
        try:
            client = ApiClient(self.base, self.token, self.session_id)
            data = client.request(self.method, self.path, self.body, self.idem)
            self.signals.finished.emit(self.action, True, json.dumps(data, ensure_ascii=False),
                                       "", "", 200)
        except ApiError as exc:
            self.signals.finished.emit(self.action, False, "", exc.code, exc.message, exc.status)
        except Exception as exc:  # noqa: BLE001
            log.exception("request worker crashed")
            self.signals.finished.emit(self.action, False, "", "CLIENT_ERROR", str(exc)[:200], 0)


class UploadWorker(QRunnable):
    def __init__(self, base: str, token: str, session_id: str, domain_id: int,
                 cert: bytes, key: bytes, chain: bytes | None) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self.base = base
        self.token = token
        self.session_id = session_id
        self.domain_id = domain_id
        self.cert = cert
        self.key = key
        self.chain = chain

    def run(self) -> None:
        try:
            client = ApiClient(self.base, self.token, self.session_id)
            files = {
                "cert": ("cert.pem", self.cert, "application/x-pem-file"),
                "key": ("key.pem", self.key, "application/x-pem-file"),
            }
            if self.chain:
                files["chain"] = ("chain.pem", self.chain, "application/x-pem-file")
            data = client.upload(f"/domains/{self.domain_id}/certificates", files)
            self.signals.finished.emit("cert_upload", True,
                                       json.dumps(data, ensure_ascii=False), "", "", 200)
        except ApiError as exc:
            self.signals.finished.emit("cert_upload", False, "", exc.code, exc.message, exc.status)
        except Exception as exc:  # noqa: BLE001
            self.signals.finished.emit("cert_upload", False, "", "CLIENT_ERROR", str(exc)[:200], 0)


class Bridge(QObject):
    apiResult = Signal(str, bool, str, str, str)
    authChanged = Signal(bool, str)
    captchaReady = Signal(str, str, int)
    toast = Signal(str, bool)
    labChanged = Signal(bool, int, str)
    navigateTo = Signal(str)
    resetView = Signal()
    crashLogReady = Signal(str, str)
    serverWarning = Signal(str)
    busyChanged = Signal(bool)

    loggedInChanged = Signal()
    userJsonChanged = Signal()
    labRunningChanged = Signal()

    def __init__(self, settings: AppSettings, crash: CrashManager, parent=None):  # noqa: ANN001
        super().__init__(parent)
        self.settings = settings
        self.crash = crash
        self.pool = QThreadPool.globalInstance()
        self.tokens = TokenStore()
        self._access = ""
        self._access_at = 0.0
        self._refresh = ""
        self._user: dict = {}
        self._logged = False
        self._session_id = uuid.uuid4().hex
        self._workers: list[QRunnable] = []
        self._demo = False
        self._demo_guest = False
        self._demo_domains = _demo_domains()
        self._demo_records = _demo_records()
        self._demo_certs = _demo_certs()
        self._demo_versions: dict[int, list[int]] = {1: [4, 3, 2, 1], 3: [1]}
        self._lab: LocalLab | None = None
        self._lab_port = 0
        self.agent = TunnelAgent(settings)
        self._busy = 0

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(4 * 60 * 1000)
        self._refresh_timer.timeout.connect(self._silent_refresh)

    # ---------- properties ----------
    @Property(bool, notify=loggedInChanged)
    def loggedIn(self) -> bool:
        return self._logged

    @Property(str, notify=userJsonChanged)
    def userJson(self) -> str:
        return json.dumps(self._user, ensure_ascii=False)

    @Property(bool, notify=labRunningChanged)
    def labRunning(self) -> bool:
        return bool(self._lab and self._lab.running)

    @Property(str, constant=True)
    def githubUrl(self) -> str:
        return GITHUB_URL

    @Property(bool, constant=True)
    def demo(self) -> bool:
        return self._demo

    @Property(bool, constant=True)
    def persistentSession(self) -> bool:
        return self.tokens.persistent

    @Property(str, constant=True)
    def sessionStorage(self) -> str:
        return "系统凭据管理器" if self.tokens.persistent else "仅本次运行（内存）"

    # ---------- lifecycle ----------
    @Slot()
    def bootstrap(self) -> None:
        if self._demo:
            if not self._demo_guest:
                self._logged = True
                self._user = _demo_user()
            self._emit_auth()
            return
        stored = self.tokens.load()
        warn = base_url_warning(self.settings.apiBase)
        if warn:
            self.serverWarning.emit(warn)
        if not stored:
            self._emit_auth()
            return
        self._refresh = stored[0]
        self._start("refresh", "POST", "/auth/refresh", {"refresh_token": self._refresh}, None)

    @Slot()
    def shutdown(self) -> None:
        self._stop_lab()
        self.agent.stop()

    # ---------- generic API ----------
    @Slot(str, str, str, str)
    def api(self, action: str, method: str, path: str, body_json: str) -> None:
        if self._demo:
            QTimer.singleShot(80, lambda: self._demo_reply(action, method, path, body_json))
            return
        if not self.settings.apiBase:
            self.toast.emit("请先在设置中填写服务端地址", True)
            return
        try:
            body = json.loads(body_json) if body_json and body_json.strip() not in ("", "{}") else None
        except json.JSONDecodeError:
            self.toast.emit("请求参数不是合法 JSON", True)
            return
        idem = None
        if method.upper() in ("POST", "PATCH", "DELETE"):
            idem = uuid.uuid4().hex
        self._start(action, method, path, body, idem)

    def _start(self, action: str, method: str, path: str, body: Any, idem: str | None) -> None:
        warn = base_url_warning(self.settings.apiBase)
        if warn and "生产" in warn:
            self.serverWarning.emit(warn)
        self._set_busy(1)
        w = RequestWorker(self.settings.apiBase, self._access, self._session_id,
                          action, method, path, body, idem)
        w.signals.finished.connect(self._on_result)
        w.setAutoDelete(False)
        self._workers.append(w)
        self.pool.start(w)

    @Slot(str, bool, str, str, str, int)
    def _on_result(self, action: str, ok: bool, data_json: str, code: str, msg: str,
                   status: int) -> None:
        self._set_busy(-1)
        data: dict = {}
        if ok:
            try:
                data = json.loads(data_json)
            except json.JSONDecodeError:
                data = {}
        if ok and action in ("login", "refresh", "refresh_silent"):
            self._accept_tokens(data)
        elif action == "logout":
            self._clear_session(silent=ok)
        elif action == "me" and ok:
            self._user = data
            self.userJsonChanged.emit()
        elif action == "captcha" and ok:
            self.captchaReady.emit(str(data.get("captcha_id", "")),
                                   str(data.get("question", "")),
                                   int(data.get("expires_in", 600)))
        elif not ok and code in ("AUTH_REQUIRED", "AUTH_EMAIL_UNVERIFIED") and status == 401:
            self._clear_session(silent=True)
        elif not ok and action in ("refresh", "refresh_silent"):
            self._clear_session(silent=True)
        elif not ok and code == "NETWORK_ERROR":
            self.serverWarning.emit("网络不可达，请检查服务端地址")
        if ok and action in (
            "domain_create", "domain_verify", "domain_delete", "upstream_save",
            "tunnel_start", "realname_activate",
        ):
            # Control-plane deployments: the desktop agent must pull the new
            # hostname map / token. In standalone mode this is a no-op.
            QTimer.singleShot(700, self.agent.sync)
        self.apiResult.emit(action, ok, json.dumps(data, ensure_ascii=False) if ok else "", code, msg)
        self._reap_workers()

    def _reap_workers(self) -> None:
        # Workers are tiny; trim only completed entries occasionally.
        if len(self._workers) > 16:
            self._workers = self._workers[-8:]

    def _accept_tokens(self, data: dict) -> None:
        access = str(data.get("access_token", ""))
        refresh = str(data.get("refresh_token", ""))
        user = data.get("user") or {}
        if not access or not refresh:
            return
        self._access = access
        self._access_at = time.monotonic()
        self._refresh = refresh
        self._user = user
        self._logged = True
        self.tokens.save(refresh, str(user.get("email", "")))
        self.agent.set_session(self.settings.apiBase, self._access)
        self._emit_auth()
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _emit_auth(self) -> None:
        self.loggedInChanged.emit()
        self.userJsonChanged.emit()
        self.authChanged.emit(self._logged, json.dumps(self._user, ensure_ascii=False))

    def _clear_session(self, silent: bool = False) -> None:
        self._access = ""
        self._refresh = ""
        self._user = {}
        self._logged = False
        self._refresh_timer.stop()
        self.agent.clear_session()
        self.tokens.clear()
        self._emit_auth()
        if not silent:
            self.toast.emit("已退出登录", False)

    def _silent_refresh(self) -> None:
        if not self._logged or not self._refresh or self._demo:
            return
        if time.monotonic() - self._access_at < 7 * 60:
            return
        self._start("refresh_silent", "POST", "/auth/refresh", {"refresh_token": self._refresh}, None)

    @Slot()
    def logout(self) -> None:
        if self._demo:
            self._clear_session()
            return
        refresh = self._refresh
        if refresh:
            self._start("logout", "POST", "/auth/logout", {"refresh_token": refresh}, None)
        QTimer.singleShot(300, lambda: self._clear_session(silent=False))

    @Slot()
    def refreshMe(self) -> None:
        self.api("me", "GET", "/auth/me", "{}")

    # ---------- certificate upload ----------
    @Slot(int, str, str, str)
    def uploadCertificate(self, domain_id: int, cert_url: str, key_url: str, chain_url: str) -> None:
        if self._demo:
            QTimer.singleShot(120, lambda: self._demo_cert_upload(domain_id))
            return
        try:
            cert = _read_local(cert_url)
            key = _read_local(key_url)
            chain = _read_local(chain_url) if chain_url else None
        except OSError as exc:
            self.toast.emit(f"读取文件失败：{exc}", True)
            return
        if len(cert) > MAX_UPLOAD or len(key) > MAX_UPLOAD:
            self.toast.emit("证书或私钥文件过大", True)
            return
        self._set_busy(1)
        w = UploadWorker(self.settings.apiBase, self._access, self._session_id,
                         domain_id, cert, key, chain)
        w.signals.finished.connect(self._on_result)
        w.setAutoDelete(False)
        self._workers.append(w)
        self.pool.start(w)

    # ---------- local lab ----------
    @Slot(int)
    def startLab(self, port: int) -> None:
        ok, msg = port_available(port)
        if not ok:
            self.toast.emit(msg, True)
            self.labChanged.emit(bool(self.labRunning), int(port), msg)
            return
        self._stop_lab()
        try:
            self._lab = LocalLab(int(port))
            self._lab.start()
            self._lab_port = int(port)
            self.labRunningChanged.emit()
            self.labChanged.emit(True, int(port), f"http://127.0.0.1:{port}/health")
            self.toast.emit(f"本地实验服务已启动：127.0.0.1:{port}", False)
        except OSError as exc:
            self._lab = None
            self.labChanged.emit(False, int(port), str(exc))
            self.toast.emit(f"启动失败：{exc}", True)

    @Slot()
    def stopLab(self) -> None:
        self._stop_lab()
        self.labRunningChanged.emit()
        self.labChanged.emit(False, self._lab_port, "已停止")
        self.toast.emit("本地实验服务已停止", False)

    def _stop_lab(self) -> None:
        if self._lab:
            try:
                self._lab.stop()
            except Exception:  # noqa: BLE001
                pass
            self._lab = None

    @Slot(int)
    def applyFirewall(self, port: int) -> None:
        ok, msg = validate_port(port)
        if not ok:
            self.toast.emit(msg, True)
            return
        self.toast.emit("正在请求系统放行（会弹出 UAC）…", False)
        worker = _CallableWorker(lambda: add_firewall_rule(port), self._firewall_result)
        worker.signals.done.connect(self._firewall_result)
        self._workers.append(worker)
        self.pool.start(worker)

    def _firewall_result(self, result, error) -> None:  # noqa: ANN001
        if error:
            self.toast.emit(f"防火墙操作失败：{error}", True)
            return
        try:
            ok, msg = result
        except (TypeError, ValueError):
            self.toast.emit("防火墙操作返回异常", True)
            return
        self.toast.emit(str(msg), not ok)

    @Slot(int, result=str)
    def checkPort(self, port: int) -> str:
        ok, msg = port_available(port)
        return "" if ok else msg

    @Slot(result=int)
    def suggestPort(self) -> int:
        for p in range(8765, 8866):
            if port_available(p)[0]:
                return p
        return 8765

    # ---------- utilities ----------
    @Slot(str)
    def openUrl(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def copyText(self, text: str) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text)
        self.toast.emit("已复制到剪贴板", False)

    @Slot()
    def openLogDir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.crash.logDir()))

    @Slot()
    def makeCrashSample(self) -> None:
        path, text = self.crash.write(note="user requested sample log")
        self.crashLogReady.emit(str(path), text)
        self.toast.emit("示例日志已生成（已脱敏）", False)

    @Slot(result=str)
    def apiBaseWarning(self) -> str:
        return base_url_warning(self.settings.apiBase) or ""

    def _set_busy(self, delta: int) -> None:
        before = self._busy
        self._busy = max(0, self._busy + delta)
        if (before == 0) != (self._busy == 0):
            self.busyChanged.emit(self._busy > 0)

    # ---------- demo ----------
    def enable_demo(self) -> None:
        self._demo = True

    def demo_guest(self) -> None:
        self._demo = True
        self._demo_guest = True

    def _demo_reply(self, action: str, method: str, path: str, body_json: str) -> None:
        body = {}
        try:
            body = json.loads(body_json) if body_json else {}
        except json.JSONDecodeError:
            body = {}
        result: dict = {}
        if action == "captcha":
            result = {"captcha_id": "demo-captcha", "question": "7 + 9 = ?", "expires_in": 600}
            self.captchaReady.emit("demo-captcha", "7 + 9 = ?", 600)
        elif action in ("login", "refresh", "refresh_silent"):
            self._logged = True
            self._user = _demo_user()
            self._emit_auth()
            result = {"access_token": "demo", "refresh_token": "demo",
                      "expires_in": 900, "user": self._user}
        elif action == "logout":
            self._logged = False
            self._emit_auth()
            result = {"message": "已退出"}
        elif action == "domains":
            result = {"items": self._demo_domains}
        elif action == "tunnel_status":
            result = {"configured": True, "running": True, "tunnel_id": "demo-tunnel",
                      "active_connections": 12, "warn_connections": 800,
                      "max_connections": 1000, "warning": False, "domain_count": 3,
                      "last_error": "", "api_configured": True}
        elif action == "meta_public":
            result = {"platform_domain": "asnia.cc", "nameservers": ["ns1.liuli.example", "ns2.liuli.example"]}
        elif action == "domain_create":
            if body.get("prefix"):
                fqdn = str(body.get("prefix")).lower() + ".asnia.cc"
                new = _demo_domain(len(self._demo_domains) + 1, fqdn, "active", 1)
                new["kind"] = "platform"
                new["status"] = "active"
                new["stage"] = "active"
            else:
                fqdn = body.get("fqdn", "new.example")
                new = _demo_domain(len(self._demo_domains) + 1, fqdn, "ns_pending", 1)
                new["kind"] = "external"
                new["status"] = "ns_pending"
                new["stage"] = "ns_pending"
            self._demo_domains.insert(0, new)
            self._demo_records[new["id"]] = []
            self._demo_versions[new["id"]] = [1]
            result = new
        elif action == "domain_verify":
            did = _path_id(path)
            for d in self._demo_domains:
                if d["id"] == did:
                    d["status"] = "active"
                    d["stage"] = "active"
                    d["tunnel_status"] = "active"
                    d["verification"]["verified_at"] = "2026-11-20T10:00:00"
                    result = d
                    break
        elif action == "records":
            result = {"items": self._demo_records.get(_path_id(path), []),
                      "version": _demo_version(self._demo_domains, _path_id(path))}
        elif action == "records_batch":
            did = _path_id(path)
            items = []
            for i, r in enumerate(body.get("records", []), start=1):
                items.append({"id": i, "name": r.get("name", "@"), "type": r.get("type", "A"),
                              "ttl": int(r.get("ttl", 300)), "value": r.get("value", ""),
                              "priority": r.get("priority")})
            self._demo_records[did] = items
            for d in self._demo_domains:
                if d["id"] == did:
                    d["zone_version"] += 1
                    result = {"version": d["zone_version"], "items": items, "mode": body.get("mode")}
                    self._demo_versions.setdefault(did, []).insert(0, d["zone_version"])
                    break
        elif action == "revisions":
            did = _path_id(path)
            result = {"items": [{"version": v, "reason": "apply",
                                 "created_at": "2026-11-20T10:00:00", "record_count": 5}
                                for v in self._demo_versions.get(did, [1])]}
        elif action == "rollback":
            result = {"version": 1, "items": self._demo_records.get(_path_id(path), [])}
        elif action == "certs":
            result = {"items": self._demo_certs.get(_path_id(path), [])}
        elif action == "cert_upload":
            result = self._demo_certs_for(_path_id(path))[0]
        elif action == "cert_activate":
            result = {"status": "active"}
        elif action == "cert_delete":
            result = {"message": "deleted"}
        elif action == "expiring":
            result = {"items": [
                {"id": 1, "domain": "liuli.studio", "common_name": "liuli.studio",
                 "days_left": 42, "not_after": "2027-01-04T00:00:00", "status": "active"},
                {"id": 7, "domain": "lab.local", "common_name": "lab.local",
                 "days_left": 12, "not_after": "2026-12-05T00:00:00", "status": "active"},
            ]}
        elif action == "realname_status":
            result = {"status": "approved", "user_no": "U-2026-7K3M9Q",
                      "instructions": [
                          "1. 在本页复制“我的用户编号”：U-2026-7K3M9Q。",
                          "2. 用注册邮箱发送邮件到 2416444244@qq.com，主题写“实名审核 + 你的编号”。",
                          "3. 邮件附身份证正面和反面清晰照片，正文也写上用户编号。",
                          "4. 管理员人工审核 1～5 个工作日；通过后发放一次性激活码。",
                          "5. 激活码粘贴到本页上方输入框并点击“激活”，成功后可终身使用。",
                          "6. 身份证照片仅用于本次审核，审核完成后删除；数据库不保留证件原图，只保留状态、时间和必要脱敏记录。",
                          "7. 平台人工审核，非官方权威核验。",
                      ], "inbox": "2416444244@qq.com"}
        elif action == "tools_dns":
            result = {"name": "liuli.studio", "type": "A", "answers": ["203.0.113.10"], "count": 1}
        elif action == "tools_port":
            result = {"domain": "liuli.studio", "results": [
                {"address": "203.0.113.10", "port": 443, "reachable": True, "latency_ms": 38,
                 "error": None}]}
        elif action in ("realname_submit", "realname_activate"):
            result = {"status": "active", "message": "演示模式：实名已激活（终身有效）"}
        elif action == "me":
            result = self._user
        self.apiResult.emit(action, True, json.dumps(result, ensure_ascii=False), "", "")

    def _demo_cert_upload(self, domain_id: int) -> None:
        cert = self._demo_certs_for(domain_id)[0]
        self._demo_certs[domain_id] = [cert]
        self.apiResult.emit("cert_upload", True, json.dumps(cert, ensure_ascii=False), "", "")

    def _demo_certs_for(self, domain_id: int) -> list[dict]:
        return self._demo_certs.get(domain_id, [{
            "id": 11, "common_name": "liuli.studio", "sans": ["liuli.studio", "www.liuli.studio"],
            "serial": "7f3a9c", "fingerprint_sha256": "7A:31:0C:BB:93:2D:1F:88",
            "not_before": "2026-10-05T00:00:00", "not_after": "2027-01-04T00:00:00",
            "status": "active", "source": "upload", "created_at": "2026-10-06T08:00:00",
            "days_left": 42,
        }])


class _CallableWorker(QRunnable):
    """Run a blocking helper without freezing QML; deliver (result, error) via signal."""

    class Sig(QObject):
        done = Signal(object, object)

    def __init__(self, fn, callback) -> None:  # noqa: ANN001
        super().__init__()
        self.fn = fn
        self.callback = callback
        self.signals = _CallableWorker.Sig()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            result = self.fn()
            self.signals.done.emit(result, None)
        except Exception as exc:  # noqa: BLE001
            self.signals.done.emit(None, str(exc)[:200])


def _read_local(url_or_path: str) -> bytes:
    if not url_or_path:
        return b""
    path = QUrl(url_or_path).toLocalFile() if url_or_path.startswith("file:") else url_or_path
    return Path(path).read_bytes()


def _path_id(path: str) -> int:
    for part in path.split("/"):
        if part.isdigit():
            return int(part)
    return 0


def _demo_version(domains: list[dict], did: int) -> int:
    for d in domains:
        if d["id"] == did:
            return int(d["zone_version"])
    return 1


def _demo_user() -> dict:
    return {
        "id": 1024, "user_no": "U-2026-7K3M9Q", "email": "studio@liuli.dev",
        "email_verified": True, "realname_status": "approved",
        "realname_activated_at": None, "created_at": "2026-10-20T11:30:00",
    }


def _demo_domain(i: int, fqdn: str, status: str, version: int) -> dict:
    return {
        "id": i, "fqdn": fqdn, "status": status, "kind": "external",
        "stage": "active" if status == "active" else "ns_pending", "provider": "cloudflare",
        "ns_mode": "tunnel", "zone_version": version,
        "upstream_url": "http://127.0.0.1:8080",
        "ns_nameservers": ["ns1.liuli.example", "ns2.liuli.example"],
        "public_url": f"https://{fqdn}", "tunnel_status": "active" if status == "active" else "ns_pending",
        "verification": {
            "mode": "ns",
            "nameservers": ["ns1.liuli.example", "ns2.liuli.example"],
            "txt_name": f"_liuli-verify.{fqdn}",
            "txt_value": "6c1f8b2d4a7e9f03b5d8c1a4e7f0b3d6",
            "verified_at": "2026-11-02T08:20:00" if status == "active" else None,
        },
        "created_at": "2026-11-01T16:40:00",
    }


def _demo_domains() -> list[dict]:
    return [
        _demo_domain(1, "liuli.studio", "active", 4),
        _demo_domain(2, "glass.example", "pending", 1),
        _demo_domain(3, "lab.local", "active", 3),
    ]


def _demo_records() -> dict[int, list[dict]]:
    return {
        1: [
            {"id": 1, "name": "@", "type": "A", "ttl": 300, "value": "203.0.113.10", "priority": None},
            {"id": 2, "name": "www", "type": "CNAME", "ttl": 300, "value": "liuli.studio", "priority": None},
            {"id": 3, "name": "@", "type": "MX", "ttl": 300, "value": "mail.liuli.studio", "priority": 10},
            {"id": 4, "name": "@", "type": "TXT", "ttl": 300, "value": "v=spf1 -all", "priority": None},
            {"id": 5, "name": "docs", "type": "CNAME", "ttl": 300, "value": "pages.example.com", "priority": None},
        ],
        3: [
            {"id": 6, "name": "lab", "type": "A", "ttl": 120, "value": "127.0.0.1", "priority": None},
        ],
    }


def _demo_certs() -> dict[int, list[dict]]:
    return {
        1: [{
            "id": 11, "common_name": "liuli.studio",
            "sans": ["liuli.studio", "www.liuli.studio"], "serial": "7f3a9c",
            "fingerprint_sha256": "7A:31:0C:BB:93:2D:1F:88:5B:44:0E:9A:3C:71:D2:66",
            "not_before": "2026-10-05T00:00:00", "not_after": "2027-01-04T00:00:00",
            "status": "active", "source": "upload", "created_at": "2026-10-06T08:00:00",
            "days_left": 42,
        }, {
            "id": 12, "common_name": "liuli.studio", "sans": ["liuli.studio"],
            "serial": "55c1b2", "fingerprint_sha256": "22:9E:71:0A:BB:6D:14:F0",
            "not_before": "2026-07-01T00:00:00", "not_after": "2026-10-01T00:00:00",
            "status": "replaced", "source": "upload", "created_at": "2026-07-02T08:00:00",
            "days_left": 0,
        }],
    }
