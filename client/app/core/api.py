"""HTTP client for the LiuliDNS API. No credentials are hard-coded here."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import httpx


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 0, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def base_url_warning(base: str) -> str | None:
    try:
        parts = urlsplit(base)
    except ValueError:
        return "服务端地址不合法"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "服务端地址必须是 http(s) URL"
    if parts.scheme == "http" and parts.hostname not in ("127.0.0.1", "localhost", "::1"):
        return "当前使用 HTTP 明文连接；生产环境请改用 HTTPS"
    return None


class ApiClient:
    def __init__(self, base: str, access_token: str | None = None,
                 session_id: str | None = None) -> None:
        self.base = (base or "").rstrip("/")
        self.access_token = access_token
        self.session_id = session_id

    def _headers(self, idem_key: str | None) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "LiuliDNS-Desktop/0.1"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.session_id:
            headers["X-Session-Id"] = self.session_id
        if idem_key:
            headers["X-Idempotency-Key"] = idem_key
        return headers

    def request(self, method: str, path: str, body: Any = None,
                idem_key: str | None = None, timeout: float = 20.0) -> Any:
        if not self.base:
            raise ApiError("CLIENT_NO_SERVER", "请先在设置中填写服务端地址", 0)
        url = f"{self.base}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as c:
                resp = c.request(method.upper(), url, json=body, headers=self._headers(idem_key))
        except httpx.TimeoutException as exc:
            raise ApiError("NETWORK_TIMEOUT", "连接服务端超时", 0) from exc
        except httpx.HTTPError as exc:
            raise ApiError("NETWORK_ERROR", "网络不可达，请检查服务端地址", 0) from exc
        return self._parse(resp)

    def upload(self, path: str, files: dict[str, tuple[str, bytes, str]],
               data: dict[str, str] | None = None, timeout: float = 30.0) -> Any:
        url = f"{self.base}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as c:
                resp = c.post(url, files=files, data=data or {}, headers=self._headers(None))
        except httpx.HTTPError as exc:
            raise ApiError("NETWORK_ERROR", "网络不可达，请检查服务端地址", 0) from exc
        return self._parse(resp)

    @staticmethod
    def _parse(resp: httpx.Response) -> Any:
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            raise ApiError("SERVER_ERROR", f"服务端返回了非 JSON 响应（HTTP {resp.status_code}）",
                           resp.status_code)
        if not payload.get("ok", False):
            err = payload.get("error") or {}
            raise ApiError(
                str(err.get("code", "INTERNAL")),
                str(err.get("message", "操作失败")),
                resp.status_code,
                err.get("details"),
            )
        return payload.get("data")

    def get_version(self) -> Any:
        return self.request("GET", "/meta/version", timeout=8.0)
