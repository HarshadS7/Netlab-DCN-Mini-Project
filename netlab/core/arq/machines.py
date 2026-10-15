"""ARQ protocols for noisy channels: Stop-and-Wait, Go-Back-N, Selective Repeat.

Each protocol is simulated as a discrete-event timeline and returns the list of
arrows the Link Lab page draws -- sender on the left, receiver on the right,
time running downward, exactly like the diagram in the textbook.

Losses are given as an explicit set of sequence numbers rather than drawn at
random, so a demo is reproducible and the classic teaching picture (lose frame
2, watch Go-Back-N resend 2, 3 and 4 while Selective Repeat resends only 2) can
be set up deliberately.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field as dc_field

__all__ = ["ArqConfig", "Arrow", "ArqResult", "stop_and_wait", "go_back_n", "selective_repeat"]


@dataclass
class ArqConfig:
    """Timing and loss settings shared by all three protocols."""

    total_frames: int = 6
    window: int = 4
    timeout: float = 8.0
    transmission: float = 1.0
    propagation: float = 2.0
    lose_data: set[int] = dc_field(default_factory=set)
    lose_acks: set[int] = dc_field(default_factory=set)
    loss_probability: float = 0.0
    seed: int | None = 12345
    max_attempts: int = 4

    @property
    def one_way(self) -> float:
        return self.transmission + self.propagation


@dataclass
class Arrow:
    """One frame or acknowledgement crossing the link."""

    seq: int
    start: float
    end: float
    kind: str  # "data" | "ack" | "nak"
    lost: bool = False
    label: str = ""
    note: str = ""
    discarded: bool = False  # arrived, but the receiver threw it away

    @property
    def direction(self) -> str:
        return "forward" if self.kind == "data" else "back"


@dataclass
class ArqResult:
    """Everything the timeline view and the statistics panel need."""

    protocol: str
    arrows: list[Arrow]
    timeouts: list[tuple[int, float]] = dc_field(default_factory=list)
    delivered: list[int] = dc_field(default_factory=list)
    total_time: float = 0.0
    transmissions: int = 0
    window_trace: list[tuple[float, int, int]] = dc_field(default_factory=list)
    note: str = ""

    @property
    def efficiency(self) -> float:
        """Useful frames delivered per frame actually put on the wire."""
        if not self.transmissions:
            return 0.0
        return len(self.delivered) / self.transmissions * 100


class _Loss:
    """Decides what gets lost -- scripted first, then random if configured."""

    def __init__(self, config: ArqConfig) -> None:
        self.config = config
        self._rng = random.Random(config.seed)
        self._seen_data: set[int] = set()
        self._seen_ack: set[int] = set()

    def data_lost(self, seq: int) -> bool:
        # A scripted loss applies to the first attempt only, so the protocol
        # can recover -- otherwise every run ends in max_attempts.
        if seq in self.config.lose_data and seq not in self._seen_data:
            self._seen_data.add(seq)
            return True
        return self._rng.random() < self.config.loss_probability

    def ack_lost(self, seq: int) -> bool:
        if seq in self.config.lose_acks and seq not in self._seen_ack:
            self._seen_ack.add(seq)
            return True
        return self._rng.random() < self.config.loss_probability


def stop_and_wait(config: ArqConfig) -> ArqResult:
    """Send one frame, wait for its acknowledgement, repeat.

    Simple and correct, and the reason it is slow is visible in the picture:
    the sender spends almost all its time idle waiting for the round trip.
    """
    loss = _Loss(config)
    arrows: list[Arrow] = []
    timeouts: list[tuple[int, float]] = []
    delivered: list[int] = []
    transmissions = 0

    time = 0.0
    seq = 0
    while seq < config.total_frames:
        attempts = 0
        acked = False
        while not acked and attempts < config.max_attempts:
            attempts += 1
            transmissions += 1
            send_at, arrive_at = time, time + config.one_way
            data_lost = loss.data_lost(seq)
            arrows.append(
                Arrow(
                    seq=seq,
                    start=send_at,
                    end=arrive_at,
                    kind="data",
                    lost=data_lost,
                    label=f"Frame {seq % 2}",
                    note="Sequence numbers alternate 0/1 -- one bit is enough here",
                )
            )
            if data_lost:
                time = send_at + config.timeout
                timeouts.append((seq, time))
                continue

            ack_lost = loss.ack_lost(seq)
            arrows.append(
                Arrow(
                    seq=seq,
                    start=arrive_at,
                    end=arrive_at + config.one_way,
                    kind="ack",
                    lost=ack_lost,
                    label=f"ACK {(seq + 1) % 2}",
                    note="Acknowledges the frame just received",
                )
            )
            if ack_lost:
                time = send_at + config.timeout
                timeouts.append((seq, time))
                # The receiver already has it; the duplicate will be discarded.
                continue

            delivered.append(seq)
            time = arrive_at + config.one_way
            acked = True
        seq += 1

    return ArqResult(
        protocol="Stop-and-Wait",
        arrows=arrows,
        timeouts=timeouts,
        delivered=delivered,
        total_time=time,
        transmissions=transmissions,
        note="One frame in flight at a time. Utilisation collapses as the "
        "bandwidth-delay product grows.",
    )


def go_back_n(config: ArqConfig) -> ArqResult:
    """Keep N frames in flight; on a timeout, resend the whole window.

    The receiver accepts frames strictly in order, so one loss forces every
    frame after it to be sent twice -- wasteful on a good link, but the
    receiver needs no buffer at all.
    """
    loss = _Loss(config)
    arrows: list[Arrow] = []
    timeouts: list[tuple[int, float]] = []
    delivered: list[int] = []
    window_trace: list[tuple[float, int, int]] = []
    transmissions = 0

    base = 0
    time = 0.0
    rounds = 0
    expected = 0

    while base < config.total_frames and rounds < config.total_frames * config.max_attempts:
        rounds += 1
        window_trace.append((time, base, min(base + config.window, config.total_frames)))

        sent: list[tuple[int, float, float, bool]] = []
        send_at = time
        for offset in range(config.window):
            seq = base + offset
            if seq >= config.total_frames:
                break
            transmissions += 1
            arrive_at = send_at + config.one_way
            data_lost = loss.data_lost(seq)
            sent.append((seq, send_at, arrive_at, data_lost))
            send_at += config.transmission

        highest_acked = base - 1
        for seq, start, arrive, data_lost in sent:
            in_order = seq == expected
            arrows.append(
                Arrow(
                    seq=seq,
                    start=start,
                    end=arrive,
                    kind="data",
                    lost=data_lost,
                    discarded=not data_lost and not in_order,
                    label=f"Frame {seq}",
                    note=""
                    if data_lost
                    else (
                        "Accepted in order"
                        if in_order
                        else f"Out of order -- receiver wants {expected}, so this is discarded"
                    ),
                )
            )
            if data_lost or not in_order:
                continue

            expected += 1
            delivered.append(seq)
            highest_acked = seq
            ack_lost = loss.ack_lost(seq)
            arrows.append(
                Arrow(
                    seq=seq,
                    start=arrive,
                    end=arrive + config.one_way,
                    kind="ack",
                    lost=ack_lost,
                    label=f"ACK {seq}",
                    note="Cumulative -- it acknowledges every frame up to this one",
                )
            )

        if highest_acked >= base:
            base = highest_acked + 1
            time = max(arrow.end for arrow in arrows if not arrow.lost)
        else:
            time = sent[0][1] + config.timeout if sent else time + config.timeout
            timeouts.append((base, time))

    return ArqResult(
        protocol="Go-Back-N",
        arrows=arrows,
        timeouts=timeouts,
        delivered=delivered,
        total_time=time,
        transmissions=transmissions,
        window_trace=window_trace,
        note="One loss costs the whole window. The receiver needs no buffer, "
        "but the link carries the same frames twice.",
    )


def selective_repeat(config: ArqConfig) -> ArqResult:
    """Keep N frames in flight and retransmit only the ones that went missing.

    The receiver buffers out-of-order frames and acknowledges each one
    individually, so a single loss costs a single retransmission -- at the
    price of a real buffer and more bookkeeping at both ends.
    """
    loss = _Loss(config)
    arrows: list[Arrow] = []
    timeouts: list[tuple[int, float]] = []
    delivered: list[int] = []
    window_trace: list[tuple[float, int, int]] = []
    transmissions = 0

    acked: set[int] = set()
    buffered: set[int] = set()
    base = 0
    time = 0.0
    rounds = 0

    while base < config.total_frames and rounds < config.total_frames * config.max_attempts:
        rounds += 1
        window_trace.append((time, base, min(base + config.window, config.total_frames)))

        pending = [
            seq
            for seq in range(base, min(base + config.window, config.total_frames))
            if seq not in acked
        ]
        if not pending:
            break

        send_at = time
        latest = time
        progressed = False
        for seq in pending:
            transmissions += 1
            arrive_at = send_at + config.one_way
            data_lost = loss.data_lost(seq)
            arrows.append(
                Arrow(
                    seq=seq,
                    start=send_at,
                    end=arrive_at,
                    kind="data",
                    lost=data_lost,
                    label=f"Frame {seq}",
                    note=""
                    if data_lost
                    else ("Buffered out of order" if seq != base else "Accepted in order"),
                )
            )
            send_at += config.transmission

            if data_lost:
                continue

            buffered.add(seq)
            ack_lost = loss.ack_lost(seq)
            arrows.append(
                Arrow(
                    seq=seq,
                    start=arrive_at,
                    end=arrive_at + config.one_way,
                    kind="ack",
                    lost=ack_lost,
                    label=f"ACK {seq}",
                    note="Acknowledges this frame only",
                )
            )
            if not ack_lost:
                acked.add(seq)
                progressed = True
                latest = max(latest, arrive_at + config.one_way)

        # Deliver whatever prefix is now contiguous.
        while base in buffered and base in acked:
            delivered.append(base)
            base += 1

        if progressed:
            time = latest
        else:
            time = time + config.timeout
            timeouts.append((base, time))

    return ArqResult(
        protocol="Selective Repeat",
        arrows=arrows,
        timeouts=timeouts,
        delivered=delivered,
        total_time=time,
        transmissions=transmissions,
        window_trace=window_trace,
        note="Only the lost frame is resent. The receiver must buffer and "
        "reorder, and the window may be at most half the sequence space.",
    )


PROTOCOLS = {
    "Stop-and-Wait": stop_and_wait,
    "Go-Back-N": go_back_n,
    "Selective Repeat": selective_repeat,
}
