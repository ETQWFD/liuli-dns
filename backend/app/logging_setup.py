"""Logging: JSON lines, request-id context, redaction filter."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_SECRET_PATTERNS = [
    (re.compile(r"(?i)(authorization:\s*bearer\s+)\S+"), r"\1***"),
    (re.compile(r"(?i)(password\"?\s*[:=]\s*\"?)[^\s,\"]+"), r"\1***"),
    (re.compile(r"(?i)(token\"?\s*[:=]\s*\"?)[^\s,\"]+"), r"\1***"),
    (re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----[\s\S]*?-----END[^-]*PRIVATE KEY-----"),
     "<private-key-redacted>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "<email>"),
    (re.compile(r"\b\d{17}[\dXx]\b"), "<id>"),
]


def redact(text: str) -> str:
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text[:2000]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "rid": request_id_ctx.get(),
            "msg": redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


log = logging.getLogger("liuli")


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
