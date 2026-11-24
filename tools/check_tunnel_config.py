#!/usr/bin/env python3
"""Offline/local-only validator for LiuliDNS tunnel configuration.

This script NEVER contacts Cloudflare or a public hostname. It checks the
generated files, loopback ports and optional local control/proxy endpoints.
Public tunnel verification is a manual developer step by design.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


def fail(errors: list[str], msg: str) -> None:
    errors.append(msg)


def check_config(path: Path) -> tuple[dict, list[str]]:
    errors: list[str] = []
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [f"cannot read JSON: {exc}"]
    for key in ("cloudflared", "token_file", "proxy_listen", "control_listen", "domains_file", "state_dir"):
        if not cfg.get(key):
            fail(errors, f"missing {key}")
    cf = Path(str(cfg.get("cloudflared", ""))).expanduser()
    if not cf.is_file():
        fail(errors, f"cloudflared binary not found: {cf}")
    token = Path(str(cfg.get("token_file", ""))).expanduser()
    if not token.is_file():
        fail(errors, f"token file not found: {token}")
    elif os.name != "nt":
        mode = token.stat().st_mode & 0o777
        if mode & 0o077:
            fail(errors, f"token file permissions are too open: {oct(mode)} (expected 0600)")
    for key in ("proxy_listen", "control_listen"):
        host, _, port = str(cfg.get(key, "")).rpartition(":")
        if host not in ("127.0.0.1", "localhost", "[::1]", "::1"):
            fail(errors, f"{key} must bind loopback, got {cfg.get(key)}")
        if not port.isdigit() or not (1024 <= int(port) <= 65535):
            fail(errors, f"{key} has invalid port")
    domains_file = Path(str(cfg.get("domains_file", ""))).expanduser()
    if not domains_file.is_file():
        fail(errors, f"domains file not found: {domains_file}")
    else:
        try:
            domains = json.loads(domains_file.read_text(encoding="utf-8")).get("domains", [])
        except Exception as exc:
            fail(errors, f"domains JSON invalid: {exc}")
            domains = []
        if len(domains) > 5:
            fail(errors, f"more than 5 domains: {len(domains)}")
        for item in domains:
            host = str(item.get("hostname", "")).lower().rstrip(".")
            if not HOST_RE.match(host):
                fail(errors, f"invalid hostname: {host!r}")
            upstream = str(item.get("upstream", ""))
            u = urlsplit(upstream)
            if u.scheme not in ("http", "https") or u.hostname not in ("127.0.0.1", "localhost", "::1"):
                fail(errors, f"upstream must be loopback http(s): {upstream!r}")
            if u.username or u.password:
                fail(errors, f"upstream must not contain credentials: {host}")
    return cfg, errors


def local_probe(cfg: dict, domain: str | None) -> list[str]:
    """Only loopback requests. No public DNS/Tunnel traffic."""
    errors: list[str] = []
    host, _, port = str(cfg["control_listen"]).rpartition(":")
    try:
        c = http.client.HTTPConnection(host, int(port), timeout=2)
        c.request("GET", "/health")
        r = c.getresponse()
        body = r.read().decode("utf-8", "replace")
        if r.status != 200 or '"ok":true' not in body:
            errors.append(f"control /health failed: HTTP {r.status} {body[:80]}")
        c.close()
    except Exception as exc:
        errors.append(f"control endpoint unreachable: {exc}")
    if domain:
        host, _, port = str(cfg["proxy_listen"]).rpartition(":")
        try:
            c = http.client.HTTPConnection(host, int(port), timeout=3)
            c.request("GET", "/", headers={"Host": domain})
            r = c.getresponse()
            body = r.read(128).decode("utf-8", "replace")
            if r.status == 404:
                errors.append("proxy returned 404: hostname is not mapped")
            elif r.status >= 500:
                errors.append(f"proxy/origin returned HTTP {r.status}: {body}")
            c.close()
        except Exception as exc:
            errors.append(f"proxy endpoint unreachable: {exc}")
    return errors


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=os.path.expanduser("~/.local/share/liuli-dns/server/tunnel/tunnel.json"))
    p.add_argument("--domain", default="", help="optional mapped hostname for a loopback-only proxy probe")
    p.add_argument("--probe", action="store_true", help="also probe 127.0.0.1 control/proxy ports")
    args = p.parse_args()
    cfg, errors = check_config(Path(args.config).expanduser())
    if cfg and args.probe:
        errors += local_probe(cfg, args.domain.strip().lower() or None)
    result = {
        "ok": not errors,
        "scope": "local-only; no Cloudflare or public hostname contacted",
        "errors": errors,
        "public_test": "manual developer step; not executed by the AI",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
