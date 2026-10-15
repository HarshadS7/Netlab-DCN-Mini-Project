"""Digital-to-digital conversion: the line coding schemes of syllabus 5.3.

Each encoder returns a step waveform sampled densely enough to draw, plus the
per-bit levels. The interesting cases are the ones that solve a real problem:

* **NRZ-L** is the naive scheme, and a long run of identical bits leaves the
  receiver with no transitions to recover a clock from.
* **Manchester** guarantees a transition in every bit, at the cost of double
  the bandwidth.
* **AMI** keeps the average voltage at zero by alternating polarity, but a long
  run of zeros still has no transitions -- which is what **B8ZS** and **HDB3**
  exist to fix, by deliberately violating the alternation in a pattern the
  receiver can recognise as intentional.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SCHEMES", "Waveform", "encode"]

SAMPLES_PER_BIT = 20


@dataclass
class Waveform:
    """A step waveform plus the commentary the page prints beside it."""

    name: str
    times: list[float]
    levels: list[float]
    bits: list[int]
    note: str = ""
    violations: list[int] = None  # bit positions where polarity was violated

    def __post_init__(self) -> None:
        if self.violations is None:
            self.violations = []


def _steps(levels_per_bit: list[list[float]]) -> tuple[list[float], list[float]]:
    """Expand per-bit level segments into a drawable step waveform."""
    times: list[float] = []
    values: list[float] = []
    for index, segments in enumerate(levels_per_bit):
        span = 1.0 / len(segments)
        for position, level in enumerate(segments):
            start = index + position * span
            end = start + span
            times.extend([start, end])
            values.extend([level, level])
    return times, values


def nrz_l(bits: list[int]) -> Waveform:
    """Non-return to zero, level: 1 is high, 0 is low."""
    segments = [[1.0 if bit else -1.0] for bit in bits]
    times, levels = _steps(segments)
    return Waveform(
        "NRZ-L",
        times,
        levels,
        bits,
        "Level *is* the bit. Simple, but a long run of the same bit gives the "
        "receiver no transition to synchronise its clock on, and the average "
        "voltage drifts away from zero.",
    )


def nrz_i(bits: list[int]) -> Waveform:
    """Non-return to zero, inverted: a 1 causes a transition, a 0 does not."""
    segments = []
    level = -1.0
    for bit in bits:
        if bit:
            level = -level
        segments.append([level])
    times, levels = _steps(segments)
    return Waveform(
        "NRZ-I",
        times,
        levels,
        bits,
        "A 1 inverts the level, a 0 leaves it alone. Immune to a swapped pair "
        "of wires, since only the change matters -- but a run of zeros is still "
        "featureless.",
    )


def manchester(bits: list[int]) -> Waveform:
    """Manchester: every bit has a mid-bit transition (IEEE 802.3 convention)."""
    segments = [[-1.0, 1.0] if bit else [1.0, -1.0] for bit in bits]
    times, levels = _steps(segments)
    return Waveform(
        "Manchester",
        times,
        levels,
        bits,
        "Every bit carries its own transition in the middle, so the clock is "
        "recoverable from any data at all. The price is double the bandwidth: "
        "the signal rate is twice the bit rate.",
    )


def differential_manchester(bits: list[int]) -> Waveform:
    """Mid-bit transition always; a 0 also transitions at the bit boundary."""
    segments = []
    level = 1.0
    for bit in bits:
        if not bit:
            level = -level  # transition at the start for a 0
        segments.append([level, -level])
        level = -level
    times, levels = _steps(segments)
    return Waveform(
        "Diff. Manchester",
        times,
        levels,
        bits,
        "Always a mid-bit transition for the clock; a 0 adds a transition at "
        "the start of the bit and a 1 does not. Combines self-clocking with "
        "polarity independence.",
    )


def ami(bits: list[int]) -> Waveform:
    """Alternate mark inversion: 0 is zero volts, 1 alternates +/-."""
    segments = []
    polarity = -1.0
    for bit in bits:
        if bit:
            polarity = -polarity
            segments.append([polarity])
        else:
            segments.append([0.0])
    times, levels = _steps(segments)
    return Waveform(
        "AMI",
        times,
        levels,
        bits,
        "Ones alternate between + and -, so the average voltage is zero and no "
        "DC builds up on the line. A long run of zeros, though, is just silence.",
    )


def _substitute(bits: list[int], run: int, encoder) -> Waveform:
    return encoder(bits, run)


def b8zs(bits: list[int]) -> Waveform:
    """B8ZS: replace eight zeros with a pattern containing two violations.

    The substitution ``000VB0VB`` deliberately breaks the alternation twice.
    Two violations in that pattern cannot arise from real data, so the receiver
    recognises them and puts the eight zeros back.
    """
    segments: list[list[float]] = []
    violations: list[int] = []
    polarity = -1.0
    index = 0

    while index < len(bits):
        if bits[index] == 0 and bits[index : index + 8] == [0] * 8:
            # 000 then V B 0 V B, where V repeats the last polarity.
            for _ in range(3):
                segments.append([0.0])
            v1 = polarity
            violations.append(len(segments))
            segments.append([v1])            # V - violation
            polarity = -v1
            segments.append([polarity])      # B - correct alternation
            segments.append([0.0])
            v2 = polarity
            violations.append(len(segments))
            segments.append([v2])            # V - violation
            polarity = -v2
            segments.append([polarity])      # B
            index += 8
            continue

        if bits[index]:
            polarity = -polarity
            segments.append([polarity])
        else:
            segments.append([0.0])
        index += 1

    times, levels = _steps(segments)
    return Waveform(
        "B8ZS",
        times,
        levels,
        bits,
        "Eight consecutive zeros are replaced by 000VB0VB. V repeats the "
        "previous polarity, which real data can never do -- so the receiver "
        "knows the pattern was inserted and restores the zeros. Used on T1.",
        violations,
    )


def hdb3(bits: list[int]) -> Waveform:
    """HDB3: the European equivalent, substituting after four zeros."""
    segments: list[list[float]] = []
    violations: list[int] = []
    polarity = -1.0
    ones_since_substitution = 0
    index = 0

    while index < len(bits):
        if bits[index : index + 4] == [0, 0, 0, 0]:
            if ones_since_substitution % 2 == 0:
                # Even number of ones since the last substitution: B00V
                polarity = -polarity
                segments.append([polarity])  # B
                segments.extend([[0.0], [0.0]])
                violations.append(len(segments))
                segments.append([polarity])  # V, repeats polarity
            else:
                # Odd: 000V
                segments.extend([[0.0], [0.0], [0.0]])
                violations.append(len(segments))
                segments.append([polarity])  # V, repeats polarity
            ones_since_substitution = 0
            index += 4
            continue

        if bits[index]:
            polarity = -polarity
            segments.append([polarity])
            ones_since_substitution += 1
        else:
            segments.append([0.0])
        index += 1

    times, levels = _steps(segments)
    return Waveform(
        "HDB3",
        times,
        levels,
        bits,
        "Four zeros are replaced by 000V or B00V, chosen so the number of ones "
        "between substitutions stays odd and no DC accumulates. Used on E1.",
        violations,
    )


SCHEMES = {
    "NRZ-L": nrz_l,
    "NRZ-I": nrz_i,
    "Manchester": manchester,
    "Diff. Manchester": differential_manchester,
    "AMI": ami,
    "B8ZS": b8zs,
    "HDB3": hdb3,
}


def encode(scheme: str, bits: list[int]) -> Waveform:
    if scheme not in SCHEMES:
        raise ValueError(f"unknown line code: {scheme!r}")
    if not bits:
        raise ValueError("nothing to encode")
    return SCHEMES[scheme](bits)
