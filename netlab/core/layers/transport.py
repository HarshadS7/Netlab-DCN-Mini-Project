"""Transport layer: real TCP segments and UDP datagrams.

Both checksums cover the IPv4 pseudo-header, so they genuinely protect the
addresses as well as the data. The field layout follows RFC 793 (4-bit data
offset, 6 reserved bits, 6 control bits), which is the layout Forouzan teaches.
"""

from __future__ import annotations

import struct

from ..errors.checksum import internet_checksum
from ..model import Field, LayerView
from .network import PROTOCOL_NUMBERS, pseudo_header

__all__ = ["TCP_HEADER_LEN", "UDP_HEADER_LEN", "FLAGS", "build_tcp", "build_udp"]

TCP_HEADER_LEN = 20
UDP_HEADER_LEN = 8

# Control bits, most significant first, as they sit in the 6-bit field.
FLAGS = ["URG", "ACK", "PSH", "RST", "SYN", "FIN"]

_FLAG_MEANINGS = {
    "URG": "Urgent pointer is significant",
    "ACK": "Acknowledgement number is significant",
    "PSH": "Deliver to the application now, do not buffer",
    "RST": "Reset the connection",
    "SYN": "Synchronise sequence numbers -- opens a connection",
    "FIN": "Sender has finished sending",
}


def _flag_bits(names: list[str]) -> int:
    value = 0
    for name in names:
        if name.upper() not in FLAGS:
            raise ValueError(f"unknown TCP flag: {name!r}")
        value |= 1 << (5 - FLAGS.index(name.upper()))
    return value


def build_tcp(
    payload: bytes,
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
    *,
    seq: int = 0,
    ack: int = 0,
    flags: list[str] | None = None,
    window: int = 64240,
    urgent: int = 0,
) -> LayerView:
    """Build a 20-byte TCP header (no options) around ``payload``."""
    from ..bits import parse_ipv4

    flag_names = flags if flags is not None else ["PSH", "ACK"]
    flag_value = _flag_bits(flag_names)
    offset_reserved_flags = (TCP_HEADER_LEN // 4) << 12 | flag_value

    def pack(checksum: int) -> bytes:
        return struct.pack(
            "!HHIIHHHH",
            src_port,
            dst_port,
            seq,
            ack,
            offset_reserved_flags,
            window,
            checksum,
            urgent,
        )

    # The checksum covers pseudo-header + header (zeroed checksum) + payload.
    covered = (
        pseudo_header(
            parse_ipv4(src_ip),
            parse_ipv4(dst_ip),
            PROTOCOL_NUMBERS["TCP"],
            TCP_HEADER_LEN + len(payload),
        )
        + pack(0)
        + payload
    )
    checksum = internet_checksum(covered)
    header = pack(checksum)

    fields = [
        Field(
            "Source Port",
            0,
            16,
            str(src_port),
            "Identifies the sending application",
            src_port,
        ),
        Field(
            "Destination Port",
            16,
            16,
            str(dst_port),
            _port_meaning(dst_port),
            dst_port,
        ),
        Field(
            "Sequence Number",
            32,
            32,
            str(seq),
            "Byte offset of the first data byte in this segment",
            seq,
        ),
        Field(
            "Acknowledgement Number",
            64,
            32,
            str(ack),
            "Next byte expected from the other side",
            ack,
        ),
        Field(
            "Data Offset",
            96,
            4,
            f"{TCP_HEADER_LEN // 4} ({TCP_HEADER_LEN} bytes)",
            "Header length in 32-bit words",
            TCP_HEADER_LEN // 4,
        ),
        Field("Reserved", 100, 6, "0", "Reserved for future use", 0),
    ]

    # One field per control bit, so each can be highlighted individually.
    for index, name in enumerate(FLAGS):
        is_set = bool(flag_value & (1 << (5 - index)))
        fields.append(
            Field(
                name,
                106 + index,
                1,
                "1" if is_set else "0",
                _FLAG_MEANINGS[name],
                int(is_set),
            )
        )

    fields += [
        Field(
            "Window Size",
            112,
            16,
            str(window),
            "Bytes the receiver can still accept -- this is flow control",
            window,
        ),
        Field(
            "Checksum",
            128,
            16,
            f"0x{checksum:04X}",
            "Covers pseudo-header, header and data",
            checksum,
        ),
        Field(
            "Urgent Pointer", 144, 16, str(urgent), "Only meaningful if URG is set", urgent
        ),
    ]

    shown = "+".join(flag_names) if flag_names else "none"
    return LayerView(
        layer="Transport",
        protocol="TCP",
        header=header,
        fields=fields,
        summary=f"{src_port} to {dst_port} [{shown}] seq={seq} win={window}",
    )


def build_udp(
    payload: bytes, src_ip: str, dst_ip: str, src_port: int, dst_port: int
) -> LayerView:
    """Build an 8-byte UDP header -- four fields, no connection, no promises."""
    from ..bits import parse_ipv4

    length = UDP_HEADER_LEN + len(payload)

    def pack(checksum: int) -> bytes:
        return struct.pack("!HHHH", src_port, dst_port, length, checksum)

    covered = (
        pseudo_header(
            parse_ipv4(src_ip), parse_ipv4(dst_ip), PROTOCOL_NUMBERS["UDP"], length
        )
        + pack(0)
        + payload
    )
    # In UDP a computed checksum of zero is transmitted as all ones, because
    # zero is the reserved "no checksum computed" value.
    checksum = internet_checksum(covered) or 0xFFFF
    header = pack(checksum)

    fields = [
        Field("Source Port", 0, 16, str(src_port), "Sending application", src_port),
        Field(
            "Destination Port", 16, 16, str(dst_port), _port_meaning(dst_port), dst_port
        ),
        Field(
            "Length",
            32,
            16,
            f"{length} bytes",
            f"Header ({UDP_HEADER_LEN}) + data ({len(payload)})",
            length,
        ),
        Field(
            "Checksum",
            48,
            16,
            f"0x{checksum:04X}",
            "Optional in IPv4, mandatory in IPv6",
            checksum,
        ),
    ]

    return LayerView(
        layer="Transport",
        protocol="UDP",
        header=header,
        fields=fields,
        summary=f"{src_port} to {dst_port}, {length} bytes, connectionless",
    )


_WELL_KNOWN = {
    20: "FTP data",
    21: "FTP control",
    23: "Telnet",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    110: "POP3",
    443: "HTTPS",
}


def _port_meaning(port: int) -> str:
    service = _WELL_KNOWN.get(port)
    if service:
        return f"Well-known port for {service}"
    if port < 1024:
        return "Well-known port"
    if port < 49152:
        return "Registered port"
    return "Ephemeral port, chosen by the client"
