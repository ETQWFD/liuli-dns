"""Domain control verification (NS delegation or TXT) using real DNS queries."""

from __future__ import annotations

import logging

import dns.resolver
import dns.exception

from ..config import get_settings

log = logging.getLogger("liuli.verify")


def _resolver() -> dns.resolver.Resolver:
    r = dns.resolver.Resolver(configure=False)
    r.nameservers = get_settings().resolver_list
    r.lifetime = 4.0
    r.timeout = 4.0
    return r


def query(name: str, rtype: str) -> list[str]:
    try:
        answers = _resolver().resolve(name, rtype, lifetime=4.0)
        out: list[str] = []
        for a in answers:
            if rtype == "TXT":
                out.append(b"".join(a.strings).decode("utf-8", "replace"))
            elif rtype == "MX":
                out.append(f"{a.preference} {str(a.exchange).rstrip('.')}")
            else:
                out.append(str(a).rstrip("."))
        return out
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers,
            dns.exception.Timeout, dns.resolver.LifetimeTimeout):
        return []
    except Exception:  # noqa: BLE001 - never leak resolver internals to callers
        log.warning("dns query failed name=%s type=%s", name, rtype)
        return []


def check_control(fqdn: str, token: str, ns_hosts: list[str]) -> tuple[bool, str, dict]:
    got_ns = {n.lower().rstrip(".") for n in query(fqdn, "NS")}
    expected = {n.lower().rstrip(".") for n in ns_hosts}
    detail: dict = {"ns_found": sorted(got_ns), "ns_expected": sorted(expected)}
    if expected and expected.issubset(got_ns):
        return True, "ns", detail
    txt_name = f"_liuli-verify.{fqdn}"
    got_txt = query(txt_name, "TXT")
    detail["txt_name"] = txt_name
    if token in got_txt:
        return True, "txt", detail
    detail["txt_found"] = len(got_txt)
    return False, "none", detail


def check_a(fqdn: str) -> list[str]:
    return query(fqdn, "A") + query(fqdn, "AAAA")


def check_ns_switched(fqdn: str, expected: list[str]) -> tuple[bool, list[str]]:
    """Check delegated nameservers against Cloudflare's assigned pair.

    Cloudflare may report nameservers with different case/trailing dots. An
    empty answer is "still waiting", never "verified".
    """
    want = {n.strip().lower().rstrip(".") for n in expected if n and n.strip()}
    got = {n.strip().lower().rstrip(".") for n in query(fqdn, "NS")}
    return bool(want and got == want), sorted(got)
