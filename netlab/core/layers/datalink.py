"""Data link layer: Ethernet II framing, plus the framing techniques of 5.2.

Two notes on the frame check sequence, because both cost real debugging time:

* The FCS uses IEEE CRC-32 (:func:`~netlab.core.errors.crc.crc32_ieee`), not
  the textbook long division. The textbook variant would produce a frame
  Wireshark rejects.
* The FCS is appended little-endian, which is why it looks byte-reversed in a
  hex dump next to every other field in this project.

``.pcap`` export deliberately omits the FCS -- see :mod:`netlab.core.pcap`.
"""

from __future__ import annotations

import struct

from ..bits import format_mac, parse_mac
from ..errors.crc import crc32_ieee
from ..model import Field, LayerView

__all__ = [
    "ETHERNET_HEADER_LEN",
    "ETHERNET_MIN_FRAME",
    "ETHERTYPES",
    "build_ethernet",
    "byte_stuff",
    "byte_unstuff",
    "bit_stuff",
    "bit_unstuff",
]

ETHERNET_HEADER_LEN = 14
FCS_LEN = 4
# 802.3 requires 64 bytes on the wire including the 4-byte FCS.
ETHERNET_MIN_FRAME = 60

ETHERTYPES = {"IPv4": 0x0800, "ARP": 0x0806, "IPv6": 0x86DD}


def build_ethernet(
    payload: bytes,
    src_mac: str = "02:1A:2B:3C:4D:5E",
    dst_mac: str = "02:AA:BB:CC:DD:EE",
    ethertype: str = "IPv4",
    *,
    pad: bool = True,
) -> tuple[LayerView, bytes]:
    """Build an Ethernet II header and FCS.

    Returns the layer view and any padding that had to be inserted, because the
    padding sits between the payload and the trailer and the caller needs to
    account for it when assembling the frame.
    """
    dst_raw, src_raw = parse_mac(dst_mac), parse_mac(src_mac)
    type_value = ETHERTYPES.get(ethertype, 0x0800)
    header = struct.pack("!6s6sH", dst_raw, src_raw, type_value)

    padding = b""
    if pad:
        short_by = ETHERNET_MIN_FRAME - (ETHERNET_HEADER_LEN + len(payload))
        if short_by > 0:
            padding = b"\x00" * short_by

    fcs_value = crc32_ieee(header + payload + padding)
    # Little-endian on the wire, unlike every other field here.
    trailer = struct.pack("<I", fcs_value)

    fields = [
        Field(
            "Destination MAC",
            0,
            48,
            format_mac(dst_raw),
            "Physical address of the next hop, not the final destination",
            dst_raw,
        ),
        Field(
            "Source MAC",
            48,
            48,
            format_mac(src_raw),
            "Physical address of this interface",
            src_raw,
        ),
        Field(
            "EtherType",
            96,
            16,
            f"0x{type_value:04X} ({ethertype})",
            "Which network-layer protocol is inside",
            type_value,
        ),
    ]

    trailer_fields = [
        Field(
            "FCS",
            0,
            32,
            f"0x{fcs_value:08X}",
            "IEEE CRC-32 over header and data; stored little-endian",
            fcs_value,
        )
    ]

    view = LayerView(
        layer="Data Link",
        protocol="Ethernet",
        header=header,
        fields=fields,
        trailer=trailer,
        trailer_fields=trailer_fields,
        summary=f"{format_mac(src_raw)} to {format_mac(dst_raw)}, type {ethertype}",
    )
    return view, padding


def verify_ethernet(frame: bytes) -> bool:
    """Check a received frame's FCS, including any padding it carries."""
    if len(frame) < ETHERNET_HEADER_LEN + FCS_LEN:
        return False
    body, trailer = frame[:-FCS_LEN], frame[-FCS_LEN:]
    return crc32_ieee(body) == struct.unpack("<I", trailer)[0]


# --------------------------------------------------------------------------
# Framing techniques (syllabus 5.2) -- variable-size framing needs a way to say
# "this flag byte is data, not a delimiter".
# --------------------------------------------------------------------------

FLAG_BYTE = 0x7E
ESCAPE_BYTE = 0x7D


def byte_stuff(data: bytes, flag: int = FLAG_BYTE, escape: int = ESCAPE_BYTE) -> bytes:
    """Character stuffing: escape any flag or escape byte appearing in data."""
    out = bytearray()
    for byte in data:
        if byte in (flag, escape):
            out.append(escape)
        out.append(byte)
    return bytes(out)


def byte_unstuff(data: bytes, escape: int = ESCAPE_BYTE) -> bytes:
    out = bytearray()
    skip = False
    for byte in data:
        if skip:
            out.append(byte)
            skip = False
        elif byte == escape:
            skip = True
        else:
            out.append(byte)
    return bytes(out)


def bit_stuff(bits: list[int], run: int = 5) -> list[int]:
    """Bit stuffing: insert a 0 after ``run`` consecutive 1s, as HDLC does."""
    out: list[int] = []
    ones = 0
    for bit in bits:
        out.append(bit)
        ones = ones + 1 if bit == 1 else 0
        if ones == run:
            out.append(0)
            ones = 0
    return out


def bit_unstuff(bits: list[int], run: int = 5) -> list[int]:
    out: list[int] = []
    ones = 0
    index = 0
    while index < len(bits):
        bit = bits[index]
        out.append(bit)
        if bit == 1:
            ones += 1
            if ones == run and index + 1 < len(bits):
                index += 1  # drop the stuffed 0
                ones = 0
        else:
            ones = 0
        index += 1
    return out
