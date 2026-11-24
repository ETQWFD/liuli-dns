"""Self-hosted arithmetic CAPTCHA: server-side answer, one-time, short TTL.

No third-party service. The client receives only a question and an opaque id;
the answer never leaves the server. Verification consumes the challenge even
on failure, so a challenge cannot be brute-forced by retrying.
"""

from __future__ import annotations

import secrets
import threading
import time

from .security import constant_time_eq


class CaptchaStore:
    def __init__(self, ttl_seconds: int = 600, max_entries: int = 50_000) -> None:
        self._items: dict[str, tuple[str, str | None, float]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max_entries

    def issue(self, session_id: str | None = None) -> dict:
        a = secrets.randbelow(18) + 2
        b = secrets.randbelow(18) + 2
        mode = secrets.randbelow(3)
        if mode == 0:
            question, answer = f"{a} + {b} = ?", str(a + b)
        elif mode == 1:
            hi, lo = max(a, b), min(a, b)
            question, answer = f"{hi} - {lo} = ?", str(hi - lo)
        else:
            a, b = secrets.randbelow(8) + 2, secrets.randbelow(8) + 2
            question, answer = f"{a} x {b} = ?", str(a * b)
        cid = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            self._items[cid] = (answer, session_id, now + self._ttl)
        return {"captcha_id": cid, "question": question, "expires_in": self._ttl}

    def verify(self, captcha_id: str, answer: str, session_id: str | None = None) -> bool:
        if not captcha_id:
            return False
        now = time.monotonic()
        with self._lock:
            item = self._items.pop(captcha_id, None)  # one-time regardless of outcome
        if not item:
            return False
        expected, bound_session, expires = item
        if now > expires:
            return False
        if bound_session and bound_session != (session_id or ""):
            return False
        return constant_time_eq(expected, (answer or "").strip())

    def _prune(self, now: float) -> None:
        if len(self._items) < self._max:
            return
        expired = [k for k, v in self._items.items() if v[2] <= now]
        for k in expired[: self._max // 2]:
            self._items.pop(k, None)
        if len(self._items) >= self._max:
            for k in list(self._items.keys())[: self._max // 4]:
                self._items.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


captcha_store = CaptchaStore()
