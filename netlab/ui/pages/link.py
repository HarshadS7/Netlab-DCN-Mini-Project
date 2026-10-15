"""Link Lab — error detection, error correction, framing and ARQ.

Module 5.1 and 5.2, and the page that owns CO4. Five tabs, each built around
the same idea: encode something, break it on purpose by clicking a bit, and
watch the receiver's arithmetic notice.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core import bits as bitlib
from ...core.arq.machines import PROTOCOLS, ArqConfig
from ...core.errors import crc, hamming
from ...core.errors.checksum import checksum_steps, internet_checksum
from ...core.layers import datalink
from ..theme import COLORS
from ..widgets.bitgrid import BitGrid
from ..widgets.timeline import ArqTimeline

__all__ = ["LinkPage"]


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "section")
    return label


def _mono(parent: QPlainTextEdit) -> QPlainTextEdit:
    from PySide6.QtGui import QFont

    from ..theme import MONO_FAMILY

    font = QFont(MONO_FAMILY.split(",")[0].strip())
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(9)
    parent.setFont(font)
    parent.setReadOnly(True)
    return parent


def _verdict(label: QLabel, ok: bool, text: str) -> None:
    color = COLORS["good"] if ok else COLORS["bad"]
    mark = "&#10003;" if ok else "&#10007;"
    label.setText(f"<span style='color:{color}'>{mark} {text}</span>")


class LinkPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        title = QLabel("Link Lab")
        title.setProperty("role", "title")
        subtitle = QLabel(
            "Error detection and correction, framing, and the three ARQ protocols. "
            "Click any bit to corrupt it and watch the receiver respond."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.addTab(HammingTab(), "Hamming")
        tabs.addTab(CrcTab(), "CRC")
        tabs.addTab(ChecksumTab(), "Checksum")
        tabs.addTab(FramingTab(), "Framing")
        tabs.addTab(ArqTab(), "ARQ Protocols")
        outer.addWidget(tabs, 1)


# --------------------------------------------------------------------------
# Hamming
# --------------------------------------------------------------------------


class HammingTab(QWidget):
    """Encode, corrupt one bit, and let the syndrome name the guilty position."""

    def __init__(self) -> None:
        super().__init__()
        self._code: hamming.HammingCode | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.data = QLineEdit("1011")
        self.data.setMaximumWidth(220)
        self.encode_button = QPushButton("Encode")
        self.encode_button.setProperty("role", "primary")
        controls.addWidget(QLabel("Data bits"))
        controls.addWidget(self.data)
        controls.addWidget(self.encode_button)
        controls.addStretch(1)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        controls.addWidget(self.title)
        layout.addLayout(controls)

        layout.addWidget(_section("SENT CODEWORD — parity bits sit at positions 1, 2, 4, 8 …"))
        self.sent = BitGrid(one_based=True)
        self.sent.set_editable(False)
        layout.addWidget(self.sent)

        layout.addWidget(_section("RECEIVED CODEWORD — click a bit to flip it"))
        self.received = BitGrid(one_based=True)
        layout.addWidget(self.received)

        self.verdict = QLabel()
        self.verdict.setStyleSheet("font-size: 13px; font-weight: 600; padding: 4px 0;")
        layout.addWidget(self.verdict)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.parity_view = _mono(QPlainTextEdit())
        self.syndrome_view = _mono(QPlainTextEdit())
        for widget, caption in (
            (self.parity_view, "PARITY CONSTRUCTION"),
            (self.syndrome_view, "SYNDROME AT THE RECEIVER"),
        ):
            box = QWidget()
            inner = QVBoxLayout(box)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.addWidget(_section(caption))
            inner.addWidget(widget)
            splitter.addWidget(box)
        layout.addWidget(splitter, 1)

        self.encode_button.clicked.connect(self.encode)
        self.data.returnPressed.connect(self.encode)
        self.received.bitToggled.connect(lambda _: self.check())
        self.encode()

    def encode(self) -> None:
        try:
            data = bitlib.str_to_bits(self.data.text())
            if not data:
                raise ValueError("enter some bits")
            self._code = hamming.encode(data)
        except ValueError as error:
            self.verdict.setText(f"<span style='color:{COLORS['bad']}'>{error}</span>")
            return

        code = self._code
        roles = [
            "parity" if code.is_parity(position) else "data"
            for position in range(1, code.n + 1)
        ]
        self.sent.set_bits(code.codeword, roles)
        self.received.set_bits(code.codeword, roles, set())
        self.title.setText(f"{code.name} — {code.k} data + {code.n - code.k} redundant bits")

        lines = [
            f"r = {code.n - code.k}, chosen as the smallest r with 2^r >= m + r + 1",
            "",
        ]
        for parity in code.parity:
            covered = [p for p in parity.covers if p != parity.position]
            values = "".join(str(code.at(p)) for p in covered)
            lines.append(
                f"{parity.label:>3} checks positions {covered}\n"
                f"     even parity over {values} -> {parity.value}"
            )
        self.parity_view.setPlainText("\n".join(lines))
        self.check()

    def check(self) -> None:
        if self._code is None:
            return
        result = hamming.decode(self.received.bits)
        original = self._code.codeword

        lines = ["Recompute each parity check over the received bits:", ""]
        for position, total, passed in result.checks:
            lines.append(
                f"  r{position:<3} -> {'0 (pass)' if passed else '1 (FAIL)'}"
                f"{'' if passed else f'   contributes {position} to the syndrome'}"
            )
        binary = "".join(str(bit) for bit in result.syndrome_bits)
        lines += ["", f"Syndrome = {binary} binary = {result.syndrome} decimal", ""]
        if result.error_found and result.syndrome <= len(result.received):
            lines.append(f"So position {result.syndrome} is the bad bit. Flip it back.")
        elif result.error_found:
            lines.append("The syndrome points past the codeword — multiple errors.")
        else:
            lines.append("All checks pass — the codeword is accepted as received.")
        self.syndrome_view.setPlainText("\n".join(lines))

        damaged = [
            index for index, (a, b) in enumerate(zip(original, result.received)) if a != b
        ]
        self.received.set_highlight(
            {result.syndrome - 1} if 0 < result.syndrome <= len(original) else set()
        )

        if not damaged:
            _verdict(self.verdict, True, "No errors introduced — syndrome is 0, as expected.")
        elif len(damaged) == 1 and result.corrected == original:
            _verdict(
                self.verdict,
                True,
                f"One bit flipped at position {damaged[0] + 1}. "
                f"{result.summary}. The original data is recovered.",
            )
        else:
            _verdict(
                self.verdict,
                False,
                f"{len(damaged)} bits flipped. A single-error-correcting code cannot fix "
                f"this — it {'mis-corrects position ' + str(result.syndrome) if result.error_found else 'sees nothing wrong'}.",
            )


# --------------------------------------------------------------------------
# CRC
# --------------------------------------------------------------------------


class CrcTab(QWidget):
    """Polynomial long division, written out the way it is done on paper."""

    def __init__(self) -> None:
        super().__init__()
        self._codeword: list[int] = []
        self._generator: list[int] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.data = QLineEdit("1101011011")
        self.data.setMaximumWidth(260)
        self.generator = QComboBox()
        self.generator.addItems(sorted(crc.GENERATORS))
        self.generator.setCurrentText("CRC-8")
        self.encode_button = QPushButton("Encode")
        self.encode_button.setProperty("role", "primary")
        controls.addWidget(QLabel("Data bits"))
        controls.addWidget(self.data)
        controls.addWidget(QLabel("Generator"))
        controls.addWidget(self.generator)
        controls.addWidget(self.encode_button)
        controls.addStretch(1)
        self.polynomial = QLabel()
        self.polynomial.setStyleSheet(f"color: {COLORS['muted']};")
        controls.addWidget(self.polynomial)
        layout.addLayout(controls)

        layout.addWidget(_section("TRANSMITTED CODEWORD — data followed by the remainder"))
        self.sent = BitGrid()
        self.sent.set_editable(False)
        layout.addWidget(self.sent)

        layout.addWidget(_section("RECEIVED CODEWORD — click a bit to flip it"))
        self.received = BitGrid()
        layout.addWidget(self.received)

        self.verdict = QLabel()
        self.verdict.setStyleSheet("font-size: 13px; font-weight: 600; padding: 4px 0;")
        layout.addWidget(self.verdict)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.encode_view = _mono(QPlainTextEdit())
        self.check_view = _mono(QPlainTextEdit())
        for widget, caption in (
            (self.encode_view, "DIVISION AT THE SENDER"),
            (self.check_view, "DIVISION AT THE RECEIVER"),
        ):
            box = QWidget()
            inner = QVBoxLayout(box)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.addWidget(_section(caption))
            inner.addWidget(widget)
            splitter.addWidget(box)
        layout.addWidget(splitter, 1)

        self.encode_button.clicked.connect(self.encode)
        self.data.returnPressed.connect(self.encode)
        self.generator.currentTextChanged.connect(self.encode)
        self.received.bitToggled.connect(lambda _: self.check())
        self.encode()

    @staticmethod
    def _polynomial_text(generator: list[int]) -> str:
        degree = len(generator) - 1
        terms = []
        for index, bit in enumerate(generator):
            if not bit:
                continue
            power = degree - index
            terms.append("1" if power == 0 else ("x" if power == 1 else f"x^{power}"))
        return " + ".join(terms)

    def encode(self) -> None:
        try:
            data = bitlib.str_to_bits(self.data.text())
            generator = crc.generator_bits(self.generator.currentText())
            if len(data) < 1:
                raise ValueError("enter some bits")
            codeword, remainder, steps = crc.crc_encode(data, generator)
        except ValueError as error:
            self.verdict.setText(f"<span style='color:{COLORS['bad']}'>{error}</span>")
            return

        self._codeword, self._generator = codeword, generator
        roles = ["data"] * len(data) + ["remainder"] * len(remainder)
        self.sent.set_bits(codeword, roles)
        self.received.set_bits(codeword, roles, set())
        self.polynomial.setText(self._polynomial_text(generator))

        head = [
            f"Message:     {''.join(map(str, data))}",
            f"Generator:   {''.join(map(str, generator))}  ({self._polynomial_text(generator)})",
            f"Append {len(generator) - 1} zeros, then divide modulo 2:",
            "",
        ]
        self.encode_view.setPlainText(
            "\n".join(head + self._format_steps(steps))
            + f"\n\nRemainder = {''.join(map(str, remainder))}"
            + f"\nTransmit  = {''.join(map(str, codeword))}"
        )
        self.check()

    @staticmethod
    def _format_steps(steps) -> list[str]:
        lines = []
        for step in steps:
            if not step.divided:
                continue  # skip the pure shift rows, they add noise on paper too
            lines.append(f"  pos {step.position:>3}  {step.dividend}")
            lines.append(f"            {step.divisor}   XOR")
            lines.append(f"            {'-' * len(step.result)}")
            lines.append(f"            {step.result}")
            lines.append("")
        return lines

    def check(self) -> None:
        if not self._codeword:
            return
        received = self.received.bits
        ok, remainder, steps = crc.crc_check(received, self._generator)
        damaged = [i for i, (a, b) in enumerate(zip(self._codeword, received)) if a != b]

        text = [
            f"Received: {''.join(map(str, received))}",
            "Divide the whole codeword by the same generator:",
            "",
        ] + self._format_steps(steps)
        text.append(f"Remainder = {''.join(map(str, remainder))}")
        self.check_view.setPlainText("\n".join(text))

        if not damaged:
            _verdict(self.verdict, True, "Remainder is zero — frame accepted.")
        elif ok:
            _verdict(
                self.verdict,
                False,
                f"{len(damaged)} bit(s) flipped but the remainder is still zero. This is an "
                "undetectable error — the error pattern is an exact multiple of the generator.",
            )
        else:
            _verdict(
                self.verdict,
                True,
                f"{len(damaged)} bit(s) flipped and the remainder is non-zero — "
                "error detected, frame discarded.",
            )


# --------------------------------------------------------------------------
# Checksum
# --------------------------------------------------------------------------


class ChecksumTab(QWidget):
    """The 16-bit one's complement sum, carry by carry."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.words = QLineEdit("4500 003C 1C46 4000 4006 0000 0A00 0001 0A00 0002")
        self.compute_button = QPushButton("Compute")
        self.compute_button.setProperty("role", "primary")
        controls.addWidget(QLabel("16-bit words (hex)"))
        controls.addWidget(self.words, 1)
        controls.addWidget(self.compute_button)
        layout.addLayout(controls)

        hint = QLabel(
            "The default is a real IPv4 header with its checksum field zeroed. "
            "Compute it and the answer replaces those zeros."
        )
        hint.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.view = _mono(QPlainTextEdit())
        layout.addWidget(self.view, 1)

        self.verdict = QLabel()
        self.verdict.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(self.verdict)

        self.compute_button.clicked.connect(self.compute)
        self.words.returnPressed.connect(self.compute)
        self.compute()

    def compute(self) -> None:
        try:
            words = [int(token, 16) for token in self.words.text().split()]
            if not words or any(not 0 <= word <= 0xFFFF for word in words):
                raise ValueError
        except ValueError:
            self.verdict.setText(
                f"<span style='color:{COLORS['bad']}'>Enter space-separated 16-bit hex words.</span>"
            )
            return

        data = b"".join(word.to_bytes(2, "big") for word in words)
        steps, checksum = checksum_steps(data)

        lines = ["  #   word    running sum   carry", "  " + "-" * 38]
        for step in steps:
            lines.append(
                f"  {step.index:<3} {step.word_hex}    {step.running_hex}"
                f"          {'yes' if step.carried else ''}"
            )
        lines += [
            "",
            f"Sum (folded to 16 bits)  = {(~checksum) & 0xFFFF:04X}",
            f"One's complement         = {checksum:04X}   <- the checksum",
            "",
            "At the receiver, summing the words *including* the checksum gives",
            "FFFF, whose complement is 0000 — which is how a receiver checks it",
            "without knowing what the sender computed.",
        ]
        self.view.setPlainText("\n".join(lines))

        verified = internet_checksum(data + checksum.to_bytes(2, "big"))
        _verdict(
            self.verdict,
            verified == 0,
            f"Checksum 0x{checksum:04X}; re-summing with it included gives 0x{verified:04X}.",
        )


