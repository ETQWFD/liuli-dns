"""Loopback-only lab service for local DNS / port / certificate experiments."""

from __future__ import annotations

import json
import socket
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import dns.exception
    import dns.resolver
except Exception:  # noqa: BLE001
    dns = None
try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
except Exception:  # noqa: BLE001
    x509 = None


class LocalLab:
    def __init__(self, port: int) -> None:
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        if self._server is not None:
            return
        lab = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "LiuliLab/0.1"

            def log_message(self, fmt, *args):  # noqa: ANN001, D102
                pass

            def _json(self, status: int, payload: dict) -> None:
                raw = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                try:
                    if u.path == "/health":
                        return self._json(200, {"ok": True, "service": "liuli-local-lab", "port": lab.port})
                    if u.path == "/dns":
                        return self._json(200, _dns(q.get("name", ""), q.get("type", "A"),
                                                    q.get("server", "")))
                    if u.path == "/port":
                        return self._json(200, _port(q.get("host", ""), q.get("port", "0")))
                    if u.path == "/cert":
                        return self._json(200, _cert(q.get("path", "")))
                    if u.path == "/hosts":
                        dom = q.get("domain", "").strip()
                        ip = q.get("ip", "127.0.0.1").strip()
                        text = f"{ip}\t{dom}\n" if dom else ""
                        return self._json(200, {"ok": True, "text": text})
                    return self._json(404, {"ok": False, "error": "not found"})
                except Exception as exc:  # noqa: BLE001
                    return self._json(400, {"ok": False, "error": str(exc)[:200]})

        self._server = ThreadingHTTPServer(("127.0.0.1", int(self.port)), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None


def _dns(name: str, rtype: str, server: str) -> dict:
    if dns is None:
        return {"ok": False, "error": "dnspython 未安装"}
    if not name:
        return {"ok": False, "error": "缺少 name"}
    r = dns.resolver.Resolver(configure=False)
    if server:
        r.nameservers = [server]
    else:
        r.nameservers = ["1.1.1.1", "8.8.8.8"]
    r.timeout = 3.0
    r.lifetime = 4.0
    try:
        ans = r.resolve(name, rtype.upper(), lifetime=4.0)
        values = []
        for a in ans:
            values.append(str(a).rstrip("."))
        return {"ok": True, "name": name, "type": rtype.upper(), "answers": values}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}


def _port(host: str, port: str) -> dict:
    if not host or not port.isdigit():
        return {"ok": False, "error": "host/port 不合法"}
    started = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=3.0):
            reachable = True
            err = None
    except OSError as exc:
        reachable = False
        err = exc.strerror or "connection failed"
    return {"ok": True, "host": host, "port": int(port), "reachable": reachable,
            "latency_ms": int((time.monotonic() - started) * 1000), "error": err}


def _cert(path: str) -> dict:
    if x509 is None:
        return {"ok": False, "error": "cryptography 未安装"}
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": "文件不存在"}
    try:
        cert = x509.load_pem_x509_certificate(p.read_bytes())
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "不是有效的 PEM 证书"}
    cn = ""
    try:
        cn = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
    except IndexError:
        pass
    sans = []
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        sans = [str(n.value) for n in ext.value if isinstance(n, x509.DNSName)]
    except Exception:  # noqa: BLE001
        pass

    def iso(dt: datetime) -> str:
        return dt.astimezone(UTC).replace(tzinfo=None).isoformat() if dt.tzinfo else dt.isoformat()

    return {
        "ok": True, "common_name": str(cn), "sans": sans,
        "serial": format(cert.serial_number, "x"),
        "fingerprint": cert.fingerprint(hashes.SHA256()).hex().upper(),
        "not_before": iso(cert.not_valid_before_utc),
        "not_after": iso(cert.not_valid_after_utc),
        "days_left": max(0, (cert.not_valid_after_utc.replace(tzinfo=None) - datetime.now(UTC).replace(tzinfo=None)).days),
    }
