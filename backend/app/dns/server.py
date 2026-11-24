"""Authoritative DNS server (UDP + TCP). Non-recursive, rate-limited, no ANY.

Run:  python -m app.dns.server --host 0.0.0.0 --port 53
Dev:  python -m app.dns.server --host 127.0.0.1 --port 5353
"""

from __future__ import annotations

import argparse
import logging
import socket
import threading
import time
from collections import defaultdict
from typing import Any

import dnslib
from dnslib import DNSLabel, DNSRecord, RCODE, RR
from dnslib.server import DNSHandler, DNSServer
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..db import get_engine, get_sessionmaker
from ..models import Domain

log = logging.getLogger("liuli.dns")


class ZoneStore:
    """In-memory zone snapshots, refreshed every N seconds or on demand."""

    def __init__(self, refresh_seconds: int = 15, ns_hosts: list[str] | None = None) -> None:
        self.refresh_seconds = refresh_seconds
        self.ns_hosts = ns_hosts or get_settings().nameserver_list
        self._zones: dict[str, dict[str, Any]] = {}
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def maybe_refresh(self) -> None:
        if time.monotonic() - self._loaded_at >= self.refresh_seconds:
            self.refresh()

    def refresh(self) -> None:
        with self._lock:
            try:
                factory = get_sessionmaker()
                with factory() as db:
                    domains = db.scalars(
                        select(Domain)
                        .where(Domain.status == "active")
                        .options(selectinload(Domain.records))
                    ).all()
                    zones: dict[str, dict[str, Any]] = {}
                    for d in domains:
                        zones[d.fqdn] = {
                            "version": d.zone_version,
                            "records": [
                                {
                                    "name": r.name, "type": r.type, "ttl": r.ttl,
                                    "value": r.value, "priority": r.priority or 0,
                                }
                                for r in d.records if r.deleted_at is None
                            ],
                        }
                    self._zones = zones
                    self._loaded_at = time.monotonic()
            except Exception:  # noqa: BLE001 - keep serving last good snapshot
                log.exception("zone refresh failed; serving previous snapshot")

    def find(self, qname: str) -> tuple[str, str, dict[str, Any]] | None:
        labels = qname.split(".")
        for i in range(len(labels) - 1):
            candidate = ".".join(labels[i:])
            zone = self._zones.get(candidate)
            if zone:
                rel = ".".join(labels[:i]) or "@"
                return candidate, rel, zone
        return None


class DNSRateLimiter:
    def __init__(self, per_ip: int, global_qps: int) -> None:
        self.per_ip = per_ip
        self.global_qps = global_qps
        self._second = int(time.monotonic())
        self._by_ip: dict[str, int] = defaultdict(int)
        self._global = 0
        self._lock = threading.Lock()

    def allow(self, ip: str) -> bool:
        now = int(time.monotonic())
        with self._lock:
            if now != self._second:
                self._second = now
                self._by_ip.clear()
                self._global = 0
            if self._global >= self.global_qps:
                return False
            if self._by_ip[ip] >= self.per_ip:
                return False
            self._by_ip[ip] += 1
            self._global += 1
            return True


def _label(name: str, zone: str) -> DNSLabel:
    return DNSLabel(zone if name == "@" else f"{name}.{zone}")


def _txt_chunks(text: str) -> list[bytes]:
    return [text[i : i + 255].encode("utf-8") for i in range(0, len(text), 255)] or [b""]


def rr_from(record: dict[str, Any], zone: str) -> RR | None:
    qname = _label(record["name"], zone)
    ttl = int(record["ttl"])
    rtype = record["type"]
    val = record["value"]
    try:
        if rtype == "A":
            return RR(qname, dnslib.QTYPE.A, ttl=ttl, rdata=dnslib.A(val))
        if rtype == "AAAA":
            return RR(qname, dnslib.QTYPE.AAAA, ttl=ttl, rdata=dnslib.AAAA(val))
        if rtype == "CNAME":
            return RR(qname, dnslib.QTYPE.CNAME, ttl=ttl, rdata=dnslib.CNAME(val))
        if rtype == "TXT":
            return RR(qname, dnslib.QTYPE.TXT, ttl=ttl, rdata=dnslib.TXT(_txt_chunks(val)))
        if rtype == "MX":
            return RR(qname, dnslib.QTYPE.MX, ttl=ttl,
                      rdata=dnslib.MX(label=val, preference=int(record["priority"] or 10)))
        if rtype == "NS":
            return RR(qname, dnslib.QTYPE.NS, ttl=ttl, rdata=dnslib.NS(val))
        if rtype == "SRV":
            weight, port, target = val.split()
            return RR(qname, dnslib.QTYPE.SRV, ttl=ttl,
                      rdata=dnslib.SRV(priority=int(record["priority"] or 0), weight=int(weight),
                                       port=int(port), target=target))
        if rtype == "CAA":
            flags, tag, value = val.split(None, 2)
            return RR(qname, dnslib.QTYPE.CAA, ttl=ttl,
                      rdata=dnslib.CAA(int(flags), tag, value.strip('"')))
    except Exception:  # noqa: BLE001 - a bad row must not take down the server
        log.warning("skip malformed record zone=%s type=%s", zone, rtype)
    return None