# --------------------------------------------------------------------------
# Framing
# --------------------------------------------------------------------------


class FramingTab(QWidget):
    """Byte stuffing and bit stuffing, side by side."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        form = QFormLayout()
        self.payload = QLineEdit("A~B}C")
        form.addRow("Payload (~ is the flag byte, } the escape)", self.payload)
        layout.addLayout(form)

        self.view = _mono(QPlainTextEdit())
        layout.addWidget(self.view, 1)

        self.payload.textChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        raw = self.payload.text().encode("utf-8", "replace")
        stuffed = datalink.byte_stuff(raw)
        unstuffed = datalink.byte_unstuff(stuffed)

        original_bits = bitlib.bytes_to_bits(raw)
        stuffed_bits = datalink.bit_stuff(original_bits)
        recovered_bits = datalink.bit_unstuff(stuffed_bits)

        def show(data: bytes) -> str:
            return " ".join(f"{b:02X}" for b in data)

        lines = [
            "CHARACTER (BYTE) STUFFING — variable-size framing over a byte-oriented link",
            "",
            f"  payload   {show(raw)}",
            f"  stuffed   {show(stuffed)}",
            f"  framed    7E {show(stuffed)} 7E",
            f"  recovered {show(unstuffed)}   {'OK' if unstuffed == raw else 'MISMATCH'}",
            "",
            f"  {len(stuffed) - len(raw)} escape byte(s) inserted, because the payload "
            "contained bytes that would otherwise look like a delimiter.",
            "",
            "",
            "BIT STUFFING — the same problem on a bit-oriented link (HDLC)",
            "",
            f"  payload   {bitlib.bits_to_str(original_bits)}",
            f"  stuffed   {bitlib.bits_to_str(stuffed_bits)}",
            f"  recovered {bitlib.bits_to_str(recovered_bits)}   "
            f"{'OK' if recovered_bits == original_bits else 'MISMATCH'}",
            "",
            f"  {len(stuffed_bits) - len(original_bits)} zero bit(s) inserted. A 0 is forced "
            "after every five consecutive 1s, so the flag 01111110 can never appear in data.",
        ]
        self.view.setPlainText("\n".join(lines))


# --------------------------------------------------------------------------
# ARQ
# --------------------------------------------------------------------------


class ArqTab(QWidget):
    """The three protocols, on the same loss pattern, so they can be compared."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.protocol = QComboBox()
        self.protocol.addItems(list(PROTOCOLS))
        self.protocol.setCurrentText("Go-Back-N")
        self.frames = QSpinBox()
        self.frames.setRange(2, 12)
        self.frames.setValue(6)
        self.window = QSpinBox()
        self.window.setRange(1, 8)
        self.window.setValue(4)
        self.lose = QLineEdit("2")
        self.lose.setMaximumWidth(90)
        self.lose.setToolTip("Sequence numbers to lose on their first transmission")

        for label, widget in (
            ("Protocol", self.protocol),
            ("Frames", self.frames),
            ("Window N", self.window),
            ("Lose frames", self.lose),
        ):
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        self.run_button = QPushButton("Run")
        self.run_button.setProperty("role", "primary")
        controls.addWidget(self.run_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.timeline = ArqTimeline()
        splitter.addWidget(self.timeline)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(8, 0, 0, 0)
        side_layout.addWidget(_section("RESULT"))
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.stats.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.stats.setStyleSheet(
            f"background: {COLORS['panel']}; border: 1px solid {COLORS['border']};"
            f"border-radius: 9px; padding: 10px; font-size: 12px;"
        )
        side_layout.addWidget(self.stats)
        side_layout.addWidget(_section("ALL THREE, SAME LOSSES"))
        self.compare = _mono(QPlainTextEdit())
        side_layout.addWidget(self.compare, 1)
        splitter.addWidget(side)
        splitter.setSizes([640, 400])
        layout.addWidget(splitter, 1)

        self.run_button.clicked.connect(self.run)
        self.protocol.currentTextChanged.connect(self.run)
        for spin in (self.frames, self.window):
            spin.valueChanged.connect(self.run)
        self.lose.editingFinished.connect(self.run)
        self.run()

    def _config(self) -> ArqConfig:
        try:
            lost = {int(token) for token in self.lose.text().replace(",", " ").split()}
        except ValueError:
            lost = set()
        return ArqConfig(
            total_frames=self.frames.value(),
            window=self.window.value(),
            lose_data=lost,
            loss_probability=0.0,
        )

    def run(self) -> None:
        config = self._config()
        result = PROTOCOLS[self.protocol.currentText()](config)
        self.timeline.set_result(result)

        self.stats.setText(
            f"<b>{result.protocol}</b><br><br>"
            f"Delivered {len(result.delivered)} frame(s) in "
            f"{result.transmissions} transmission(s).<br>"
            f"Efficiency <b>{result.efficiency:.0f}%</b><br>"
            f"Timeouts: {len(result.timeouts)}<br><br>"
            f"<span style='color:{COLORS['muted']}'>{result.note}</span>"
        )

        rows = [f"{'protocol':<18}{'sent':>6}{'eff':>7}  frames put on the wire", "-" * 64]
        for name, run in PROTOCOLS.items():
            other = run(self._config())
            sequence = " ".join(
                str(arrow.seq) for arrow in other.arrows if arrow.kind == "data"
            )
            rows.append(f"{name:<18}{other.transmissions:>6}{other.efficiency:>6.0f}%  {sequence}")
        rows += [
            "",
            "Lose one frame and the difference is the whole lesson: Go-Back-N",
            "resends everything after the loss, Selective Repeat resends only",
            "the frame that went missing.",
        ]
        self.compare.setPlainText("\n".join(rows))
