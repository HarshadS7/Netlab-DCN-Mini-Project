"""Network layer: real IPv4 and IPv6 headers.

Every field is packed with :mod:`struct` and the IPv4 header checksum is
genuinely computed, so the bytes produced here are the bytes Wireshark parses
when a frame is exported to ``.pcap``.
"""

from __future__ import annotations

import struct

from ..bits import format_ipv4, parse_ipv4
from ..errors.checksum import internet_checksum
from ..model import Field, LayerView

__all__ = [
    "PROTOCOL_NUMBERS",
    "build_ipv4",
    "build_ipv6",
    "parse_ipv4_header",
    "pseudo_header",
]

IPV4_HEADER_LEN = 20
IPV6_HEADER_LEN = 40

PROTOCOL_NUMBERS = {"ICMP": 1, "TCP": 6, "UDP": 17}

_FLAG_MEANINGS = {
    0b000: "no flags set",
    0b010: "Don't Fragment",
    0b001: "More Fragments",
}


def pseudo_header(src: bytes, dst: bytes, protocol: int, length: int) -> bytes:
    """The 12-byte IPv4 pseudo-header TCP and UDP checksums cover.

    It is never transmitted -- it exists only so the transport checksum also
    protects the addresses, which is why a NAT box has to recompute it.
    """
    return struct.pack("!4s4sBBH", src, dst, 0, protocol, length)


