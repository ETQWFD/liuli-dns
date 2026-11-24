"""Layered rate limiting: sliding-window counters, in-memory by default.

For multi-instance deployments set LIULI_REDIS_URL and use an external
gateway as well; this limiter mitigates abuse, it cannot stop DDoS/CC.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from .errors import AppError, E


class SlidingWindowLimiter:
    def __init__(self, max_keys: int = 200_000) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            cutoff = now - window_seconds
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry = int(window_seconds - (now - dq[0])) + 1
                return False, max(1, retry)
            dq.append(now)
            if len(self._hits) > self._max_keys:
                self._prune(now)
            return True, 0

    def _prune(self, now: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or now - v[-1] > 3600]
        for k in stale[: self._max_keys // 4]:
            self._hits.pop(k, None)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    from .config import get_settings

    s = get_settings()
    if s.trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(key: str, limit: int, window_seconds: int, message: str = "请求过于频繁，请稍后再试") -> None:
    allowed, retry = limiter.hit(key, limit, window_seconds)
    if not allowed:
        raise AppError(
            E["RATE_LIMITED"], message, status=429,
            details={"retry_after_seconds": retry},
            headers={"Retry-After": str(retry)},
        )


def enforce_ip(request: Request, bucket: str, limit: int, window_seconds: int) -> None:
    enforce(f"{bucket}:ip:{client_ip(request)}", limit, window_seconds)


def enforce_user(user_id: int, bucket: str, limit: int, window_seconds: int) -> None:
    enforce(f"{bucket}:user:{user_id}", limit, window_seconds)
