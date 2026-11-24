"""Runtime configuration. All secrets come from environment variables.

No secret has a usable production default: `validate_runtime()` refuses to boot
in production when a required key is missing. In dev/test, ephemeral keys are
generated so the stack can run locally, with a clear warning.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("liuli.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="LIULI_", extra="ignore", case_sensitive=False
    )

    app_env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "LiuliDNS"
    app_version: str = "0.2.2"
    api_prefix: str = "/api/v1"
    # Standalone desktop mode: the client starts this API locally. It keeps
    # mail optional for a one-person install, but it MUST NOT bypass real-name
    # review or activation. Public servers never enable this implicitly.
    local_mode: bool = False
    # "standalone": one machine runs API + cloudflared.
    # "control": central account/admin/DNS control plane; each desktop runs
    #            its own Go tunnel agent with the token issued here.
    server_role: Literal["standalone", "control"] = "standalone"
    auto_verify_email: bool = False
    agent_stale_seconds: int = 120
    # Platform-owned apex used for free second-level names. This is a public
    # identifier, not a secret. The matching zone must exist in Cloudflare.
    platform_domain: str = "asnia.cc"
    platform_zone_id: str = ""
    # Cloudflare API credentials live only in server-side environment variables.
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    cloudflare_api_base: str = "https://api.cloudflare.com/client/v4"
    cloudflare_timeout_seconds: float = 20.0
    # One Tunnel per user; one Go supervisor + one cloudflared process for all
    # of that user's hostnames. The Go reverse proxy applies the soft limit.
    tunnel_per_user_domains: int = 5
    tunnel_proxy_port: int = 8787
    tunnel_control_port: int = 8788
    tunnel_warn_connections: int = 800
    tunnel_max_connections: int = 1000
    tunnel_binary: str = ""
    cloudflared_binary: str = ""
    tunnel_state_dir: str = ""
    # Optional free-domain provider. Hidden from the client UI by design.
    dnshe_api_base: str = "https://api005.dnshe.com/index.php"
    dnshe_api_key: str = ""
    dnshe_api_secret: str = ""
    free_domain_provider: str = "dnshe"

    database_url: str = "sqlite:///./data/liuli.db"
    sql_echo: bool = False

    # --- secrets (env only) ---
    secret_key: str = ""          # JWT / cookie signing, >=32 bytes
    cert_master_key: str = ""     # base64 of exactly 32 random bytes
    code_pepper: str = ""         # HMAC pepper for activation codes
    doc_pepper: str = ""          # HMAC pepper for realname document numbers

    access_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 30 * 24 * 3600
    email_token_ttl_seconds: int = 24 * 3600

    # --- public identity ---
    ns_hostnames: str = "ns1.liuli.example,ns2.liuli.example"
    public_base_url: str = "https://api.liuli.example"
    dns_resolvers: str = "8.8.8.8,1.1.1.1"
    dns_host: str = "0.0.0.0"
    dns_port: int = 53

    # --- mail ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@liuli.example"
    smtp_starttls: bool = True
    realname_inbox: str = "2416444244@qq.com"
    mail_outbox_dir: str = "./data/outbox"

    # --- admin (separate from user accounts) ---
    admin_email: str = "2416444244@qq.com"
    admin_public_url: str = "http://127.0.0.1:8000/admin"
    admin_password_hash: str = ""  # argon2id string generated offline
    admin_totp_secret: str = ""    # base32
    admin_session_ttl_seconds: int = 8 * 3600

    # --- limits ---
    global_ip_per_minute: int = 600
    global_instance_per_minute: int = 5000
    dns_qps_per_ip: int = 50
    dns_qps_global: int = 2000

    # --- ops ---
    trust_proxy_headers: bool = False
    redis_url: str = ""
    maintenance_interval_seconds: int = 900

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def tunnel_configured(self) -> bool:
        return bool(self.cloudflare_api_token and self.cloudflare_account_id)

    @property
    def platform_tunnel_configured(self) -> bool:
        return bool(self.tunnel_configured and self.platform_zone_id)

    @property
    def nameserver_list(self) -> list[str]:
        return [n.strip().lower().rstrip(".") for n in self.ns_hostnames.split(",") if n.strip()]

    @property
    def resolver_list(self) -> list[str]:
        return [r.strip() for r in self.dns_resolvers.split(",") if r.strip()]

    def validate_runtime(self) -> None:
        """Fail closed in production; generate ephemeral keys in dev/test."""
        missing = [
            name
            for name in ("secret_key", "cert_master_key", "code_pepper", "doc_pepper")
            if not getattr(self, name)
        ]
        if self.is_prod and missing:
            raise RuntimeError(
                "Missing required secrets in production: " + ", ".join(missing).upper()
            )
        for name in missing:
            # dev/test only: ephemeral, not persisted, rotated each process start.
            setattr(self, name, base64.urlsafe_b64encode(os.urandom(32)).decode())
            log.warning("LIULI_%s not set; generated an ephemeral dev key", name.upper())
        if self.is_prod:
            try:
                key = base64.urlsafe_b64decode(self.cert_master_key)
            except Exception as exc:  # pragma: no cover - config guard
                raise RuntimeError("CERT_MASTER_KEY must be base64url of 32 bytes") from exc
            if len(key) != 32:
                raise RuntimeError("CERT_MASTER_KEY must decode to exactly 32 bytes")
        if not self.admin_password_hash:
            log.warning("Admin console disabled until LIULI_ADMIN_PASSWORD_HASH is configured")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.validate_runtime()
    return s


def reset_settings_cache() -> None:
    get_settings.cache_clear()
