"""Transport Lab — connection management, flow control and congestion control.

Module 3. The handshake tab draws the state machine alongside the segments, so
a state name is always attached to the segment that caused it; the congestion
tab draws the cwnd sawtooth that the whole of TCP's behaviour reduces to.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.transport_sim import (
    CongestionConfig,
    congestion_trace,
    handshake,
    sliding_window,
    teardown,
)
from ..theme import COLORS, MONO_FAMILY

__all__ = ["TransportPage"]

pg.setConfigOption("background", COLORS["panel"])
pg.setConfigOption("foreground", COLORS["muted"])
pg.setConfigOption("antialias", True)


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "section")
    return label


def _mono_view() -> QPlainTextEdit:
    view = QPlainTextEdit()
    font = QFont(MONO_FAMILY.split(",")[0].strip())
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(9)
    view.setFont(font)
    view.setReadOnly(True)
    view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    return view


class TransportPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        title = QLabel("Transport Lab")
        title.setProperty("role", "title")
        subtitle = QLabel(
            "How TCP opens a connection, keeps a fast sender from swamping a slow "
            "receiver, and backs off when the network itself is the bottleneck."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.addTab(HandshakeTab(), "Handshake and Teardown")
        tabs.addTab(WindowTab(), "Sliding Window")
        tabs.addTab(CongestionTab(), "Congestion Control")
        outer.addWidget(tabs, 1)


class HandshakeTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._events = handshake()
        self._index = 0

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.phase = QComboBox()
        self.phase.addItems(["Connection setup (3-way)", "Connection release (4-way)"])
        self.step_button = QPushButton("Step")
        self.step_button.setProperty("role", "primary")
        self.reset_button = QPushButton("Reset")
        controls.addWidget(QLabel("Phase"))
        controls.addWidget(self.phase)
        controls.addWidget(self.step_button)
        controls.addWidget(self.reset_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.addWidget(_section("SEGMENTS"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Direction", "Segment", "Client → Server state"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        left_layout.addWidget(self.table)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.note.setMinimumHeight(70)
        self.note.setStyleSheet(
            f"background: {COLORS['panel']}; border: 1px solid {COLORS['border']};"
            f"border-radius: 9px; padding: 10px; color: {COLORS['muted']}; font-size: 12px;"
        )
        left_layout.addWidget(self.note)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.addWidget(_section("STATE MACHINE"))
        self.states = _mono_view()
        right_layout.addWidget(self.states)
        splitter.addWidget(right)
        splitter.setSizes([700, 440])
        layout.addWidget(splitter, 1)

        self.phase.currentTextChanged.connect(self._switch)
        self.step_button.clicked.connect(self._step)
        self.reset_button.clicked.connect(self._reset)
        self._refresh()

    def _switch(self, text: str) -> None:
        self._events = handshake() if text.startswith("Connection setup") else teardown()
        self._index = 0
        self._refresh()

    def _step(self) -> None:
        self._index = min(self._index + 1, len(self._events))
        self._refresh()

    def _reset(self) -> None:
        self._index = 0
        self._refresh()

    def _refresh(self) -> None:
        shown = self._events[: self._index]
        self.table.setRowCount(0)
        mono = QFont(MONO_FAMILY.split(",")[0].strip())
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)

        for event in shown:
            row = self.table.rowCount()
            self.table.insertRow(row)
            arrow = "→" if event.direction == "client-server" else "←"
            cells = [
                str(event.step),
                f"client {arrow} server",
                event.label,
                f"{event.client_state} / {event.server_state}",
            ]
            for column, value in enumerate(cells):
                cell = QTableWidgetItem(value)
                if column in (2, 3):
                    cell.setFont(mono)
                if column == 2:
                    cell.setForeground(QColor(COLORS["accent"]))
                self.table.setItem(row, column, cell)

        if shown:
            self.note.setText(f"<b>Step {shown[-1].step}</b> — {shown[-1].note}")
        else:
            self.note.setText(
                "Press Step to send the first segment. Nothing has been exchanged yet, "
                "so the client is CLOSED and the server is LISTEN."
            )

        client = shown[-1].client_state if shown else "CLOSED"
        server = shown[-1].server_state if shown else "LISTEN"
        setup = self.phase.currentText().startswith("Connection setup")
        ladder = (
            [
                "CLOSED",
                "  | active open: send SYN",
                "SYN_SENT",
                "  | receive SYN+ACK, send ACK",
                "ESTABLISHED",
            ]
            if setup
            else [
                "ESTABLISHED",
                "  | close(): send FIN",
                "FIN_WAIT_1",
                "  | receive ACK",
                "FIN_WAIT_2",
                "  | receive FIN, send ACK",
                "TIME_WAIT",
                "  | wait 2*MSL",
                "CLOSED",
            ]
        )
        lines = ["CLIENT", ""]
        for entry in ladder:
            marker = " <== now" if entry.strip() == client else ""
            lines.append(f"  {entry}{marker}")

        server_ladder = (
            [
                "LISTEN",
                "  | receive SYN, send SYN+ACK",
                "SYN_RECEIVED",
                "  | receive ACK",
                "ESTABLISHED",
            ]
            if setup
            else [
                "ESTABLISHED",
                "  | receive FIN, send ACK",
                "CLOSE_WAIT",
                "  | close(): send FIN",
                "LAST_ACK",
                "  | receive ACK",
                "CLOSED",
            ]
        )
        lines += ["", "SERVER", ""]
        for entry in server_ladder:
            marker = " <== now" if entry.strip() == server else ""
            lines.append(f"  {entry}{marker}")

        lines += [
            "",
            "",
            (
                "Three segments, not four: the server's ACK of the client's SYN\n"
                "travels in the same segment as its own SYN."
                if setup
                else "Four segments, not three: each direction closes separately,\n"
                "because a host that has finished sending may still be receiving.\n"
                "TIME_WAIT then holds the port for 2*MSL so a delayed duplicate\n"
                "cannot be mistaken for data on a new connection."
            ),
        ]
        self.states.setPlainText("\n".join(lines))


class WindowTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._frames = sliding_window()
        self._index = 0

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.total = QSpinBox()
        self.total.setRange(4, 20)
        self.total.setValue(12)
        self.window = QSpinBox()
        self.window.setRange(1, 10)
        self.window.setValue(4)
        self.step_button = QPushButton("Step")
        self.step_button.setProperty("role", "primary")
        self.reset_button = QPushButton("Reset")
        for label, widget in (("Frames", self.total), ("Window", self.window)):
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        controls.addWidget(self.step_button)
        controls.addWidget(self.reset_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.view = _mono_view()
        layout.addWidget(self.view, 1)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {COLORS['muted']}; font-size: 12px;")
        layout.addWidget(self.note)

        for widget in (self.total, self.window):
            widget.valueChanged.connect(self._rebuild)
        self.step_button.clicked.connect(self._step)
        self.reset_button.clicked.connect(self._reset)
        self._rebuild()

    def _rebuild(self) -> None:
        self._frames = sliding_window(self.total.value(), self.window.value())
        self._index = 0
        self._refresh()

    def _step(self) -> None:
        self._index = (self._index + 1) % len(self._frames)
        self._refresh()

    def _reset(self) -> None:
        self._index = 0
        self._refresh()

    def _refresh(self) -> None:
        frame = self._frames[self._index]
        total = self.total.value()

        symbols = []
        for index in range(total):
            if index in frame.acked:
                symbols.append(" ✓ ")
            elif index in frame.in_flight:
                symbols.append("[#]")
            elif index in frame.usable:
                symbols.append("[ ]")
            else:
                symbols.append(" . ")

        numbers = "".join(f"{index:^3}" for index in range(total))
        window_start = frame.base
        window_end = min(frame.base + frame.window, total)
        bar = "".join(
            "===" if window_start <= index < window_end else "   " for index in range(total)
        )

        self.view.setPlainText(
            "\n".join(
                [
                    f"Step {self._index} of {len(self._frames) - 1}",
                    "",
                    f"  frame   {numbers}",
                    f"  state   {''.join(symbols)}",
                    f"  window  {bar}",
                    "",
                    f"  send base   = {frame.base}",
                    f"  next seq    = {frame.next_seq}",
                    f"  in flight   = {len(frame.in_flight)} of {frame.window}",
                    "",
                    "  ✓   acknowledged, the window has moved past it",
                    "  [#] sent, waiting for an acknowledgement",
                    "  [ ] inside the window, not yet sent",
                    "  .   outside the window, the sender may not touch it",
                ]
            )
        )
        self.note.setText(
            f"{frame.note}. The window is the receiver's advertised capacity — this is "
            "flow control, protecting a slow receiver, and it is a completely separate "
            "mechanism from the congestion window, which protects the network."
        )


class CongestionTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.rounds = QSpinBox()
        self.rounds.setRange(10, 80)
        self.rounds.setValue(40)
        self.ssthresh = QSpinBox()
        self.ssthresh.setRange(2, 64)
        self.ssthresh.setValue(16)
        self.dup_button = QPushButton("Add triple duplicate ACK")
        self.timeout_button = QPushButton("Add timeout")
        self.reset_button = QPushButton("Reset events")
        for label, widget in (("Rounds", self.rounds), ("Initial ssthresh", self.ssthresh)):
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        controls.addWidget(self.dup_button)
        controls.addWidget(self.timeout_button)
        controls.addWidget(self.reset_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self._dup = {12, 28}
        self._timeout = {20}

        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.setLabel("bottom", "round trip")
        self.plot.setLabel("left", "cwnd (segments)")
        self.plot.addLegend(offset=(10, 10))
        layout.addWidget(self.plot, 1)

        self.legend = QLabel()
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet(
            f"background: {COLORS['panel']}; border: 1px solid {COLORS['border']};"
            f"border-radius: 9px; padding: 10px; font-size: 12px;"
        )
        layout.addWidget(self.legend)

        for widget in (self.rounds, self.ssthresh):
            widget.valueChanged.connect(self.refresh)
        self.dup_button.clicked.connect(self._add_dup)
        self.timeout_button.clicked.connect(self._add_timeout)
        self.reset_button.clicked.connect(self._reset_events)
        self.refresh()

    def _next_slot(self) -> int:
        used = self._dup | self._timeout
        candidate = 8
        while candidate in used and candidate < self.rounds.value():
            candidate += 1
        return candidate

    def _add_dup(self) -> None:
        self._dup.add(self._next_slot())
        self.refresh()

    def _add_timeout(self) -> None:
        self._timeout.add(self._next_slot())
        self.refresh()

    def _reset_events(self) -> None:
        self._dup, self._timeout = {12, 28}, {20}
        self.refresh()

    def refresh(self) -> None:
        trace = congestion_trace(
            CongestionConfig(
                rounds=self.rounds.value(),
                initial_ssthresh=float(self.ssthresh.value()),
                triple_dup_rounds=set(self._dup),
                timeout_rounds=set(self._timeout),
            )
        )

        xs = [point.round for point in trace]
        cwnd = [point.cwnd for point in trace]
        ssthresh = [point.ssthresh for point in trace]

        self.plot.clear()
        self.plot.plot(xs, cwnd, pen=pg.mkPen(COLORS["accent"], width=2.5), name="cwnd")
        self.plot.plot(
            xs,
            ssthresh,
            pen=pg.mkPen(COLORS["warn"], width=1.6, style=Qt.PenStyle.DashLine),
            name="ssthresh",
        )

        for point in trace:
            if not point.event:
                continue
            colour = COLORS["bad"] if "Timeout" in point.event else COLORS["warn"]
            self.plot.addItem(
                pg.InfiniteLine(pos=point.round, angle=90, pen=pg.mkPen(colour, width=1.2))
            )
            text = pg.TextItem(
                "timeout" if "Timeout" in point.event else "3 dup ACK",
                color=colour,
                anchor=(0, 1),
            )
            text.setPos(point.round, max(cwnd) * 0.98)
            self.plot.addItem(text)

        events = [point for point in trace if point.event]
        rows = "<br>".join(f"round {point.round}: {point.event}" for point in events)
        self.legend.setText(
            f"<b style='color:{COLORS['accent']}'>cwnd</b> doubles every round trip while "
            f"below ssthresh (slow start — exponential, despite the name), then grows by "
            f"one segment per round trip (congestion avoidance — additive increase).<br><br>"
            f"{rows}<br><br>"
            f"<span style='color:{COLORS['muted']}'>The two loss signals are treated "
            f"differently on purpose: duplicate ACKs prove segments are still arriving, so "
            f"Reno halves the window and continues; a timeout proves nothing is arriving, "
            f"so it drops to one segment and starts over. That asymmetry is the whole of "
            f"additive-increase / multiplicative-decrease.</span>"
        )
