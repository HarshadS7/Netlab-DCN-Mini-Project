"""A tiny DNS server on 127.0.0.1, for when the network blocks port 53.

College and campus networks routinely block outbound UDP 53 to force traffic
through their own resolver. Rather than let that break the demo, this serves a
handful of canned records from a real UDP socket on the loopback interface.

The socket I/O and the message parsing stay completely real -- only the answers
are local. That is a much better fallback than switching to a library call,
because the thing being demonstrated is the wire format, not the internet.
"""

from __future__ import annotations

import socket
import struct
import threading

from ..layers.application import DNS_TYPES, encode_qname, parse_dns_message

__all__ = ["StubResolver", "CANNED_RECORDS"]

CANNED_RECORDS: dict[str, dict[str, list[str]]] = {
    "example.com": {"A": ["93.184.216.34"], "AAAA": ["2606:2800:21f:cb07:6820:80da:af6b:8b2c"]},
    "kjsce.somaiya.edu": {"A": ["103.86.180.14"]},
    "somaiya.edu": {"A": ["103.86.180.10"]},
    "google.com": {"A": ["142.250.183.14"]},
    "localhost": {"A": ["127.0.0.1"]},
}

DEFAULT_TTL = 300


class StubResolver:
    """A loopback DNS server answering from :data:`CANNED_RECORDS`."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind((host, port))
        self.host, self.port = self._socket.getsockname()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._running.set()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        try:
            self._socket.close()
        except OSError:
            pass
        self._thread = None

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    def _serve(self) -> None:
        self._socket.settimeout(0.4)
        while self._running.is_set():
            try:
                query, client = self._socket.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                reply = self.build_reply(query)
            except ValueError:
                continue
            try:
                self._socket.sendto(reply, client)
            except OSError:
                break

    @staticmethod
    def build_reply(query: bytes) -> bytes:
        """Build a real DNS response message for ``query``."""
        parsed = parse_dns_message(query)
        if not parsed["questions"]:
            raise ValueError("no question section")

        question = parsed["questions"][0]
        name, qtype = question["name"], question["type"]
        records = CANNED_RECORDS.get(name.lower(), {}).get(qtype, [])

        # QR=1, RD copied from the query, RA=1; NXDOMAIN when we know nothing.
        rcode = 0 if records else 3
        flags = 0x8080 | (parsed["flags"] & 0x0100) | rcode

        header = struct.pack("!HHHHHH", parsed["id"], flags, 1, len(records), 0, 0)
        type_value = next((k for k, v in DNS_TYPES.items() if v == qtype), 1)
        body = encode_qname(name) + struct.pack("!HH", type_value, 1)

        for record in records:
            rdata = _encode_rdata(qtype, record)
            body += (
                b"\xc0\x0c"  # pointer to the name at offset 12, like a real server
                + struct.pack("!HHIH", type_value, 1, DEFAULT_TTL, len(rdata))
                + rdata
            )
        return header + body

    def __enter__(self) -> "StubResolver":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


def _encode_rdata(qtype: str, value: str) -> bytes:
    if qtype == "A":
        return bytes(int(part) for part in value.split("."))
    if qtype == "AAAA":
        import ipaddress

        return ipaddress.IPv6Address(value).packed
    if qtype in ("NS", "CNAME"):
        return encode_qname(value)
    return value.encode()
