"""Cyclic redundancy check, in both flavours this project needs.

There are deliberately two implementations here, and the difference matters:

* :func:`crc_remainder` is the textbook polynomial long division taught in
  Forouzan -- zero initial value, no reflection, no final XOR. It records every
  XOR step so the Link Lab page can render the division the way it is worked on
  paper, and it is what an exam answer expects.

* :func:`crc32_ieee` is the real IEEE 802.3 CRC-32 used as the Ethernet frame
  check sequence -- reflected in and out, initial value all ones, final XOR all
  ones. It is what Wireshark expects, and it satisfies the standard check value
  ``CRC32("123456789") == 0xCBF43926``.

Using the textbook version for a frame check sequence would produce a frame
Wireshark rejects, so the two are kept apart on purpose.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from ..bits import bits_to_str, bytes_to_bits

__all__ = [
    "GENERATORS",
    "DivisionStep",
    "crc_remainder",
    "crc_encode",
    "crc_check",
    "crc32_ieee",
]


# Generator polynomials as bit strings, most significant term first.
GENERATORS: dict[str, str] = {
    "CRC-8": "100000111",  # x^8 + x^2 + x + 1
    "CRC-10": "11000110101",  # x^10 + x^9 + x^5 + x^4 + x^2 + 1
    "CRC-12": "1100000001111",  # x^12 + x^11 + x^3 + x^2 + x + 1
    "CRC-16": "11000000000000101",  # x^16 + x^15 + x^2 + 1
    "CRC-CCITT": "10001000000100001",  # x^16 + x^12 + x^5 + 1
}


@dataclass(frozen=True)
class DivisionStep:
    """One subtraction in the long division, as it would be written by hand."""

    position: int
    dividend: str
    divisor: str
    result: str
    divided: bool

    @property
    def note(self) -> str:
        return "XOR with generator" if self.divided else "leading 0, shift down"


def crc_remainder(
    data_bits: list[int], generator_bits: list[int]
) -> tuple[list[int], list[DivisionStep]]:
    """Divide ``data_bits`` by ``generator_bits`` modulo 2.

    Returns the remainder (one bit shorter than the generator) and the trace of
    every step. The caller is responsible for having already appended the zero
    padding when encoding.
    """
    if len(generator_bits) < 2:
        raise ValueError("a generator polynomial needs at least two bits")
    if generator_bits[0] != 1:
        raise ValueError("a generator polynomial must start with 1")
    if len(data_bits) < len(generator_bits):
        raise ValueError("message is shorter than the generator")

    width = len(generator_bits)
    working = list(data_bits)
    steps: list[DivisionStep] = []

    for position in range(len(data_bits) - width + 1):
        window = working[position : position + width]
        divided = window[0] == 1
        if divided:
            for offset in range(width):
                working[position + offset] ^= generator_bits[offset]
        steps.append(
            DivisionStep(
                position=position,
                dividend=bits_to_str(window, group=0),
                divisor=bits_to_str(generator_bits if divided else [0] * width, group=0),
                result=bits_to_str(working[position : position + width], group=0),
                divided=divided,
            )
        )

    return working[-(width - 1) :], steps


def crc_encode(
    data_bits: list[int], generator_bits: list[int]
) -> tuple[list[int], list[int], list[DivisionStep]]:
    """Append the CRC to the message. Returns (codeword, remainder, steps)."""
    padded = list(data_bits) + [0] * (len(generator_bits) - 1)
    remainder, steps = crc_remainder(padded, generator_bits)
    return list(data_bits) + remainder, remainder, steps


def crc_check(
    codeword_bits: list[int], generator_bits: list[int]
) -> tuple[bool, list[int], list[DivisionStep]]:
    """Divide a received codeword. A non-zero remainder means an error."""
    remainder, steps = crc_remainder(list(codeword_bits), generator_bits)
    return not any(remainder), remainder, steps


def crc32_ieee(data: bytes) -> int:
    """IEEE 802.3 CRC-32, as used for the Ethernet frame check sequence."""
    return zlib.crc32(data) & 0xFFFFFFFF


def generator_bits(name_or_bits: str) -> list[int]:
    """Look up a named generator, or parse a literal bit string."""
    text = GENERATORS.get(name_or_bits, name_or_bits)
    bits = [int(char) for char in text if char in "01"]
    if not bits:
        raise ValueError(f"unknown generator: {name_or_bits!r}")
    return bits


def bits_of(data: bytes) -> list[int]:
    """Convenience re-export so callers need not import from two modules."""
    return bytes_to_bits(data)
