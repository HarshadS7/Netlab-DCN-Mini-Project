"""TCP mechanics: connection setup and teardown, and congestion control.

The congestion model is TCP Reno, because Reno is what the syllabus describes
and what every cwnd sawtooth diagram is drawn from. The two loss signals behave
differently on purpose, and that difference is the point:

* **Three duplicate ACKs** means segments are still getting through, so Reno
  halves the window and carries on (fast recovery).
* **A timeout** means nothing is getting through, so Reno drops the window to
  one segment and starts slow start again.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

__all__ = [
    "HandshakeEvent",
    "handshake",
    "teardown",
    "TCP_STATES",
    "CongestionConfig",
    "CwndPoint",
    "congestion_trace",
    "WindowFrame",
    "sliding_window",
]


# --------------------------------------------------------------------------
# Connection setup and teardown
# --------------------------------------------------------------------------

TCP_STATES = [
    "CLOSED",
    "LISTEN",
    "SYN_SENT",
    "SYN_RECEIVED",
    "ESTABLISHED",
    "FIN_WAIT_1",
    "FIN_WAIT_2",
    "CLOSE_WAIT",
    "LAST_ACK",
    "TIME_WAIT",
]


@dataclass
class HandshakeEvent:
    """One segment, and the state each end is in once it has been processed."""

    step: int
    direction: str  # "client-server" | "server-client"
    flags: list[str]
    seq: int
    ack: int | None
    client_state: str
    server_state: str
    note: str

    @property
    def label(self) -> str:
        flags = "+".join(self.flags)
        parts = [f"seq={self.seq}"]
        if self.ack is not None:
            parts.append(f"ack={self.ack}")
        return f"{flags} {' '.join(parts)}"


def handshake(client_isn: int = 1000, server_isn: int = 5000) -> list[HandshakeEvent]:
    """The three-way handshake.

    Three segments and not two, because both directions need their initial
    sequence number acknowledged and the server's ACK of the client rides along
    with its own SYN.
    """
    return [
        HandshakeEvent(
            1,
            "client-server",
            ["SYN"],
            client_isn,
            None,
            "SYN_SENT",
            "LISTEN",
            "Client picks an initial sequence number and asks to synchronise. "
            "SYN consumes one sequence number even though it carries no data.",
        ),
        HandshakeEvent(
            2,
            "server-client",
            ["SYN", "ACK"],
            server_isn,
            client_isn + 1,
            "SYN_SENT",
            "SYN_RECEIVED",
            "The server acknowledges the client's SYN and sends its own in the "
            "same segment -- which is why this is three segments, not four.",
        ),
        HandshakeEvent(
            3,
            "client-server",
            ["ACK"],
            client_isn + 1,
            server_isn + 1,
            "ESTABLISHED",
            "ESTABLISHED",
            "The client acknowledges the server's SYN. Both ends are now open "
            "and data can flow in either direction.",
        ),
    ]


def teardown(client_seq: int = 1001, server_seq: int = 5001) -> list[HandshakeEvent]:
    """The four-way close.

    Four segments because TCP connections close one direction at a time: a
    party that has finished sending may still need to receive.
    """
    return [
        HandshakeEvent(
            1,
            "client-server",
            ["FIN", "ACK"],
            client_seq,
            server_seq,
            "FIN_WAIT_1",
            "ESTABLISHED",
            "The client has no more data. It can still receive.",
        ),
        HandshakeEvent(
            2,
            "server-client",
            ["ACK"],
            server_seq,
            client_seq + 1,
            "FIN_WAIT_2",
            "CLOSE_WAIT",
            "The server acknowledges, but does not close yet -- it may still "
            "have data to send. This is the half-open state.",
        ),
        HandshakeEvent(
            3,
            "server-client",
            ["FIN", "ACK"],
            server_seq,
            client_seq + 1,
            "TIME_WAIT",
            "LAST_ACK",
            "The server has now finished too.",
        ),
        HandshakeEvent(
            4,
            "client-server",
            ["ACK"],
            client_seq + 1,
            server_seq + 1,
            "TIME_WAIT",
            "CLOSED",
            "The client acknowledges and waits 2*MSL before closing, so a "
            "delayed duplicate cannot be mistaken for part of a new connection.",
        ),
    ]


# --------------------------------------------------------------------------
# Congestion control
# --------------------------------------------------------------------------


@dataclass
class CongestionConfig:
    rounds: int = 40
    initial_ssthresh: float = 16.0
    triple_dup_rounds: set[int] = dc_field(default_factory=lambda: {12, 28})
    timeout_rounds: set[int] = dc_field(default_factory=lambda: {20})
    max_cwnd: float = 64.0


@dataclass
class CwndPoint:
    """The window at one round trip."""

    round: int
    cwnd: float
    ssthresh: float
    phase: str
    event: str = ""


def congestion_trace(config: CongestionConfig | None = None) -> list[CwndPoint]:
    """Walk TCP Reno through slow start, AIMD, fast recovery and timeouts."""
    settings = config or CongestionConfig()
    cwnd = 1.0
    ssthresh = settings.initial_ssthresh
    points: list[CwndPoint] = []

    for round_number in range(settings.rounds + 1):
        if round_number in settings.timeout_rounds:
            ssthresh = max(2.0, cwnd / 2)
            cwnd = 1.0
            points.append(
                CwndPoint(
                    round_number,
                    cwnd,
                    ssthresh,
                    "slow start",
                    f"Timeout — ssthresh set to {ssthresh:g}, window collapses to 1",
                )
            )
            continue

        if round_number in settings.triple_dup_rounds:
            ssthresh = max(2.0, cwnd / 2)
            cwnd = ssthresh
            points.append(
                CwndPoint(
                    round_number,
                    cwnd,
                    ssthresh,
                    "fast recovery",
                    f"Three duplicate ACKs — halved to {cwnd:g}, no slow start "
                    "because segments are still arriving",
                )
            )
            continue

        phase = "slow start" if cwnd < ssthresh else "congestion avoidance"
        points.append(CwndPoint(round_number, cwnd, ssthresh, phase))

        # Exponential while below the threshold, then strictly linear.
        cwnd = cwnd * 2 if phase == "slow start" else cwnd + 1
        cwnd = min(cwnd, settings.max_cwnd)

    return points


# --------------------------------------------------------------------------
# Sliding window
# --------------------------------------------------------------------------


@dataclass
class WindowFrame:
    """One snapshot of the sender's window."""

    step: int
    base: int
    next_seq: int
    window: int
    acked: list[int]
    in_flight: list[int]
    usable: list[int]
    note: str


