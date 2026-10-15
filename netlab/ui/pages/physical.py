"""Physical Lab — signals, encoding, modulation and multiplexing.

Syllabus 5.3 and 5.4. Everything here is a picture, because that is how these
topics are actually understood: the shape of a Manchester waveform explains
self-clocking far faster than a paragraph about it can.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core import bits as bitlib
from ...core.signals import line_coding as lc
from ...core.signals import modulation as mod
from ..theme import COLORS, MONO_FAMILY

__all__ = ["PhysicalPage"]

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


class PhysicalPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(6)

        title = QLabel("Physical Lab")
        title.setProperty("role", "title")
        subtitle = QLabel(
            "How bits become signals: line coding, modulation, sampling, and the two "
            "formulas that cap how fast any of it can go."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.addTab(LineCodingTab(), "Line Coding")
        tabs.addTab(ModulationTab(), "Modulation")
        tabs.addTab(PcmTab(), "PCM")
        tabs.addTab(LimitsTab(), "Data Rate Limits")
        tabs.addTab(MultiplexingTab(), "Multiplexing")
        outer.addWidget(tabs, 1)


class LineCodingTab(QWidget):
    """Every scheme stacked on one shared time axis, so they can be compared."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.bits = QLineEdit("0100110")
        self.bits.setMaximumWidth(300)
        controls.addWidget(QLabel("Bit stream"))
        controls.addWidget(self.bits)
        preset = QComboBox()
        preset.addItems(
            [
                "Custom",
                "Long run of zeros (B8ZS/HDB3)",
                "Long run of ones",
                "Alternating",
            ]
        )
        controls.addWidget(QLabel("Preset"))
        controls.addWidget(preset)
        controls.addStretch(1)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.plots = pg.GraphicsLayoutWidget()
        splitter.addWidget(self.plots)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(8, 0, 0, 0)
        side_layout.addWidget(_section("WHAT EACH SCHEME SOLVES"))
        self.notes = _mono_view()
        self.notes.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        side_layout.addWidget(self.notes)
        splitter.addWidget(side)
        splitter.setSizes([760, 400])
        layout.addWidget(splitter, 1)

        self._presets = {
            "Long run of zeros (B8ZS/HDB3)": "1000000001",
            "Long run of ones": "0111111110",
            "Alternating": "10101010",
        }
        preset.currentTextChanged.connect(self._apply_preset)
        self.bits.textChanged.connect(self.refresh)
        self.refresh()

    def _apply_preset(self, name: str) -> None:
        if name in self._presets:
            self.bits.setText(self._presets[name])

    def refresh(self) -> None:
        try:
            bits = bitlib.str_to_bits(self.bits.text())
        except ValueError:
            return
        if not bits:
            return

        self.plots.clear()
        notes = []
        previous = None

        for index, name in enumerate(lc.SCHEMES):
            waveform = lc.encode(name, bits)
            plot = self.plots.addPlot(row=index, col=0)
            plot.setMenuEnabled(False)
            plot.setMouseEnabled(x=False, y=False)
            plot.hideButtons()
            plot.setYRange(-1.6, 1.6)
            plot.getAxis("left").setWidth(110)
            plot.getAxis("left").setTicks([[(-1, ""), (0, name), (1, "")]])
            plot.showGrid(x=True, y=False, alpha=0.18)
            if previous is not None:
                plot.setXLink(previous)
            previous = plot

            plot.plot(
                waveform.times,
                waveform.levels,
                pen=pg.mkPen(COLORS["accent"], width=2),
            )
            # Bit boundaries, so a level can be read back to its bit.
            for boundary in range(len(waveform.levels) // 2 + 1):
                plot.addLine(
                    x=boundary, pen=pg.mkPen(COLORS["border"], width=1, style=Qt.PenStyle.DotLine)
                )
            for position in waveform.violations:
                plot.addLine(
                    x=position + 0.5, pen=pg.mkPen(COLORS["bad"], width=2)
                )
            if index < len(lc.SCHEMES) - 1:
                plot.getAxis("bottom").setStyle(showValues=False)

            notes.append(f"{name}\n{waveform.note}\n")

        # Label the bits along the top plot.
        top = self.plots.getItem(0, 0)
        for position, bit in enumerate(bits):
            text = pg.TextItem(str(bit), color=COLORS["text"], anchor=(0.5, 0.5))
            text.setPos(position + 0.5, 1.35)
            top.addItem(text)

        self.notes.setPlainText("\n".join(notes))


class ModulationTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.scheme = QComboBox()
        self.scheme.addItems(list(mod.SCHEMES))
        self.bits = QLineEdit("01001101")
        self.bits.setMaximumWidth(260)
        controls.addWidget(QLabel("Scheme"))
        controls.addWidget(self.scheme)
        controls.addWidget(QLabel("Bits"))
        controls.addWidget(self.bits)
        controls.addStretch(1)
        self.rates = QLabel()
        self.rates.setStyleSheet("font-weight: 600;")
        controls.addWidget(self.rates)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.wave = pg.PlotWidget()
        self.wave.setMenuEnabled(False)
        self.wave.showGrid(x=True, y=True, alpha=0.18)
        self.wave.setLabel("bottom", "symbol time")
        splitter.addWidget(self.wave)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.addWidget(_section("CONSTELLATION"))
        self.constellation = pg.PlotWidget()
        self.constellation.setMenuEnabled(False)
        self.constellation.setAspectLocked(True)
        self.constellation.showGrid(x=True, y=True, alpha=0.25)
        self.constellation.setXRange(-1.6, 1.6)
        self.constellation.setYRange(-1.6, 1.6)
        right_layout.addWidget(self.constellation)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.note.setStyleSheet(f"color: {COLORS['muted']}; font-size: 12px;")
        self.note.setMinimumHeight(90)
        right_layout.addWidget(self.note)
        splitter.addWidget(right)
        splitter.setSizes([700, 420])
        layout.addWidget(splitter, 1)

        self.scheme.currentTextChanged.connect(self.refresh)
        self.bits.textChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        try:
            bits = bitlib.str_to_bits(self.bits.text())
            result = mod.modulate(self.scheme.currentText(), bits)
        except ValueError:
            return

        self.wave.clear()
        self.wave.plot(result.times, result.values, pen=pg.mkPen(COLORS["accent"], width=2))
        boundary_step = 2 if result.bits_per_symbol == 2 else 1
        for position in range(0, len(bits) + 1, boundary_step):
            self.wave.addLine(
                x=position, pen=pg.mkPen(COLORS["border"], width=1, style=Qt.PenStyle.DotLine)
            )

        self.constellation.clear()
        if result.constellation:
            xs = [point[0] for point in result.constellation]
            ys = [point[1] for point in result.constellation]
            self.constellation.plot(
                xs,
                ys,
                pen=None,
                symbol="o",
                symbolSize=13,
                symbolBrush=COLORS["good"],
                symbolPen=None,
            )
            for x, y, label in result.constellation:
                text = pg.TextItem(label, color=COLORS["text"], anchor=(0.5, 1.4))
                text.setPos(x, y)
                self.constellation.addItem(text)

        self.rates.setText(
            f"{len(bits)} bits · {result.baud:g} baud · "
            f"{result.bits_per_symbol} bit/symbol"
        )
        self.note.setText(result.note)


class PcmTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.frequency = QDoubleSpinBox()
        self.frequency.setRange(0.5, 6.0)
        self.frequency.setValue(1.0)
        self.frequency.setSingleStep(0.5)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(1.0, 40.0)
        self.rate.setValue(8.0)
        self.levels = QSpinBox()
        self.levels.setRange(2, 64)
        self.levels.setValue(8)
        for label, widget in (
            ("Signal frequency (Hz)", self.frequency),
            ("Sampling rate (Hz)", self.rate),
            ("Quantisation levels", self.levels),
        ):
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.verdict.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.verdict)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.addLegend(offset=(-10, 10))
        self.plot.setLabel("bottom", "time (s)")
        splitter.addWidget(self.plot)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.addWidget(_section("ENCODED SAMPLES"))
        self.codes = _mono_view()
        right_layout.addWidget(self.codes)
        splitter.addWidget(right)
        splitter.setSizes([740, 400])
        layout.addWidget(splitter, 1)

        for widget in (self.frequency, self.rate, self.levels):
            widget.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        frequency = self.frequency.value()
        rate = self.rate.value()
        result = mod.pcm(frequency=frequency, sample_rate=rate, levels=self.levels.value())

        self.plot.clear()
        self.plot.plot(
            result.times, result.analog, pen=pg.mkPen(COLORS["muted"], width=1),
            name="original signal",
        )
        self.plot.plot(
            result.sample_times, result.sample_values, pen=None, symbol="o",
            symbolSize=7, symbolBrush=COLORS["accent"], symbolPen=None, name="samples",
        )
        self.plot.plot(
            result.sample_times, result.quantised, pen=pg.mkPen(COLORS["good"], width=2),
            stepMode=False, name="quantised",
        )

        nyquist = 2 * frequency
        if rate < nyquist:
            self.verdict.setText(
                f"<span style='color:{COLORS['bad']}'>&#10007; Aliasing: sampling at "
                f"{rate:g} Hz is below the Nyquist rate of {nyquist:g} Hz. The samples "
                "fit a different, lower-frequency wave and the original can never be "
                "recovered.</span>"
            )
        else:
            self.verdict.setText(
                f"<span style='color:{COLORS['good']}'>&#10003; Sampling at {rate:g} Hz, "
                f"at or above the Nyquist rate of {nyquist:g} Hz — the original is "
                f"recoverable.</span> <span style='color:{COLORS['muted']}'>"
                f"{result.bits_per_sample} bits per sample gives "
                f"{result.bit_rate:g} bps.</span>"
            )

        lines = [
            f"{len(result.sample_values)} samples, {result.bits_per_sample} bits each",
            f"bit rate = {rate:g} Hz x {result.bits_per_sample} = {result.bit_rate:g} bps",
            "",
            f"  {'t':>6}  {'sampled':>9}  {'level':>6}  code",
        ]
        for index, time in enumerate(result.sample_times[:24]):
            lines.append(
                f"  {time:>6.3f}  {result.sample_values[index]:>9.3f}  "
                f"{result.levels[index]:>6}  {result.codes[index]}"
            )
        if len(result.sample_times) > 24:
            lines.append(f"  … {len(result.sample_times) - 24} more")
        lines += [
            "",
            "The gap between a sample and its quantised value is quantisation",
            "error. More levels shrink it but cost more bits per sample.",
        ]
        self.codes.setPlainText("\n".join(lines))


class LimitsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.bandwidth = QSpinBox()
        self.bandwidth.setRange(100, 1_000_000)
        self.bandwidth.setValue(3000)
        self.bandwidth.setSingleStep(500)
        self.levels = QSpinBox()
        self.levels.setRange(2, 256)
        self.levels.setValue(4)
        self.snr = QDoubleSpinBox()
        self.snr.setRange(0.0, 60.0)
        self.snr.setValue(30.0)
        for label, widget in (
            ("Bandwidth (Hz)", self.bandwidth),
            ("Signal levels", self.levels),
            ("SNR (dB)", self.snr),
        ):
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.result.setStyleSheet(
            f"background: {COLORS['panel']}; border: 1px solid {COLORS['border']};"
            "border-radius: 9px; padding: 14px; font-size: 13px;"
        )
        layout.addWidget(self.result)

        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.setLabel("bottom", "SNR (dB)")
        self.plot.setLabel("left", "capacity (bps)")
        self.plot.addLegend(offset=(10, 10))
        layout.addWidget(self.plot, 1)

        for widget in (self.bandwidth, self.levels, self.snr):
            widget.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        bandwidth = self.bandwidth.value()
        levels = self.levels.value()
        snr_db = self.snr.value()

        nyquist = mod.nyquist_rate(bandwidth, levels)
        shannon = mod.shannon_capacity(bandwidth, snr_db)
        usable = min(nyquist, shannon)
        needed = mod.levels_for_capacity(bandwidth, shannon)

        self.result.setText(
            f"<b>Nyquist</b> (noiseless): C = 2 × B × log₂(L) = 2 × {bandwidth} × "
            f"log₂({levels}) = <b>{nyquist:,.0f} bps</b><br>"
            f"<b>Shannon</b> (noisy): C = B × log₂(1 + SNR) = {bandwidth} × "
            f"log₂(1 + {10 ** (snr_db / 10):,.0f}) = <b>{shannon:,.0f} bps</b><br><br>"
            f"<span style='color:{COLORS['good']}'>Usable rate is the lower of the two: "
            f"<b>{usable:,.0f} bps</b></span><br><br>"
            f"<span style='color:{COLORS['muted']}'>Nyquist alone would let you reach any "
            f"rate by adding levels, which is why it is only half the story. At this SNR "
            f"the most levels worth using is about {needed:,.0f} — beyond that the "
            f"receiver cannot tell them apart through the noise.</span>"
        )

        xs = [value / 2 for value in range(0, 121)]
        self.plot.clear()
        self.plot.plot(
            xs,
            [mod.shannon_capacity(bandwidth, x) for x in xs],
            pen=pg.mkPen(COLORS["good"], width=2),
            name="Shannon limit",
        )
        self.plot.plot(
            xs,
            [nyquist] * len(xs),
            pen=pg.mkPen(COLORS["accent"], width=2, style=Qt.PenStyle.DashLine),
            name=f"Nyquist at L={levels}",
        )
        marker = pg.InfiniteLine(
            pos=snr_db, angle=90, pen=pg.mkPen(COLORS["warn"], width=1.4)
        )
        self.plot.addItem(marker)


class MultiplexingTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.sources = QSpinBox()
        self.sources.setRange(2, 6)
        self.sources.setValue(3)
        controls.addWidget(QLabel("Sources"))
        controls.addWidget(self.sources)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.view = _mono_view()
        layout.addWidget(self.view, 1)

        self.sources.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        names = [chr(ord("A") + index) for index in range(self.sources.value())]
        frames = mod.tdm(names, frames=4)
        bands = mod.fdm(names)

        lines = [
            "TIME DIVISION MULTIPLEXING",
            "  Every source gets the whole bandwidth, but only for its own slot.",
            "",
            "  " + "".join(f"|{'frame ' + str(i):^{len(names) * 5}}" for i in range(4)) + "|",
            "  " + "".join("|" + "".join(f"{slot:^5}" for slot in frame) for frame in frames) + "|",
            "",
            "  A source with nothing to send still owns its slot, so the slot goes",
            "  out empty -- which is why synchronous TDM wastes capacity on bursty",
            "  traffic, and why statistical TDM exists.",
            "",
            "",
            "FREQUENCY DIVISION MULTIPLEXING",
            "  Every source gets its own band, all of the time.",
            "",
        ]
        scale = 4
        for name, low, high in bands:
            width = int((high - low) * scale)
            lines.append(
                f"  {name}  {low:>5.1f} - {high:<5.1f} kHz  "
                + "#" * width
            )
        lines += [
            "",
            "  The gaps between the bars are guard bands: unused frequency kept",
            "  empty so that one channel's signal cannot bleed into its neighbour.",
            "  They are pure overhead, and the price of never having to coordinate",
            "  who transmits when.",
        ]
        self.view.setPlainText("\n".join(lines))
