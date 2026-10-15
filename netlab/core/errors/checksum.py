"""The 16-bit one's complement Internet checksum (RFC 1071).

Used for real by the IPv4, TCP and UDP header builders, and stepped through
field by field on the Link Lab page. :func:`checksum_steps` records the running
sum after every 16-bit word so the wraparound carry -- the part students
reliably get wrong -- is visible rather than asserted.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["internet_checksum", "verify_checksum", "ChecksumStep", "checksum_steps"]


def _fold(total: int) -> int:
    """Add the carry bits back in until the sum fits in 16 bits."""
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return total


def internet_checksum(data: bytes) -> int:
    """One's complement of the one's complement sum of 16-bit words.

    An odd-length buffer is padded with a zero byte for the calculation only,
    exactly as RFC 1071 specifies.
    """
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for index in range(0, len(data), 2):
        total = _fold(total + int.from_bytes(data[index : index + 2], "big"))
    return (~total) & 0xFFFF


def verify_checksum(data: bytes) -> bool:
    """A buffer with its checksum in place sums to 0xFFFF, so this returns 0."""
    return internet_checksum(data) == 0


@dataclass(frozen=True)
class ChecksumStep:
    """One 16-bit word added to the running sum, for the step-by-step view."""

    index: int
    word: int
    running: int
    carried: bool

    @property
    def word_hex(self) -> str:
        return f"{self.word:04X}"

    @property
    def running_hex(self) -> str:
        return f"{self.running:04X}"


def checksum_steps(data: bytes) -> tuple[list[ChecksumStep], int]:
    """Return every intermediate sum plus the final checksum."""
    if len(data) % 2:
        data += b"\x00"
    steps: list[ChecksumStep] = []
    total = 0
    for position, index in enumerate(range(0, len(data), 2)):
        word = int.from_bytes(data[index : index + 2], "big")
        raw = total + word
        total = _fold(raw)
        steps.append(
            ChecksumStep(index=position, word=word, running=total, carried=raw > 0xFFFF)
        )
    return steps, (~total) & 0xFFFF
