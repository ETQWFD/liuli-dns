"""Crash reporting: redacted local logs + clipboard hand-off.

Never records passwords, bearer tokens, refresh tokens, private keys, cookies
or identity numbers. Emails are masked as well. The full log stays local and is
only copied when the user explicitly clicks the button.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import platform
import re
import sys
import threading
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Signal, Slot

APP_VERSION = "0.2.0"
MAX_LOG_LINES = 240

_PATTERNS = [
    (re.compile(r"(?i)(authorization:\s*bearer\s+)\S+"), r"\1***"),
    (re.compile(r"(?i)(refresh[_-]?token\"?\s*[:=]\s*\"?)[^\s,\"]+"), r"\1***"),
    (re.compile(r"(?i)(access[_-]?token\"?\s*[:=]\s*\"?)[^\s,\"]+"), r"\1***"),
    (re.compile(r"(?i)(password\"?\s*[:=]\s*\"?)[^\s,\"]+"), r"\1***"),
    (re.compile(r"(?i)(token\"?\s*[:=]\s*\"?)[^\s,\"]+"), r"\1***"),
    (re.compile(r"(?i)(cookie\"?\s*[:=]\s*\"?)[^\s,\"]+"), r"\1***"),
    (re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----[\s\S]*?-----END[^-]*PRIVATE KEY-----"),
     "<private-key-redacted>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "<email>"),
    (re.compile(r"\b\d{17}[\dXx]\b"), "<id-number>"),
    (re.compile(r"\b\d{15}\b"), "<id-number>"),
    (re.compile(r"(\b\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class _RingBuffer(logging.Handler):
    def __init__(self, capacity: int = MAX_LOG_LINES) -> None:
        super().__init__()
        self.lines: list[str] = []
        self.capacity = capacity
        self._lock2 = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock2:
                self.lines.append(redact(msg))
                if len(self.lines) > self.capacity:
                    self.lines = self.lines[-self.capacity :]
        except Exception:  # noqa: BLE001
            pass


class CrashManager(QObject):
    crashReported = Signal(str, str)  # path, redacted text
    logWritten = Signal(str, str)

    def __init__(self, parent=None):  # noqa: ANN001
        super().__init__(parent)
        base = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
        self.dir = Path(base or Path.home() / ".liuli-dns") / "logs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ring = _RingBuffer()
        self.ring.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        self._file_handler: RotatingFileHandler | None = None
        self._installed = False

    def setup_logging(self) -> logging.Logger:
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        if self._file_handler is None:
            self._file_handler = RotatingFileHandler(
                self.dir / "app.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            self._file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
        root.addHandler(self._file_handler)
        root.addHandler(self.ring)
        return logging.getLogger("liuli.client")

    def install(self) -> None:
        if self._installed:
            return
        self._installed = True
        sys.excepthook = self._hook
        threading.excepthook = self._thread_hook
        try:
            fh = open(self.dir / "faulthandler.log", "a", buffering=1, encoding="utf-8")  # noqa: SIM115
            faulthandler.enable(file=fh, all_threads=True)
        except Exception:  # noqa: BLE001
            pass

    def _hook(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        path, text = self.write(exc_type, exc, tb)
        try:
            self.crashReported.emit(str(path), text)
        except Exception:  # noqa: BLE001
            pass
        print(redact("".join(traceback.format_exception(exc_type, exc, tb))), file=sys.stderr)

    def _thread_hook(self, args) -> None:  # noqa: ANN001
        self._hook(args.exc_type, args.exc_value, args.exc_traceback)

    def write(self, exc_type=None, exc=None, tb=None, note: str = "") -> tuple[Path, str]:  # noqa: ANN001
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.dir / f"crash-{ts}.log"
        header = [
            "LiuliDNS crash report (redacted)",
            f"time: {datetime.now().isoformat()}",
            f"version: {APP_VERSION}",
            f"os: {platform.platform()}",
            f"python: {sys.version.split()[0]}",
            f"note: {note}",
            "-" * 60,
        ]
        body = note + "\n"
        if exc_type is not None:
            body = "".join(traceback.format_exception(exc_type, exc, tb))
        recent = "\n".join(self.ring.lines[-MAX_LOG_LINES:])
        text = redact("\n".join(header) + "\n" + body + "\n" + "-" * 60 + "\nRECENT LOG\n" + recent + "\n")
        path.write_text(text, encoding="utf-8")
        return path, text

    @Slot(str, result=str)
    def writeSample(self, note: str) -> str:
        path, text = self.write(note=note or "sample")
        self.logWritten.emit(str(path), text)
        return text

    @Slot(result=str)
    def logDir(self) -> str:
        return str(self.dir)

    @Slot(result=str)
    def latest(self) -> str:
        files = sorted(self.dir.glob("crash-*.log"), key=os.path.getmtime, reverse=True)
        if not files:
            return ""
        try:
            return files[0].read_text(encoding="utf-8")
        except OSError:
            return ""