def build_ipv4(
    payload: bytes,
    src: str,
    dst: str,
    protocol: str = "TCP",
    *,
    ttl: int = 64,
    identification: int = 0x1C46,
    dont_fragment: bool = True,
    fragment_offset: int = 0,
    dscp: int = 0,
    ecn: int = 0,
) -> LayerView:
    """Build a 20-byte IPv4 header (no options) around ``payload``."""
    src_raw, dst_raw = parse_ipv4(src), parse_ipv4(dst)
    protocol_number = PROTOCOL_NUMBERS.get(protocol.upper(), 6)
    total_length = IPV4_HEADER_LEN + len(payload)
    version_ihl = (4 << 4) | (IPV4_HEADER_LEN // 4)
    tos = (dscp << 2) | ecn
    flags = 0b010 if dont_fragment else 0b000
    flags_fragment = (flags << 13) | (fragment_offset & 0x1FFF)

    def pack(checksum: int) -> bytes:
        return struct.pack(
            "!BBHHHBBH4s4s",
            version_ihl,
            tos,
            total_length,
            identification,
            flags_fragment,
            ttl,
            protocol_number,
            checksum,
            src_raw,
            dst_raw,
        )

    # The checksum is computed over the header with the checksum field zeroed.
    header = pack(internet_checksum(pack(0)))
    checksum = struct.unpack("!H", header[10:12])[0]

    fields = [
        Field("Version", 0, 4, "4", "IPv4", 4),
        Field(
            "IHL",
            4,
            4,
            f"{IPV4_HEADER_LEN // 4} ({IPV4_HEADER_LEN} bytes)",
            "Header length in 32-bit words; 5 means no options",
            IPV4_HEADER_LEN // 4,
        ),
        Field("DSCP", 8, 6, str(dscp), "Differentiated services -- QoS class", dscp),
        Field("ECN", 14, 2, str(ecn), "Explicit congestion notification", ecn),
        Field(
            "Total Length",
            16,
            16,
            f"{total_length} bytes",
            f"Header ({IPV4_HEADER_LEN}) + payload ({len(payload)})",
            total_length,
        ),
        Field(
            "Identification",
            32,
            16,
            f"0x{identification:04X}",
            "Groups fragments belonging to one original datagram",
            identification,
        ),
        Field(
            "Flags",
            48,
            3,
            f"0b{flags:03b}",
            _FLAG_MEANINGS.get(flags, "reserved"),
            flags,
        ),
        Field(
            "Fragment Offset",
            51,
            13,
            str(fragment_offset),
            "Position of this fragment, in 8-byte units",
            fragment_offset,
        ),
        Field(
            "TTL",
            64,
            8,
            str(ttl),
            "Decremented by every router; the packet dies at 0",
            ttl,
        ),
        Field(
            "Protocol",
            72,
            8,
            f"{protocol_number} ({protocol.upper()})",
            "Which transport protocol is inside",
            protocol_number,
        ),
        Field(
            "Header Checksum",
            80,
            16,
            f"0x{checksum:04X}",
            "Covers the header only -- recomputed at every hop because TTL changes",
            checksum,
        ),
        Field("Source Address", 96, 32, format_ipv4(src_raw), "Sender", src_raw),
        Field(
            "Destination Address", 128, 32, format_ipv4(dst_raw), "Receiver", dst_raw
        ),
    ]

    return LayerView(
        layer="Network",
        protocol="IPv4",
        header=header,
        fields=fields,
        summary=f"{format_ipv4(src_raw)} to {format_ipv4(dst_raw)}, {protocol.upper()}, TTL {ttl}",
    )


def build_ipv6(
    payload: bytes,
    src: str = "2001:db8::1",
    dst: str = "2001:db8::2",
    protocol: str = "TCP",
    *,
    hop_limit: int = 64,
    traffic_class: int = 0,
    flow_label: int = 0,
) -> LayerView:
    """Build a 40-byte IPv6 header.

    Shown beside IPv4 on the Network Lab page: twice the size, yet far simpler
    -- no checksum, no fragmentation fields, no variable-length options.
    """
    import ipaddress

    src_raw = ipaddress.IPv6Address(src).packed
    dst_raw = ipaddress.IPv6Address(dst).packed
    next_header = PROTOCOL_NUMBERS.get(protocol.upper(), 6)

    first_word = (6 << 28) | (traffic_class << 20) | (flow_label & 0xFFFFF)
    header = struct.pack(
        "!IHBB16s16s", first_word, len(payload), next_header, hop_limit, src_raw, dst_raw
    )

    fields = [
        Field("Version", 0, 4, "6", "IPv6", 6),
        Field(
            "Traffic Class",
            4,
            8,
            str(traffic_class),
            "Equivalent of IPv4's DSCP + ECN",
            traffic_class,
        ),
        Field(
            "Flow Label",
            12,
            20,
            f"0x{flow_label:05X}",
            "Labels a stream so routers can treat it consistently -- no IPv4 equivalent",
            flow_label,
        ),
        Field(
            "Payload Length",
            32,
            16,
            f"{len(payload)} bytes",
            "Payload only, unlike IPv4's Total Length which includes the header",
            len(payload),
        ),
        Field(
            "Next Header",
            48,
            8,
            f"{next_header} ({protocol.upper()})",
            "Same role as IPv4's Protocol field",
            next_header,
        ),
        Field(
            "Hop Limit", 56, 8, str(hop_limit), "IPv4's TTL, honestly renamed", hop_limit
        ),
        Field("Source Address", 64, 128, str(ipaddress.IPv6Address(src)), "Sender", src_raw),
        Field(
            "Destination Address",
            192,
            128,
            str(ipaddress.IPv6Address(dst)),
            "Receiver",
            dst_raw,
        ),
    ]

    return LayerView(
        layer="Network",
        protocol="IPv6",
        header=header,
        fields=fields,
        summary=f"{src} to {dst}, {protocol.upper()}, hop limit {hop_limit}",
    )


def parse_ipv4_header(header: bytes) -> dict:
    """Unpack a received header -- used by the receiving side of the journey."""
    if len(header) < IPV4_HEADER_LEN:
        raise ValueError(f"IPv4 header needs {IPV4_HEADER_LEN} bytes")
    (
        version_ihl,
        tos,
        total_length,
        identification,
        flags_fragment,
        ttl,
        protocol,
        checksum,
        src,
        dst,
    ) = struct.unpack("!BBHHHBBH4s4s", header[:IPV4_HEADER_LEN])
    return {
        "version": version_ihl >> 4,
        "ihl": version_ihl & 0x0F,
        "dscp": tos >> 2,
        "ecn": tos & 0x03,
        "total_length": total_length,
        "identification": identification,
        "flags": flags_fragment >> 13,
        "fragment_offset": flags_fragment & 0x1FFF,
        "ttl": ttl,
        "protocol": protocol,
        "checksum": checksum,
        "src": format_ipv4(src),
        "dst": format_ipv4(dst),
        "checksum_valid": internet_checksum(header[:IPV4_HEADER_LEN]) == 0,
    }