def _matching(records: list[dict], rel: str) -> list[dict]:
    exact = [r for r in records if r["name"] == rel]
    if exact:
        return exact
    if rel == "@":
        return []
    wildcard: list[dict] = []
    for r in records:
        n = r["name"]
        if n == "*":
            if rel.count(".") == 0:
                wildcard.append(r)
        elif n.startswith("*."):
            suffix = n[2:]
            if rel.endswith("." + suffix) and rel[: -len(suffix) - 1].count(".") == 0:
                wildcard.append(r)
    return wildcard


class AuthoritativeResolver:
    def __init__(self, store: ZoneStore, limiter: DNSRateLimiter,
                 platform_domain: str | None = None) -> None:
        self.store = store
        self.limiter = limiter
        self.platform = platform_domain or get_settings().platform_domain

    def resolve(self, request: DNSRecord, handler: Any) -> DNSRecord:
        ip = getattr(handler, "client_address", ("0.0.0.0", 0))[0]
        reply = request.reply()
        reply.header.aa = 1
        reply.header.ra = 0
        reply.header.rd = 0

        if not self.limiter.allow(ip):
            reply.header.rcode = RCODE.REFUSED
            return reply

        qname = str(request.q.qname).rstrip(".").lower()
        qtype = dnslib.QTYPE.get(request.q.qtype)
        if request.q.qtype == 255 or qtype in ("AXFR", "IXFR", "OPT"):  # noqa: PLR2004
            reply.header.rcode = RCODE.REFUSED
            return reply

        self.store.maybe_refresh()
        found = self.store.find(qname)
        if found is None:
            # Not ours: refuse. Never recurse, never act as an open resolver.
            reply.header.rcode = RCODE.REFUSED
            return reply

        zone_name, rel, zone = found
        ns = self.store.ns_hosts
        soa = RR(
            DNSLabel(zone_name), dnslib.QTYPE.SOA, ttl=300,
            rdata=dnslib.SOA(
                mname=ns[0] if ns else f"ns1.{self.platform}",
                rname=f"hostmaster.{self.platform}",
                times=(zone.get("version", 1), 3600, 600, 604800, 300),
            ),
        )

        if rel == "@" and qtype == "SOA":
            reply.add_answer(soa)
            return reply
        if rel == "@" and qtype == "NS":
            for host in ns:
                reply.add_answer(RR(DNSLabel(zone_name), dnslib.QTYPE.NS, ttl=86400,
                                    rdata=dnslib.NS(host)))
            return reply

        matches = _matching(zone["records"], rel)
        if not matches:
            reply.header.rcode = RCODE.NXDOMAIN
            reply.add_auth(soa)
            return reply

        answers = [rr for rr in (rr_from(r, zone_name) for r in matches) if rr is not None]
        selected = [rr for rr in answers if dnslib.QTYPE.get(rr.rtype) == qtype]
        if not selected and qtype != "CNAME":
            selected = [rr for rr in answers if dnslib.QTYPE.get(rr.rtype) == "CNAME"]
        if not selected:
            # Name exists, requested type does not: NODATA.
            reply.add_auth(soa)
            return reply
        for rr in selected:
            reply.add_answer(rr)
        return reply


class _Handler(DNSHandler):
    # Keep UDP responses inside a conservative EDNS-friendly size.
    udplen = 1232


def build_servers(host: str, port: int, store: ZoneStore,
                  limiter: DNSRateLimiter) -> tuple[DNSServer, DNSServer]:
    resolver = AuthoritativeResolver(store, limiter)
    udp = DNSServer(resolver, address=host, port=port, tcp=False, handler=_Handler)
    try:
        tcp = DNSServer(resolver, address=host, port=port, tcp=True, handler=_Handler)
    except OSError:
        tcp = None
    return udp, tcp


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = get_settings()
    parser = argparse.ArgumentParser(description="LiuliDNS authoritative DNS server")
    parser.add_argument("--host", default=s.dns_host)
    parser.add_argument("--port", type=int, default=s.dns_port)
    parser.add_argument("--refresh", type=int, default=15)
    args = parser.parse_args()

    from ..db import init_db

    init_db()
    store = ZoneStore(refresh_seconds=max(2, args.refresh), ns_hosts=s.nameserver_list)
    store.refresh()
    limiter = DNSRateLimiter(s.dns_qps_per_ip, s.dns_qps_global)
    udp, tcp = build_servers(args.host, args.port, store, limiter)
    log.info("UDP listening on %s:%s (zones=%d)", args.host, args.port, len(store._zones))
    threads = [threading.Thread(target=udp.start, daemon=True)]
    if tcp is not None:
        log.info("TCP listening on %s:%s", args.host, args.port)
        threads.append(threading.Thread(target=tcp.start, daemon=True))
    for t in threads:
        t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
