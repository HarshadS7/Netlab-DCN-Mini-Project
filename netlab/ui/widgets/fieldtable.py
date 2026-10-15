"""The header field breakdown, and the glue that keeps it in step.

Selecting a row here highlights the same bytes in the hex dump and the same
segment in the packet animation, because all three are driven by the byte range
carried on :class:`~netlab.core.model.Field`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ...core.model import Field, LayerView
from ..theme import COLORS, MONO_FAMILY, layer_color

__all__ = ["FieldTable"]


class FieldTable(QTableWidget):
    """One row per field: name and value, with the detail in the tooltip."""

    fieldSelected = Signal(object, object)  # (LayerView, Field)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["Field", "Value"])
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)

        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # Meanings are full sentences and always truncated in a column this
        # narrow, so they live in the tooltip and in the explainer under the
        # animation, where there is room to read them.

        self._entries: list[tuple[LayerView, Field, bool]] = []
        self.itemSelectionChanged.connect(self._emit_selection)

    def set_layers(self, layers: list[LayerView]) -> None:
        """Populate from the whole stack, outermost layer first."""
        self.blockSignals(True)
        self._entries.clear()
        self.setRowCount(0)

        mono = QFont(MONO_FAMILY.split(",")[0].strip())
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)

        for view in layers:
            pairs = [(item, False) for item in view.fields]
            pairs += [(item, True) for item in view.trailer_fields]
            if not pairs:
                continue
            self._add_header_row(view)
            for item, is_trailer in pairs:
                self._add_field_row(view, item, is_trailer, mono)

        self.blockSignals(False)

    def _add_header_row(self, view: LayerView) -> None:
        row = self.rowCount()
        self.insertRow(row)
        label = QTableWidgetItem(f"  {view.layer.upper()} · {view.protocol}")
        font = label.font()
        font.setBold(True)
        font.setPointSize(9)
        label.setFont(font)
        label.setForeground(QBrush(layer_color(view.layer)))
        background = layer_color(view.layer)
        background.setAlpha(28)
        for column in range(2):
            cell = label if column == 0 else QTableWidgetItem("")
            cell.setBackground(QBrush(background))
            cell.setFlags(Qt.ItemFlag.NoItemFlags)
            self.setItem(row, column, cell)
        self._entries.append((view, None, False))
        self.setSpan(row, 0, 1, 2)

    def _add_field_row(
        self, view: LayerView, item: Field, is_trailer: bool, mono: QFont
    ) -> None:
        row = self.rowCount()
        self.insertRow(row)
        start, end = view.absolute_bits(item, trailer=is_trailer)

        span = f"bits {start}-{end}" if item.length_bits > 1 else f"bit {start}"
        tip = f"{item.name} — {span} ({item.length_bits} bit(s))"
        if item.meaning:
            tip += "\n" + item.meaning

        name = QTableWidgetItem(f"   {item.name}")
        name.setToolTip(tip)
        value = QTableWidgetItem(item.display)
        value.setFont(mono)
        value.setForeground(QBrush(layer_color(view.layer)))
        value.setToolTip(tip)
        for column, cell in enumerate([name, value]):
            self.setItem(row, column, cell)
        self._entries.append((view, item, is_trailer))

    def _emit_selection(self) -> None:
        rows = {index.row() for index in self.selectedIndexes()}
        if not rows:
            return
        row = rows.pop()
        if not 0 <= row < len(self._entries):
            return
        view, item, _ = self._entries[row]
        if item is not None:
            self.fieldSelected.emit(view, item)

    def select_field(self, view: LayerView, item: Field) -> None:
        """Select a row from outside -- used when a hex byte is clicked."""
        for row, (candidate_view, candidate_item, _) in enumerate(self._entries):
            if candidate_view is view and candidate_item is item:
                self.selectRow(row)
                self.scrollToItem(self.item(row, 0))
                return
