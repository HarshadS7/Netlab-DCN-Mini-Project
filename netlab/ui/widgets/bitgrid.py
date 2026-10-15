"""A row of clickable bits.

Used wherever the page wants the user to break something on purpose: flip a bit
in a Hamming codeword, a CRC codeword or a checksummed header and watch the
receiver's arithmetic notice. Each cell carries a role so parity bits, data bits
and damaged bits are told apart at a glance.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import COLORS

__all__ = ["BitGrid"]

CELL_W, CELL_H = 30.0, 34.0
GAP = 4.0
LABEL_H = 16.0

ROLE_COLORS = {
    "data": COLORS["accent"],
    "parity": "#f2994a",
    "remainder": "#27c093",
    "plain": COLORS["muted"],
}


class BitGrid(QWidget):
    """Bits laid out left to right, numbered, clickable."""

    bitToggled = Signal(int)

    def __init__(self, parent: QWidget | None = None, *, one_based: bool = False) -> None:
        super().__init__(parent)
        self._bits: list[int] = []
        self._roles: list[str] = []
        self._flipped: set[int] = set()
        self._highlight: set[int] = set()
        self._one_based = one_based
        self._editable = True
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- data ---------------------------------------------------------------

    def set_bits(
        self,
        bits: list[int],
        roles: list[str] | None = None,
        flipped: set[int] | None = None,
    ) -> None:
        self._bits = list(bits)
        self._roles = roles or ["plain"] * len(bits)
        self._flipped = flipped or set()
        self.updateGeometry()
        self.update()

    def set_highlight(self, positions: set[int]) -> None:
        """Mark positions (same indexing as the grid) with an outline."""
        self._highlight = positions
        self.update()

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if editable else Qt.CursorShape.ArrowCursor
        )

    @property
    def bits(self) -> list[int]:
        return list(self._bits)

    # -- geometry -----------------------------------------------------------

    def _columns(self) -> int:
        usable = max(1.0, self.width())
        return max(1, int(usable // (CELL_W + GAP)))

    def _rows(self) -> int:
        if not self._bits:
            return 1
        columns = self._columns()
        return (len(self._bits) + columns - 1) // columns

    def sizeHint(self) -> QSize:
        rows = self._rows()
        return QSize(400, int(rows * (CELL_H + LABEL_H + GAP) + GAP))

    def minimumSizeHint(self) -> QSize:
        return QSize(200, int(CELL_H + LABEL_H + GAP * 2))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.updateGeometry()

    def _cell_rect(self, index: int) -> QRectF:
        columns = self._columns()
        row, column = divmod(index, columns)
        x = GAP + column * (CELL_W + GAP)
        y = GAP + row * (CELL_H + LABEL_H + GAP) + LABEL_H
        return QRectF(x, y, CELL_W, CELL_H)

    # -- interaction --------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._editable:
            return
        position = event.position()
        for index in range(len(self._bits)):
            if self._cell_rect(index).contains(position):
                self._bits[index] ^= 1
                if index in self._flipped:
                    self._flipped.discard(index)
                else:
                    self._flipped.add(index)
                self.update()
                self.bitToggled.emit(index)
                return

    # -- painting -----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self._bits:
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No bits yet")
            return

        value_font = QFont()
        value_font.setPointSize(11)
        value_font.setBold(True)
        label_font = QFont()
        label_font.setPointSize(7)
        metrics = QFontMetricsF(label_font)

        for index, bit in enumerate(self._bits):
            rect = self._cell_rect(index)
            role = self._roles[index] if index < len(self._roles) else "plain"
            damaged = index in self._flipped
            color = QColor(COLORS["bad"] if damaged else ROLE_COLORS.get(role, COLORS["muted"]))

            fill = QColor(color)
            fill.setAlpha(58 if bit else 22)
            painter.fillRect(rect, fill)

            width = 2.0 if (damaged or index in self._highlight) else 1.0
            pen_color = QColor(COLORS["warn"]) if index in self._highlight else color
            painter.setPen(QPen(pen_color, width))
            painter.drawRect(rect)

            painter.setFont(value_font)
            painter.setPen(QColor(COLORS["text"]))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(bit))

            painter.setFont(label_font)
            painter.setPen(QColor(COLORS["bad"] if damaged else COLORS["muted"]))
            number = index + 1 if self._one_based else index
            caption = f"{role[0]}{number}" if role in ("data", "parity") else str(number)
            painter.drawText(
                QRectF(rect.x(), rect.y() - LABEL_H, rect.width(), LABEL_H),
                Qt.AlignmentFlag.AlignCenter,
                caption,
            )
        painter.end()
