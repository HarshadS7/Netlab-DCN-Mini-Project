"""A hex dump that knows which layer owns each byte.

Custom-painted rather than built on a text widget, because this view has to do
three things a QTextEdit makes awkward: tint each byte by its owning layer,
outline the bytes a channel error damaged, and turn a click into a field
selection. A fixed character grid makes all three straightforward.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QWidget

from ..theme import COLORS, MONO_FAMILY

__all__ = ["ByteRange", "HexView"]

BYTES_PER_ROW = 16


@dataclass(frozen=True)
class ByteRange:
    """A half-open byte range [start, end) owned by one layer."""

    start: int
    end: int
    color: QColor
    label: str = ""

    def contains(self, index: int) -> bool:
        return self.start <= index < self.end


class HexView(QAbstractScrollArea):
    """Offset / hex / ASCII dump with per-layer tinting and click-to-select."""

    byteClicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = b""
        self._ranges: list[ByteRange] = []
        self._selection: ByteRange | None = None
        self._corrupt: set[int] = set()

        font = QFont(MONO_FAMILY.split(",")[0].strip())
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.setFont(font)

        metrics = QFontMetricsF(font)
        self._char_w = metrics.horizontalAdvance("0")
        self._row_h = metrics.height() + 5
        self._pad = 10

        self._columns = BYTES_PER_ROW
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)

    def _fit_columns(self) -> None:
        """Drop to 8 bytes per row when 16 will not fit.

        A clipped ASCII column is worse than a taller dump, and this panel
        competes for width with the field table.
        """
        needed = self._pad * 2 + (6 + BYTES_PER_ROW * 3 + 3 + BYTES_PER_ROW) * self._char_w
        columns = BYTES_PER_ROW if self.viewport().width() >= needed else BYTES_PER_ROW // 2
        if columns != self._columns:
            self._columns = columns
            self._update_scroll()

    # -- data ---------------------------------------------------------------

    def set_data(
        self,
        data: bytes,
        ranges: list[ByteRange] | None = None,
        corrupt: set[int] | None = None,
    ) -> None:
        self._data = data
        self._ranges = ranges or []
        self._corrupt = corrupt or set()
        self._selection = None
        self._update_scroll()
        self.viewport().update()

    def set_selection(self, selection: ByteRange | None) -> None:
        self._selection = selection
        if selection is not None:
            self._scroll_to_byte(selection.start)
        self.viewport().update()

    def set_corrupt(self, corrupt: set[int]) -> None:
        self._corrupt = corrupt
        self.viewport().update()

    # -- geometry -----------------------------------------------------------

    @property
    def _rows(self) -> int:
        return max(1, (len(self._data) + self._columns - 1) // self._columns)

    def _hex_x(self, column: int) -> float:
        """Left edge of the hex cell for ``column``, with a gap mid-row."""
        gap = 1 if column >= self._columns // 2 else 0
        return self._pad + (6 + column * 3 + gap) * self._char_w

    def _ascii_x(self, column: int) -> float:
        base = self._pad + (6 + self._columns * 3 + 3) * self._char_w
        return base + column * self._char_w

    def _update_scroll(self) -> None:
        self.verticalScrollBar().setRange(
            0, max(0, self._rows - self._visible_rows())
        )
        self.verticalScrollBar().setPageStep(self._visible_rows())

    def _visible_rows(self) -> int:
        return max(1, int(self.viewport().height() / self._row_h))

    def _scroll_to_byte(self, index: int) -> None:
        row = index // self._columns
        first = self.verticalScrollBar().value()
        last = first + self._visible_rows() - 1
        if row < first:
            self.verticalScrollBar().setValue(row)
        elif row > last:
            self.verticalScrollBar().setValue(row - self._visible_rows() + 1)

    def sizeHint(self) -> QSize:
        width = int(self._pad * 2 + (6 + BYTES_PER_ROW * 3 + 3 + BYTES_PER_ROW) * self._char_w)
        return QSize(width, int(self._row_h * 12))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._fit_columns()
        self._update_scroll()
        self.viewport().update()

    # -- interaction --------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        index = self._byte_at(event.position().x(), event.position().y())
        if index is not None:
            self.byteClicked.emit(index)

    def _byte_at(self, x: float, y: float) -> int | None:
        row = int(y // self._row_h) + self.verticalScrollBar().value()
        if not 0 <= row < self._rows:
            return None
        for column in range(self._columns):
            left = self._hex_x(column)
            if left <= x < left + self._char_w * 2.6:
                index = row * self._columns + column
                return index if index < len(self._data) else None
            left = self._ascii_x(column)
            if left <= x < left + self._char_w:
                index = row * self._columns + column
                return index if index < len(self._data) else None
        return None

    def _range_for(self, index: int) -> ByteRange | None:
        for item in self._ranges:
            if item.contains(index):
                return item
        return None

    # -- painting -----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self.viewport())
        painter.setFont(self.font())
        painter.fillRect(self.viewport().rect(), QColor(COLORS["panel"]))

        if not self._data:
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(
                self.viewport().rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No frame yet -- press Send",
            )
            return

        first_row = self.verticalScrollBar().value()
        muted = QColor(COLORS["muted"])
        text_color = QColor(COLORS["text"])
        corrupt_pen = QPen(QColor(COLORS["bad"]), 1.4)

        for screen_row in range(self._visible_rows() + 1):
            row = first_row + screen_row
            if row >= self._rows:
                break
            y = screen_row * self._row_h


            painter.setPen(muted)
            painter.drawText(
                QRectF(self._pad, y, self._char_w * 5, self._row_h),
                Qt.AlignmentFlag.AlignVCenter,
                f"{row * self._columns:04x}",
            )

            for column in range(self._columns):
                index = row * self._columns + column
                if index >= len(self._data):
                    break

                owner = self._range_for(index)
                selected = self._selection is not None and self._selection.contains(index)
                byte = self._data[index]

                hex_rect = QRectF(
                    self._hex_x(column) - self._char_w * 0.25,
                    y + 1,
                    self._char_w * 2.5,
                    self._row_h - 2,
                )
                ascii_rect = QRectF(
                    self._ascii_x(column) - 1, y + 1, self._char_w + 2, self._row_h - 2
                )

                if owner is not None:
                    tint = QColor(owner.color)
                    tint.setAlpha(190 if selected else 46)
                    painter.fillRect(hex_rect, tint)
                    painter.fillRect(ascii_rect, tint)
                elif selected:
                    painter.fillRect(hex_rect, QColor(COLORS["accent"]))

                if index in self._corrupt:
                    painter.setPen(corrupt_pen)
                    painter.drawRect(hex_rect.adjusted(0.5, 0.5, -0.5, -0.5))

                if selected and owner is not None:
                    painter.setPen(QColor("#0d1016"))
                elif index in self._corrupt:
                    painter.setPen(QColor(COLORS["bad"]))
                else:
                    painter.setPen(text_color)

                painter.drawText(
                    QRectF(self._hex_x(column), y, self._char_w * 2, self._row_h),
                    Qt.AlignmentFlag.AlignVCenter,
                    f"{byte:02x}",
                )
                glyph = chr(byte) if 32 <= byte < 127 else "."
                painter.drawText(
                    QRectF(self._ascii_x(column), y, self._char_w, self._row_h),
                    Qt.AlignmentFlag.AlignVCenter,
                    glyph,
                )
