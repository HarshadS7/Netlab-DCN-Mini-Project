"""A simulated transmission channel: the part that cannot be real.

Corrupting individual bits on a live NIC needs raw sockets and administrator
rights, so this is where NetLab stops being real and says so. Everything it
does, though, it does to the actual frame bytes -- a flipped bit here is what
makes the receiver's CRC genuinely fail in :mod:`netlab.core.stack`.

Delays follow the standard model from syllabus 5.3: transmission delay is
frame size over bandwidth, propagation delay is distance over signal speed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field as dc_field

from .bits import bit_diff, flip_bit

__all__ = ["ChannelConfig", "Transmission", "Channel"]

# Roughly 2/3 c, the usual figure for copper and fibre.
SIGNAL_SPEED_M_PER_S = 2.0e8


@dataclass
class ChannelConfig:
    """Everything the Packet Journey sliders control."""

    bit_error_rate: float = 0.0
    burst_length: int = 1
    loss_probability: float = 0.0
    bandwidth_bps: float = 1_000_000
    distance_m: float = 1_000.0
    seed: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.bit_error_rate <= 1.0:
            raise ValueError("bit error rate must be a probability")
        if not 0.0 <= self.loss_probability <= 1.0:
            raise ValueError("loss probability must be a probability")
        if self.bandwidth_bps <= 0:
            raise ValueError("bandwidth must be positive")
        if self.burst_length < 1:
            raise ValueError("burst length must be at least 1")


@dataclass
class Transmission:
    """The outcome of putting one frame on the wire."""

    sent: bytes
    received: bytes
    delivered: bool
    corrupted_bits: list[int] = dc_field(default_factory=list)
    transmission_delay_ms: float = 0.0
    propagation_delay_ms: float = 0.0

    @property
    def total_delay_ms(self) -> float:
        return self.transmission_delay_ms + self.propagation_delay_ms

    @property
    def corrupted(self) -> bool:
        return bool(self.corrupted_bits)

    @property
    def summary(self) -> str:
        if not self.delivered:
            return "Lost in transit -- nothing arrived"
        if self.corrupted:
            positions = ", ".join(str(bit) for bit in self.corrupted_bits[:6])
            more = "" if len(self.corrupted_bits) <= 6 else f" and {len(self.corrupted_bits) - 6} more"
            return f"{len(self.corrupted_bits)} bit(s) flipped at {positions}{more}"
        return "Arrived intact"


class Channel:
    """Applies loss, bit errors and delay to a frame."""

    def __init__(self, config: ChannelConfig | None = None) -> None:
        self.config = config or ChannelConfig()
        self._rng = random.Random(self.config.seed)

    def reseed(self, seed: int | None = None) -> None:
        """Reset the generator so a demo can be repeated exactly."""
        self._rng = random.Random(self.config.seed if seed is None else seed)

    def transmit(self, frame: bytes) -> Transmission:
        config = self.config
        bits = len(frame) * 8

        transmission_delay_ms = bits / config.bandwidth_bps * 1000
        propagation_delay_ms = config.distance_m / SIGNAL_SPEED_M_PER_S * 1000

        if self._rng.random() < config.loss_probability:
            return Transmission(
                sent=frame,
                received=b"",
                delivered=False,
                transmission_delay_ms=transmission_delay_ms,
                propagation_delay_ms=propagation_delay_ms,
            )

        received = frame
        index = 0
        while index < bits:
            if self._rng.random() < config.bit_error_rate:
                # A burst takes out several adjacent bits, which is what real
                # impulse noise does -- and what a single-bit code cannot fix.
                for offset in range(config.burst_length):
                    if index + offset < bits:
                        received = flip_bit(received, index + offset)
                index += config.burst_length
            else:
                index += 1

        return Transmission(
            sent=frame,
            received=received,
            delivered=True,
            corrupted_bits=bit_diff(frame, received),
            transmission_delay_ms=transmission_delay_ms,
            propagation_delay_ms=propagation_delay_ms,
        )

    def corrupt_at(
        self, frame: bytes, positions: list[int], *, refresh_fcs: bool = False
    ) -> Transmission:
        """Flip exactly these bits -- for a deterministic, repeatable demo.

        ``refresh_fcs`` recomputes the Ethernet frame check sequence over the
        damaged frame, which models corruption happening *inside a router*
        rather than on the wire. This is not a cheat: Ethernet's FCS is
        per-hop, so every router strips the frame, routes the packet and builds
        a fresh frame with a fresh FCS. Damage done in a router's memory is
        therefore signed off as valid by the next hop's FCS, and only the
        end-to-end IP and TCP checksums can still catch it.

        It is also the only way to *see* those checksums do their job, since an
        intact FCS otherwise catches every error first.
        """
        received = frame
        for position in positions:
            received = flip_bit(received, position)

        if refresh_fcs and len(received) > 4:
            from .errors.crc import crc32_ieee

            body = received[:-4]
            received = body + crc32_ieee(body).to_bytes(4, "little")

        bits = len(frame) * 8
        return Transmission(
            sent=frame,
            received=received,
            delivered=True,
            corrupted_bits=sorted(set(positions)),
            transmission_delay_ms=bits / self.config.bandwidth_bps * 1000,
            propagation_delay_ms=self.config.distance_m / SIGNAL_SPEED_M_PER_S * 1000,
        )
