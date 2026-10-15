"""Hamming code: the one that corrects rather than merely detects.

Generalised to any (n, k), not just the (7, 4) case, because the syllabus asks
for the method and not one worked example. Positions are numbered from 1 on the
left, parity bits sit at the powers of two, and the syndrome read as a binary
number *is* the position of the corrupted bit -- which is the whole trick, and
the thing the Link Lab page is built to show.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

__all__ = [
    "ParityBit",
    "HammingCode",
    "redundant_bits_needed",
    "encode",
    "decode",
    "DecodeResult",
]


def redundant_bits_needed(data_length: int) -> int:
    """Smallest r satisfying 2^r >= m + r + 1."""
    r = 0
    while 2**r < data_length + r + 1:
        r += 1
    return r


def _is_power_of_two(position: int) -> bool:
    return position & (position - 1) == 0


def _covered_by(parity_position: int, total: int) -> list[int]:
    """Positions whose index has this parity bit's bit set.

    Parity bit 1 covers 1,3,5,7...; parity bit 2 covers 2,3,6,7...; and so on.
    """
    return [
        position
        for position in range(1, total + 1)
        if position & parity_position and not _is_power_of_two(position)
        or (position == parity_position)
    ]


@dataclass(frozen=True)
class ParityBit:
    """One parity bit, the positions it checks, and the value it took."""

    position: int
    covers: list[int]
    value: int

    @property
    def label(self) -> str:
        return f"r{self.position}"


@dataclass
class HammingCode:
    """An encoded codeword, with enough detail to explain itself."""

    data_bits: list[int]
    codeword: list[int]  # index 0 holds position 1
    parity: list[ParityBit]

    @property
    def n(self) -> int:
        return len(self.codeword)

    @property
    def k(self) -> int:
        return len(self.data_bits)

    @property
    def name(self) -> str:
        return f"Hamming({self.n}, {self.k})"

    def at(self, position: int) -> int:
        return self.codeword[position - 1]

    def is_parity(self, position: int) -> bool:
        return _is_power_of_two(position)

    def data_positions(self) -> list[int]:
        return [p for p in range(1, self.n + 1) if not _is_power_of_two(p)]


def encode(data_bits: list[int]) -> HammingCode:
    """Interleave data and parity, then compute each parity bit as even parity."""
    if not data_bits:
        raise ValueError("nothing to encode")
    if any(bit not in (0, 1) for bit in data_bits):
        raise ValueError("data must be bits")

    k = len(data_bits)
    r = redundant_bits_needed(k)
    n = k + r

    codeword = [0] * (n + 1)  # 1-based; index 0 unused
    source = iter(data_bits)
    for position in range(1, n + 1):
        if not _is_power_of_two(position):
            codeword[position] = next(source)

    parity: list[ParityBit] = []
    for exponent in range(r):
        position = 2**exponent
        covers = _covered_by(position, n)
        value = 0
        for covered in covers:
            if covered != position:
                value ^= codeword[covered]
        codeword[position] = value
        parity.append(ParityBit(position=position, covers=covers, value=value))

    return HammingCode(data_bits=list(data_bits), codeword=codeword[1:], parity=parity)


@dataclass
class DecodeResult:
    """What the receiver worked out from a possibly corrupted codeword."""

    received: list[int]
    corrected: list[int]
    syndrome: int
    syndrome_bits: list[int]
    checks: list[tuple[int, int, bool]] = dc_field(default_factory=list)
    data_bits: list[int] = dc_field(default_factory=list)

    @property
    def error_found(self) -> bool:
        return self.syndrome != 0

    @property
    def error_position(self) -> int | None:
        return self.syndrome if self.syndrome else None

    @property
    def summary(self) -> str:
        if not self.error_found:
            return "Syndrome 0 -- no error detected"
        if self.syndrome > len(self.received):
            return (
                f"Syndrome {self.syndrome} points past the end of the codeword -- "
                "more than one bit is wrong and this code cannot fix it"
            )
        return (
            f"Syndrome {self.syndrome} -- bit at position {self.syndrome} was wrong, "
            "and has been flipped back"
        )


def decode(received: list[int]) -> DecodeResult:
    """Recompute every parity check; the failures spell out the bad position.

    A single-bit error is corrected. Two-bit errors are detected in most cases
    but "corrected" to the wrong position -- a genuine limitation of the code,
    not of this implementation, and one the Link Lab page lets you demonstrate.
    """
    n = len(received)
    if n == 0:
        raise ValueError("nothing to decode")

    codeword = [0] + list(received)  # 1-based
    syndrome = 0
    checks: list[tuple[int, int, bool]] = []
    exponent = 0
    while 2**exponent <= n:
        position = 2**exponent
        covers = _covered_by(position, n)
        total = 0
        for covered in covers:
            total ^= codeword[covered]
        failed = total != 0
        if failed:
            syndrome += position
        checks.append((position, total, not failed))
        exponent += 1

    corrected = list(received)
    if 0 < syndrome <= n:
        corrected[syndrome - 1] ^= 1

    data_bits = [
        corrected[position - 1]
        for position in range(1, n + 1)
        if not _is_power_of_two(position)
    ]

    width = max(1, exponent)
    syndrome_bits = [(syndrome >> shift) & 1 for shift in range(width - 1, -1, -1)]

    return DecodeResult(
        received=list(received),
        corrected=corrected,
        syndrome=syndrome,
        syndrome_bits=syndrome_bits,
        checks=checks,
        data_bits=data_bits,
    )
