"""Bit and byte level helpers shared by every layer.

Nothing in this package knows about Qt. Everything above this module works on
real ``bytes`` objects, so the hex dump the UI finally draws is a genuine frame
rather than a decorative label.
"""

from __future__ import annotations

import random

__all__ = [
    "bytes_to_bits",
    "bits_to_bytes",
    "bits_to_str",
    "str_to_bits",
    "flip_bit",
    "bit_diff",
    "hexdump",
    "format_mac",
    "parse_mac",
    "format_ipv4",
    "parse_ipv4",
    "random_mac",
]


def bytes_to_bits(data: bytes) -> list[int]:
    """Expand ``data`` to a list of bits, MSB of byte 0 first."""
    return [(byte >> shift) & 1 for byte in data for shift in range(7, -1, -1)]


def bits_to_bytes(bits: list[int]) -> bytes:
    """Inverse of :func:`bytes_to_bits`. Length must be a multiple of 8."""
    if len(bits) % 8:
        raise ValueError(f"need a whole number of bytes, got {len(bits)} bits")
    out = bytearray()
    for index in range(0, len(bits), 8):
        value = 0
        for bit in bits[index : index + 8]:
            value = (value << 1) | (bit & 1)
        out.append(value)
    return bytes(out)


def bits_to_str(bits: list[int], group: int = 8, sep: str = " ") -> str:
    """Render bits as text, grouped for readability: ``01000101 00000000``."""
    raw = "".join(str(bit & 1) for bit in bits)
    if group <= 0:
        return raw
    return sep.join(raw[i : i + group] for i in range(0, len(raw), group))


def str_to_bits(text: str) -> list[int]:
    """Parse a bit string, ignoring any separators the user typed."""
    stray = set(text) - set("01 _-\t\n")
    if stray:
        raise ValueError("not a bit string: unexpected " + "".join(sorted(stray)))
    return [int(char) for char in text if char in "01"]


def flip_bit(data: bytes, index: int) -> bytes:
    """Flip one bit, counting from the MSB of byte 0 -- the error injector."""
    if not 0 <= index < len(data) * 8:
        raise IndexError(f"bit {index} outside a {len(data)}-byte buffer")
    out = bytearray(data)
    out[index // 8] ^= 1 << (7 - index % 8)
    return bytes(out)


def bit_diff(first: bytes, second: bytes) -> list[int]:
    """Bit positions where two buffers differ -- used to highlight corruption."""
    positions = []
    for index in range(min(len(first), len(second)) * 8):
        byte, shift = index // 8, 7 - index % 8
        if (first[byte] >> shift) & 1 != (second[byte] >> shift) & 1:
            positions.append(index)
    return positions


def hexdump(data: bytes, width: int = 16, start: int = 0) -> str:
    """Classic offset / hex / ASCII dump, the shape Wireshark shows."""
    lines = []
    for offset in range(0, len(data), width):
        chunk = data[offset : offset + width]
        half = width // 2
        left = " ".join(f"{b:02x}" for b in chunk[:half])
        right = " ".join(f"{b:02x}" for b in chunk[half:])
        hex_part = f"{left:<{half * 3}} {right}".rstrip()
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{start + offset:04x}  {hex_part:<{width * 3 + 1}}  {text}")
    return "\n".join(lines)


def format_mac(raw: bytes) -> str:
    if len(raw) != 6:
        raise ValueError(f"a MAC address is 6 bytes, got {len(raw)}")
    return ":".join(f"{b:02X}" for b in raw)


def parse_mac(text: str) -> bytes:
    parts = text.replace("-", ":").split(":")
    if len(parts) != 6:
        raise ValueError(f"not a MAC address: {text!r}")
    return bytes(int(part, 16) for part in parts)


def format_ipv4(raw: bytes) -> str:
    if len(raw) != 4:
        raise ValueError(f"an IPv4 address is 4 bytes, got {len(raw)}")
    return ".".join(str(b) for b in raw)


def parse_ipv4(text: str) -> bytes:
    parts = text.strip().split(".")
    if len(parts) != 4:
        raise ValueError(f"not an IPv4 address: {text!r}")
    octets = [int(part) for part in parts]
    if any(not 0 <= octet <= 255 for octet in octets):
        raise ValueError(f"octet out of range in {text!r}")
    return bytes(octets)


def random_mac(rng: random.Random | None = None) -> bytes:
    """A locally administered unicast MAC, so demo addresses look plausible."""
    source = rng or random
    first = (source.getrandbits(8) & 0xFE) | 0x02
    return bytes([first] + [source.getrandbits(8) for _ in range(5)])
