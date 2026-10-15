"""Digital-to-analog conversion and the sampling theorem (syllabus 5.3).

ASK, FSK, PSK and QPSK waveforms with their constellation points, plus PCM --
sample, quantise, encode -- and the two data-rate limits every exam asks for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field

__all__ = [
    "Modulated",
    "modulate",
    "SCHEMES",
    "PcmResult",
    "pcm",
    "nyquist_rate",
    "shannon_capacity",
    "tdm",
    "fdm",
]

SAMPLES_PER_BIT = 60


@dataclass
class Modulated:
    name: str
    times: list[float]
    values: list[float]
    bits: list[int]
    constellation: list[tuple[float, float, str]] = dc_field(default_factory=list)
    baud: float = 0.0
    bits_per_symbol: int = 1
    note: str = ""


def _carrier(index: int, samples: int, frequency: float, phase: float, amplitude: float):
    point = index / samples
    return amplitude * math.sin(2 * math.pi * frequency * point + phase)


def ask(bits: list[int]) -> Modulated:
    """Amplitude shift keying: the carrier is present for 1, absent for 0."""
    times, values = [], []
    for position, bit in enumerate(bits):
        for sample in range(SAMPLES_PER_BIT):
            times.append(position + sample / SAMPLES_PER_BIT)
            values.append(_carrier(sample, SAMPLES_PER_BIT, 2.0, 0.0, 1.0 if bit else 0.0))
    return Modulated(
        "ASK",
        times,
        values,
        bits,
        [(0.0, 0.0, "0"), (1.0, 0.0, "1")],
        baud=len(bits),
        note="Only the amplitude carries information, which makes ASK very "
        "vulnerable to noise -- noise is an amplitude change.",
    )


def fsk(bits: list[int]) -> Modulated:
    """Frequency shift keying: one frequency for 1, another for 0."""
    times, values = [], []
    for position, bit in enumerate(bits):
        frequency = 4.0 if bit else 2.0
        for sample in range(SAMPLES_PER_BIT):
            times.append(position + sample / SAMPLES_PER_BIT)
            values.append(_carrier(sample, SAMPLES_PER_BIT, frequency, 0.0, 1.0))
    return Modulated(
        "FSK",
        times,
        values,
        bits,
        [(-1.0, 0.0, "0 (low f)"), (1.0, 0.0, "1 (high f)")],
        baud=len(bits),
        note="Far more robust against noise than ASK, but it needs more "
        "bandwidth because it occupies two frequency bands.",
    )


def psk(bits: list[int]) -> Modulated:
    """Binary phase shift keying: 0 and 180 degrees."""
    times, values = [], []
    for position, bit in enumerate(bits):
        phase = 0.0 if bit else math.pi
        for sample in range(SAMPLES_PER_BIT):
            times.append(position + sample / SAMPLES_PER_BIT)
            values.append(_carrier(sample, SAMPLES_PER_BIT, 2.0, phase, 1.0))
    return Modulated(
        "BPSK",
        times,
        values,
        bits,
        [(-1.0, 0.0, "0"), (1.0, 0.0, "1")],
        baud=len(bits),
        note="Phase carries the bit. Noise has to be large enough to rotate "
        "the phase halfway round before a symbol is misread.",
    )


def qpsk(bits: list[int]) -> Modulated:
    """Quadrature PSK: four phases, so each symbol carries two bits."""
    times, values = [], []
    pairs = [bits[i : i + 2] for i in range(0, len(bits) - len(bits) % 2, 2)]
    phase_for = {
        (0, 0): math.pi / 4,
        (0, 1): 3 * math.pi / 4,
        (1, 1): 5 * math.pi / 4,
        (1, 0): 7 * math.pi / 4,
    }
    for position, pair in enumerate(pairs):
        phase = phase_for[tuple(pair)]
        for sample in range(SAMPLES_PER_BIT * 2):
            times.append(position * 2 + sample / SAMPLES_PER_BIT)
            values.append(_carrier(sample, SAMPLES_PER_BIT, 2.0, phase, 1.0))

    constellation = [
        (math.cos(phase), math.sin(phase), f"{pair[0]}{pair[1]}")
        for pair, phase in phase_for.items()
    ]
    return Modulated(
        "QPSK",
        times,
        values,
        bits,
        constellation,
        baud=len(pairs),
        bits_per_symbol=2,
        note="Four phases means two bits per symbol, so the same baud rate "
        "carries twice the bit rate. This is the trade the Nyquist formula "
        "describes: more levels, more bits, less noise margin.",
    )


SCHEMES = {"ASK": ask, "FSK": fsk, "BPSK": psk, "QPSK": qpsk}


def modulate(scheme: str, bits: list[int]) -> Modulated:
    if scheme not in SCHEMES:
        raise ValueError(f"unknown modulation: {scheme!r}")
    if not bits:
        raise ValueError("nothing to modulate")
    return SCHEMES[scheme](bits)


# --------------------------------------------------------------------------
# PCM — analog to digital
# --------------------------------------------------------------------------


@dataclass
class PcmResult:
    times: list[float]
    analog: list[float]
    sample_times: list[float]
    sample_values: list[float]
    quantised: list[float]
    levels: list[int]
    codes: list[str]
    bits_per_sample: int
    sample_rate: float
    bit_rate: float
    error: list[float] = dc_field(default_factory=list)


def pcm(
    frequency: float = 1.0,
    sample_rate: float = 8.0,
    levels: int = 8,
    duration: float = 2.0,
    amplitude: float = 1.0,
) -> PcmResult:
    """Sample, quantise and encode a sine wave.

    ``sample_rate`` below twice ``frequency`` is deliberately allowed, so the
    page can show what aliasing does rather than just warn about it.
    """
    if levels < 2:
        raise ValueError("need at least two quantisation levels")

    resolution = max(1, int(math.log2(levels)))
    fine = [index / 400.0 for index in range(int(duration * 400))]
    analog = [amplitude * math.sin(2 * math.pi * frequency * t) for t in fine]

    count = max(1, int(sample_rate * duration))
    sample_times = [index / sample_rate for index in range(count)]
    sample_values = [amplitude * math.sin(2 * math.pi * frequency * t) for t in sample_times]

    step = 2 * amplitude / levels
    quantised, indices, codes, error = [], [], [], []
    for value in sample_values:
        index = min(levels - 1, max(0, int((value + amplitude) / step)))
        centre = -amplitude + (index + 0.5) * step
        indices.append(index)
        quantised.append(centre)
        codes.append(format(index, f"0{resolution}b"))
        error.append(centre - value)

    return PcmResult(
        times=fine,
        analog=analog,
        sample_times=sample_times,
        sample_values=sample_values,
        quantised=quantised,
        levels=indices,
        codes=codes,
        bits_per_sample=resolution,
        sample_rate=sample_rate,
        bit_rate=sample_rate * resolution,
        error=error,
    )


# --------------------------------------------------------------------------
# Data rate limits
# --------------------------------------------------------------------------


def nyquist_rate(bandwidth: float, levels: int) -> float:
    """Noiseless channel: C = 2 B log2(L).

    Says nothing about noise, so on paper it lets you reach any rate you like
    by adding levels. Shannon is what stops that.
    """
    if levels < 2:
        raise ValueError("need at least two signal levels")
    return 2 * bandwidth * math.log2(levels)


def shannon_capacity(bandwidth: float, snr_db: float) -> float:
    """Noisy channel: C = B log2(1 + SNR), with SNR given in decibels."""
    snr = 10 ** (snr_db / 10)
    return bandwidth * math.log2(1 + snr)


def levels_for_capacity(bandwidth: float, capacity: float) -> float:
    """How many signal levels Nyquist would need to reach a given capacity."""
    if bandwidth <= 0:
        raise ValueError("bandwidth must be positive")
    return 2 ** (capacity / (2 * bandwidth))


# --------------------------------------------------------------------------
# Multiplexing (syllabus 5.4)
# --------------------------------------------------------------------------


def tdm(sources: list[str], frames: int = 4) -> list[list[str]]:
    """Time division: each source gets the whole bandwidth, in turn."""
    return [[f"{source}{frame}" for source in sources] for frame in range(frames)]


def fdm(sources: list[str], total_bandwidth: float = 12.0, guard: float = 1.0):
    """Frequency division: each source gets its own band, all of the time."""
    if not sources:
        return []
    share = (total_bandwidth - guard * (len(sources) - 1)) / len(sources)
    if share <= 0:
        raise ValueError("guard bands consume the entire bandwidth")
    bands = []
    cursor = 0.0
    for source in sources:
        bands.append((source, cursor, cursor + share))
        cursor += share + guard
    return bands
