"""Optional free-domain adapter. Third-party names stay out of the client UI.

DNSHE is the preferred provider. Its API is documented at the upstream
project. Credentials come from the server environment only. The adapter never
pretends that NS delegation succeeded: if the provider rejects NS writes or the
public NS check later fails, the caller must show "该前缀暂不可用".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from ..config import get_settings

log = logging.getLogger("liuli.freedomain")


class FreeDomainError(RuntimeError):
    def __init__(self, message: str, *, status: int = 502,
                 code: str = "FREE_DOMAIN_UNAVAILABLE") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


@dataclass
class FreeDomain:
    fqdn: str
    provider_domain_id: int
    nameservers: list[str]


class DNSHEProvider:
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 api_secret: str | None = None, timeout: float = 20.0) -> None:
        s = get_settings()
        self.base_url = base_url or s.dnshe_api_base
        self.api_key = api_key if api_key is not None else s.dnshe_api_key
        self.api_secret = api_secret if api_secret is not None else s.dnshe_api_secret
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _request(self, method: str, endpoint: str, action: str | None = None,
                 *, params: dict | None = None, body: dict | None = None) -> dict:
        if not self.configured:
            raise FreeDomainError("该前缀暂不可用：免费域名服务未配置", code="FREE_DOMAIN_UNAVAILABLE")
        query = {"m": "domain_hub", "endpoint": endpoint}
        if action:
            query["action"] = action
        if params:
            query.update(params)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                r = client.request(
                    method,
                    self.base_url,
                    params=query,
                    headers={"X-API-Key": self.api_key, "X-API-Secret": self.api_secret},
                    json=body if method != "GET" else None,
                )
        except httpx.HTTPError as exc:
            raise FreeDomainError("该前缀暂不可用：免费域名服务网络不可达") from exc
        try:
            payload = r.json()
        except ValueError as exc:
            raise FreeDomainError("该前缀暂不可用：免费域名服务返回异常") from exc
        if r.status_code >= 400 or payload.get("success") is False:
            message = payload.get("message") or payload.get("error") or "请求被拒绝"
            raise FreeDomainError(f"该前缀暂不可用：{message}")
        return payload

    def register(self, prefix: str, suffix: str) -> dict:
        return self._request("POST", "subdomains", "create",
                             body={"subdomain": prefix, "domain": suffix})

    def set_nameservers(self, provider_domain_id: int, nameservers: list[str]) -> None:
        # DNSHE's record API supports NS records. Whether the account/root
        # permits delegation is a provider-side decision; a rejection is
        # surfaced as FREE_DOMAIN_UNAVAILABLE rather than faked.
        for ns in nameservers:
            self._request("POST", "dns_records", "create", body={
                "subdomain_id": provider_domain_id,
                "type": "NS",
                "name": "@",
                "content": ns.rstrip("."),
                "ttl": 600,
            })

    def delete(self, provider_domain_id: int) -> None:
        try:
            self._request("POST", "subdomains", "delete",
                          body={"subdomain_id": provider_domain_id})
        except FreeDomainError:
            log.warning("free domain cleanup failed id=%s", provider_domain_id)


class DigitalPlatProvider:
    """Placeholder for the fallback provider.

    There is no public write API for NS delegation in the upstream project
    that this build can call safely without account-specific credentials.
    Returning a hard failure is intentional: the UI must never show a fake
    domain when the provider cannot set NS.
    """

    configured = False

    def register(self, prefix: str, suffix: str) -> dict:
        raise FreeDomainError("该前缀暂不可用：备选免费域名平台当前不支持自动修改 NS")


def get_free_provider():
    s = get_settings()
    if s.free_domain_provider == "dnshe":
        return DNSHEProvider()
    return DigitalPlatProvider()
