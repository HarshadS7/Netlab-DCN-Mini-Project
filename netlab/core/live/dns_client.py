"""A real DNS client, built from the wire format up.

No resolver library is used. The query bytes come from
:func:`netlab.core.layers.application.build_dns_query` -- the same encoder the
Packet Journey page draws -- and go out over a real UDP socket. What comes back
is a real response from a real server, parsed by hand.

Every socket call is recorded as it happens, so the Application Lab can show
the sequence the syllabus calls the "application programming interface".
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field as dc_field

from ..layers.application import build_dns_query, parse_dns_message

__all__ = ["DnsExchange", "resolve", "PUBLIC_RESOLVERS", "system_resolver"]

PUBLIC_RESOLVERS = {
    "Google (8.8.8.8)": "8.8.8.8",
    "Cloudflare (1.1.1.1)": "1.1.1.1",
    "Quad9 (9.9.9.9)": "9.9.9.9",
}


@dataclass
class DnsExchange:
    """One query and its reply, with the bytes kept for inspection."""

    domain: str
    qtype: str
    server: str
    port: int
    query: bytes = b""
    response: bytes = b""
    parsed: dict | None = None
    elapsed_ms: float = 0.0
    trace: list[str] = dc_field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.parsed is not None

    @property
    def answers(self) -> list[dict]:
        return self.parsed["answers"] if self.parsed else []

    @property
    def summary(self) -> str:
        if self.error:
            return self.error
        if not self.answers:
            rcode = self.parsed["rcode"] if self.parsed else "?"
            return f"No answer records ({rcode})"
        first = self.answers[0]
        return f"{first['name']} is {first['data']} (TTL {first['ttl']}s)"


def system_resolver() -> str | None:
    """Best guess at the resolver this machine is configured to use.

    Opening a UDP socket to a public address does not send anything; it just
    makes the OS pick a route, which reveals the local interface. From there we
    fall back to the gateway convention, since Windows has no resolv.conf.
    """
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.3)
        probe.connect(("8.8.8.8", 53))
        local = probe.getsockname()[0]
        probe.close()
        parts = local.split(".")
        return ".".join(parts[:3] + ["1"])
    except OSError:
        return None


def resolve(
    domain: str,
    qtype: str = "A",
    server: str = "8.8.8.8",
    port: int = 53,
    timeout: float = 3.0,
) -> DnsExchange:
    """Send a hand-built DNS query over a real UDP socket and parse the reply."""
    exchange = DnsExchange(domain=domain, qtype=qtype, server=server, port=port)

    try:
        _, query = build_dns_query(domain, qtype)
    except ValueError as error:
        exchange.error = f"Could not build the query: {error}"
        return exchange
    exchange.query = query
    exchange.trace.append(f"build query      {len(query)} bytes, ID 0x{query[0]:02X}{query[1]:02X}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    exchange.trace.append("socket()         AF_INET, SOCK_DGRAM  (UDP)")
    sock.settimeout(timeout)

    started = time.perf_counter()
    try:
        sock.sendto(query, (server, port))
        exchange.trace.append(f"sendto()         -> {server}:{port}")

        response, source = sock.recvfrom(4096)
        exchange.elapsed_ms = (time.perf_counter() - started) * 1000
        exchange.trace.append(
            f"recvfrom()       <- {source[0]}:{source[1]}, {len(response)} bytes"
        )
        exchange.response = response

        parsed = parse_dns_message(response)
        exchange.parsed = parsed
        if parsed["id"] != int.from_bytes(query[:2], "big"):
            exchange.error = "Transaction ID mismatch -- this reply is not ours"
        elif parsed["truncated"]:
            exchange.error = "Response truncated (TC set) -- it would need TCP"
    except socket.timeout:
        exchange.error = (
            f"No reply from {server}:{port} within {timeout:g}s. "
            "Outbound UDP port 53 may be blocked on this network -- "
            "switch the resolver to the built-in offline stub."
        )
    except OSError as error:
        exchange.error = f"Socket error: {error}"
    except ValueError as error:
        exchange.error = f"Malformed response: {error}"
    finally:
        sock.close()
        exchange.trace.append("close()")

    return exchange
