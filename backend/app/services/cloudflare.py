"""Cloudflare API adapter used by the server-side domain and Tunnel flows.

The API token is read from the environment only. Nothing in this module is
exposed to the desktop client, and errors never include the token.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger("liuli.cloudflare")


class CloudflareError(RuntimeError):
    def __init__(self, message: str, status: int = 502, code: str = "CLOUDFLARE_API_ERROR",
                 details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details


@dataclass
class CFZone:
    id: str
    name: str
    nameservers: list[str]


@dataclass
class CFTunnel:
    id: str
    name: str
    token: str


class CloudflareClient:
    def __init__(self, base_url: str | None = None, token: str | None = None,
                 account_id: str | None = None, timeout: float | None = None) -> None:
        s = get_settings()
        self.base_url = (base_url or s.cloudflare_api_base).rstrip("/")
        self.token = token if token is not None else s.cloudflare_api_token
        self.account_id = account_id if account_id is not None else s.cloudflare_account_id
        self.timeout = timeout or s.cloudflare_timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.token and self.account_id)

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise CloudflareError("域名暂不可用：服务端未配置 Cloudflare API Token",
                                  status=503, code="CLOUDFLARE_NOT_CONFIGURED")
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 body: dict | None = None) -> Any:
        if not self.configured:
            raise CloudflareError("域名暂不可用：服务端未配置 Cloudflare API",
                                  status=503, code="CLOUDFLARE_NOT_CONFIGURED")
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                r = client.request(method, url, headers=self._headers(), params=params, json=body)
        except httpx.HTTPError as exc:
            raise CloudflareError("域名暂不可用：Cloudflare API 网络不可达",
                                  status=502, code="CLOUDFLARE_API_ERROR",
                                  details={"reason": type(exc).__name__}) from exc
        try:
            payload = r.json()
        except ValueError as exc:
            raise CloudflareError("域名暂不可用：Cloudflare 返回了非 JSON 响应",
                                  status=502, code="CLOUDFLARE_API_ERROR",
                                  details={"http_status": r.status_code}) from exc
        if r.status_code >= 400 or payload.get("success") is False:
            errors = payload.get("errors") or []
            message = "; ".join(str(e.get("message") or e) for e in errors) if errors else "Cloudflare API 调用失败"
            raise CloudflareError(
                f"域名暂不可用：{message}",
                status=502,
                code="CLOUDFLARE_API_ERROR",
                details={"http_status": r.status_code, "errors": errors[:5]},
            )
        return payload.get("result")

    # ---- zones ----
    def find_zone(self, name: str) -> CFZone | None:
        rows = self._request("GET", "/zones", params={"name": name, "per_page": 50}) or []
        for row in rows:
            if str(row.get("name", "")).lower() == name.lower():
                return CFZone(
                    id=str(row["id"]), name=str(row.get("name") or name),
                    nameservers=list(row.get("name_servers") or []),
                )
        return None

    def ensure_zone(self, name: str, *, platform: bool = False,
                    platform_zone_id: str = "") -> CFZone:
        if platform and platform_zone_id:
            detail = self._request("GET", f"/zones/{platform_zone_id}") or {}
            return CFZone(
                id=platform_zone_id, name=str(detail.get("name") or name),
                nameservers=list(detail.get("name_servers") or []),
            )
        zone = self.find_zone(name)
        if zone is not None:
            return zone
        if platform:
            raise CloudflareError("域名暂不可用：平台自有域名尚未绑定 Cloudflare Zone",
                                  status=503, code="CLOUDFLARE_NOT_CONFIGURED")
        result = self._request("POST", "/zones", body={
            "name": name,
            "type": "full",
            "jump_start": False,
            "account": {"id": self.account_id},
        }) or {}
        if not result.get("id"):
            raise CloudflareError("域名暂不可用：Cloudflare 未能创建 DNS Zone")
        return CFZone(
            id=str(result["id"]), name=str(result.get("name") or name),
            nameservers=list(result.get("name_servers") or []),
        )

    # ---- tunnels ----
    def create_tunnel(self, name: str) -> CFTunnel:
        result = self._request("POST", f"/accounts/{self.account_id}/cfd_tunnel", body={
            "name": name[:100],
            "config_src": "cloudflare",
        }) or {}
        tunnel_id = str(result.get("id") or result.get("tunnel_id") or "")
        if not tunnel_id:
            raise CloudflareError("域名暂不可用：Cloudflare 未能创建 Tunnel")
        token = str(result.get("token") or "")
        if not token:
            token = self.get_tunnel_token(tunnel_id)
        if not token:
            raise CloudflareError("域名暂不可用：Cloudflare Tunnel 未返回运行令牌")
        return CFTunnel(id=tunnel_id, name=name, token=token)

    def get_tunnel_token(self, tunnel_id: str) -> str:
        result = self._request("GET", f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/token")
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return str(result.get("token") or result.get("value") or "")
        return ""

    def delete_tunnel(self, tunnel_id: str) -> None:
        try:
            self._request("DELETE", f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}")
        except CloudflareError:
            log.warning("tunnel cleanup failed tunnel_id=%s", tunnel_id)

    def configure_ingress(self, tunnel_id: str, hostnames: list[str], proxy_port: int) -> None:
        ingress: list[dict[str, str]] = []
        for hostname in sorted({h.strip().lower() for h in hostnames if h.strip()}):
            ingress.append({
                "hostname": hostname,
                "service": f"http://127.0.0.1:{proxy_port}",
            })
        ingress.append({"service": "http_status:404"})
        self._request(
            "PUT",
            f"/accounts/{self.account_id}/cfd_tunnel/{tunnel_id}/configurations",
            body={"config": {"ingress": ingress}},
        )

    # ---- DNS records ----
    def ensure_cname(self, zone_id: str, fqdn: str, tunnel_id: str) -> str:
        target = f"{tunnel_id}.cfargotunnel.com"
        rows = self._request(
            "GET", f"/zones/{zone_id}/dns_records",
            params={"name": fqdn, "type": "CNAME", "per_page": 50},
        ) or []
        record_id = ""
        for row in rows:
            if str(row.get("name", "")).lower() == fqdn.lower():
                record_id = str(row.get("id") or "")
                if str(row.get("content") or "") != target or not row.get("proxied"):
                    self._request("PATCH", f"/zones/{zone_id}/dns_records/{record_id}", body={
                        "content": target, "proxied": True, "ttl": 1,
                    })
                return record_id
        result = self._request("POST", f"/zones/{zone_id}/dns_records", body={
            "type": "CNAME",
            "name": fqdn,
            "content": target,
            "proxied": True,
            "ttl": 1,
            "comment": "LiuliDNS Tunnel",
        }) or {}
        rid = str(result.get("id") or "")
        if not rid:
            raise CloudflareError("域名暂不可用：Cloudflare 未能创建 CNAME")
        return rid

    def delete_dns_record(self, zone_id: str, record_id: str) -> None:
        if zone_id and record_id:
            try:
                self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
            except CloudflareError:
                log.warning("dns cleanup failed zone=%s record=%s", zone_id, record_id)


def get_cloudflare() -> CloudflareClient:
    """Factory used by routers; tests replace this with a fake implementation."""
    return CloudflareClient()
