"""Encapsulation: drive a message down the stack and back up again.

This is the engine behind the Packet Journey page. :func:`encapsulate` builds a
real frame bottom-up in the order the checksums require, and :func:`decapsulate`
verifies it the way a receiver would -- checking the FCS first, then the IP
header checksum, then the transport checksum, and reporting exactly where a
corrupted frame died.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .layers import application, datalink, network, transport
from .model import Frame, assemble

__all__ = ["EncapsulationRequest", "encapsulate", "decapsulate", "DecapsulationResult"]

# Which transport each application protocol rides on, and its server port.
APP_PROTOCOLS = {
    "HTTP": ("TCP", 80),
    "DNS": ("UDP", 53),
    "SMTP": ("TCP", 25),
    "FTP": ("TCP", 21),
}


@dataclass
class EncapsulationRequest:
    """Everything the Packet Journey controls can set."""

    message: str = "Hello DCN"
    app_protocol: str = "HTTP"
    src_ip: str = "10.0.0.1"
    dst_ip: str = "10.0.0.2"
    src_mac: str = "02:1A:2B:3C:4D:5E"
    dst_mac: str = "02:AA:BB:CC:DD:EE"
    src_port: int = 49152
    dst_port: int | None = None
    host: str = "example.com"
    path: str = "/index.html"
    ttl: int = 64
    seq: int = 1000
    ack: int = 0
    window: int = 64240
    flags: list[str] = dc_field(default_factory=lambda: ["PSH", "ACK"])


def _build_application(request: EncapsulationRequest):
    """Build the application PDU. Returns (layer view, payload bytes)."""
    protocol = request.app_protocol.upper()
    if protocol == "HTTP":
        return application.build_http_request(host=request.host, path=request.path)
    if protocol == "DNS":
        return application.build_dns_query(domain=request.host)
    if protocol == "SMTP":
        return application.build_smtp(subject=request.message, body=request.message)
    if protocol == "FTP":
        return application.build_ftp(argument=request.path.lstrip("/") or "file.txt")
    raise ValueError(f"unsupported application protocol: {request.app_protocol!r}")


def encapsulate(request: EncapsulationRequest) -> Frame:
    """Build a complete Ethernet frame from an application message.

    Built bottom-up because each layer's checksum depends on what it wraps: the
    transport checksum covers the payload, the IPv4 total length depends on the
    transport header, and the FCS covers everything.
    """
    protocol = request.app_protocol.upper()
    transport_name, default_port = APP_PROTOCOLS.get(protocol, ("TCP", 80))
    dst_port = request.dst_port if request.dst_port is not None else default_port

    app_view, payload = _build_application(request)

    if transport_name == "TCP":
        transport_view = transport.build_tcp(
            payload,
            request.src_ip,
            request.dst_ip,
            request.src_port,
            dst_port,
            seq=request.seq,
            ack=request.ack,
            flags=request.flags,
            window=request.window,
        )
    else:
        transport_view = transport.build_udp(
            payload, request.src_ip, request.dst_ip, request.src_port, dst_port
        )

    network_view = network.build_ipv4(
        transport_view.header + payload,
        request.src_ip,
        request.dst_ip,
        transport_name,
        ttl=request.ttl,
    )

    link_view, padding = datalink.build_ethernet(
        network_view.header + transport_view.header + payload,
        src_mac=request.src_mac,
        dst_mac=request.dst_mac,
    )
    link_view.padding = padding

    return assemble([link_view, network_view, transport_view, app_view], payload)


@dataclass
class LayerCheck:
    """The verdict at one layer on the receiving side."""

    layer: str
    protocol: str
    ok: bool
    detail: str


@dataclass
class DecapsulationResult:
    """What the receiver made of the (possibly corrupted) frame."""

    checks: list[LayerCheck]
    payload: bytes | None
    failed_at: str | None

    @property
    def delivered(self) -> bool:
        return self.failed_at is None


def decapsulate(wire: bytes, frame: Frame) -> DecapsulationResult:
    """Verify a received frame layer by layer, stopping at the first failure.

    ``frame`` supplies the layout; ``wire`` is what actually arrived, which may
    differ if the channel corrupted it. A real receiver discards the frame at
    the first failed check -- so this does too, and reports where.
    """
    checks: list[LayerCheck] = []
    link = frame.layers[0]
    net = frame.layer("IPv4")
    tran = frame.layer("TCP") or frame.layer("UDP")

    # Data link: the FCS covers header, payload and padding.
    fcs_ok = datalink.verify_ethernet(wire)
    checks.append(
        LayerCheck(
            "Data Link",
            "Ethernet",
            fcs_ok,
            "FCS matches -- frame accepted"
            if fcs_ok
            else "FCS mismatch -- frame silently discarded, no NAK is ever sent",
        )
    )
    if not fcs_ok:
        return DecapsulationResult(checks, None, "Data Link")

    # Network: the IPv4 header checksum covers the header only.
    ip_bytes = wire[net.header_start : net.header_end]
    parsed = network.parse_ipv4_header(ip_bytes)
    ip_ok = parsed["checksum_valid"]
    checks.append(
        LayerCheck(
            "Network",
            "IPv4",
            ip_ok,
            f"Header checksum valid, TTL {parsed['ttl']}, {parsed['src']} to {parsed['dst']}"
            if ip_ok
            else "Header checksum mismatch -- datagram dropped by the router",
        )
    )
    if not ip_ok:
        return DecapsulationResult(checks, None, "Network")

    # Transport: the checksum covers the pseudo-header, header and data.
    from .errors.checksum import internet_checksum

    protocol_name = tran.protocol
    segment = wire[tran.header_start : link.padding_start]
    covered = (
        network.pseudo_header(
            bytes(int(p) for p in parsed["src"].split(".")),
            bytes(int(p) for p in parsed["dst"].split(".")),
            network.PROTOCOL_NUMBERS[protocol_name],
            len(segment),
        )
        + segment
    )
    transport_ok = internet_checksum(covered) == 0
    checks.append(
        LayerCheck(
            "Transport",
            protocol_name,
            transport_ok,
            "Checksum valid -- data handed to the application"
            if transport_ok
            else (
                "Checksum mismatch -- TCP will not acknowledge, so the sender retransmits"
                if protocol_name == "TCP"
                else "Checksum mismatch -- UDP just drops it, the application never finds out"
            ),
        )
    )
    if not transport_ok:
        return DecapsulationResult(checks, None, "Transport")

    payload = wire[tran.header_start + len(tran.header) : link.padding_start]
    app = frame.layers[-1]
    checks.append(
        LayerCheck("Application", app.protocol, True, f"{len(payload)} bytes delivered")
    )
    return DecapsulationResult(checks, payload, None)