def sliding_window(total: int = 12, window: int = 4) -> list[WindowFrame]:
    """Walk a sender's window across a sequence space.

    Three regions matter: bytes sent and acknowledged (the window has moved
    past them), bytes sent but not yet acknowledged (in flight), and bytes the
    window still allows but which have not been sent.
    """
    frames: list[WindowFrame] = []
    base = 0
    next_seq = 0
    step = 0

    while base < total:
        # Fill the window.
        while next_seq < min(base + window, total):
            next_seq += 1
            frames.append(
                WindowFrame(
                    step=step,
                    base=base,
                    next_seq=next_seq,
                    window=window,
                    acked=list(range(base)),
                    in_flight=list(range(base, next_seq)),
                    usable=list(range(next_seq, min(base + window, total))),
                    note=f"Sent frame {next_seq - 1}; {next_seq - base} of {window} in flight",
                )
            )
            step += 1

        # An acknowledgement slides the window forward.
        base += 1
        frames.append(
            WindowFrame(
                step=step,
                base=base,
                next_seq=next_seq,
                window=window,
                acked=list(range(base)),
                in_flight=list(range(base, next_seq)),
                usable=list(range(next_seq, min(base + window, total))),
                note=f"ACK received; window slides to {base}, one more slot opens",
            )
        )
        step += 1

    return frames
