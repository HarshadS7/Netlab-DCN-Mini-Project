"""The ARQ timeline: sender on the left, receiver on the right, time downward.

This is the diagram every textbook draws for Stop-and-Wait, Go-Back-N and
Selective Repeat. Losses stop partway with a cross, discarded frames arrive
greyed out, and timeouts are marked on the sender's own axis.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from ...core.arq.machines import ArqResult
from ..theme import COLORS

__all__ = ["ArqTimeline"]

SENDER_X, RECEIVER_X = 150.0, 560.0
TOP = 46.0
TIME_SCALE = 26.0
MARGIN = 30.0


class ArqTimeline(QGraphicsView):
    """Draws an :class:`ArqResult` as a time-sequence diagram."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Anchor the diagram to the top; centring it leaves the first frames
        # floating in the middle of the panel with dead space above them.
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._result: ArqResult | None = None

    def set_result(self, result: ArqResult) -> None:
        self._result = result
        self._redraw()

    def _y(self, time: float) -> float:
        return TOP + time * TIME_SCALE

    def _redraw(self) -> None:
        self._scene.clear()
        result = self._result
        if result is None:
            return

        end = max((arrow.end for arrow in result.arrows), default=1.0)
        end = max(end, max((t for _, t in result.timeouts), default=0.0))
        height = self._y(end) + MARGIN * 2
        self._scene.setSceneRect(0, 0, RECEIVER_X + 150, height)

        self._draw_axes(height)
        for arrow in result.arrows:
            self._draw_arrow(arrow)
        for seq, time in result.timeouts:
            self._draw_timeout(seq, time)

    def _draw_axes(self, height: float) -> None:
        pen = QPen(QColor(COLORS["border"]), 2)
        for x, title in ((SENDER_X, "SENDER"), (RECEIVER_X, "RECEIVER")):
            self._scene.addLine(x, TOP - 14, x, height - MARGIN, pen)
            label = self._scene.addText(title)
            label.setDefaultTextColor(QColor(COLORS["muted"]))
            font = QFont()
            font.setPointSize(8)
            font.setBold(True)
            label.setFont(font)
            label.setPos(x - label.boundingRect().width() / 2, 8)

        arrow = self._scene.addText("time")
        arrow.setDefaultTextColor(QColor(COLORS["muted"]))
        small = QFont()
        small.setPointSize(7)
        arrow.setFont(small)
        arrow.setPos(6, TOP)

    def _draw_arrow(self, arrow) -> None:
        forward = arrow.kind == "data"
        start_x = SENDER_X if forward else RECEIVER_X
        end_x = RECEIVER_X if forward else SENDER_X
        start = QPointF(start_x, self._y(arrow.start))
        end = QPointF(end_x, self._y(arrow.end))

        if arrow.lost:
            # Stop at the midpoint and mark the loss.
            end = QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)

        if arrow.lost:
            color = QColor(COLORS["bad"])
        elif arrow.discarded:
            color = QColor(COLORS["warn"])
        elif forward:
            color = QColor(COLORS["accent"])
        else:
            color = QColor(COLORS["good"])

        pen = QPen(color, 1.8)
        if arrow.discarded:
            pen.setStyle(Qt.PenStyle.DashLine)
        self._scene.addLine(start.x(), start.y(), end.x(), end.y(), pen)

        if arrow.lost:
            self._draw_cross(end, color)
        else:
            self._draw_head(start, end, color)

        label = self._scene.addText(arrow.label)
        label.setDefaultTextColor(color)
        font = QFont()
        font.setPointSize(8)
        label.setFont(font)
        width = label.boundingRect().width()
        if forward:
            label.setPos(start.x() + 8, start.y() - 20)
        else:
            label.setPos(start.x() - width - 8, start.y() - 20)

        if arrow.discarded:
            note = self._scene.addText("discarded")
            note.setDefaultTextColor(QColor(COLORS["warn"]))
            tiny = QFont()
            tiny.setPointSize(7)
            note.setFont(tiny)
            note.setPos(end.x() + 8, end.y() - 8)

    def _draw_head(self, start: QPointF, end: QPointF, color: QColor) -> None:
        import math

        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        size = 8.0
        head = QPolygonF(
            [
                end,
                QPointF(
                    end.x() - size * math.cos(angle - 0.4),
                    end.y() - size * math.sin(angle - 0.4),
                ),
                QPointF(
                    end.x() - size * math.cos(angle + 0.4),
                    end.y() - size * math.sin(angle + 0.4),
                ),
            ]
        )
        self._scene.addPolygon(head, QPen(color, 1), color)

    def _draw_cross(self, at: QPointF, color: QColor) -> None:
        pen = QPen(color, 2.4)
        size = 7.0
        self._scene.addLine(at.x() - size, at.y() - size, at.x() + size, at.y() + size, pen)
        self._scene.addLine(at.x() - size, at.y() + size, at.x() + size, at.y() - size, pen)
        label = self._scene.addText("lost")
        label.setDefaultTextColor(color)
        font = QFont()
        font.setPointSize(7)
        label.setFont(font)
        label.setPos(at.x() + 10, at.y() - 10)

    def _draw_timeout(self, seq: int, time: float) -> None:
        y = self._y(time)
        pen = QPen(QColor(COLORS["warn"]), 1.4, Qt.PenStyle.DotLine)
        self._scene.addLine(SENDER_X - 70, y, SENDER_X + 16, y, pen)
        label = self._scene.addText(f"timeout {seq}")
        label.setDefaultTextColor(QColor(COLORS["warn"]))
        font = QFont()
        font.setPointSize(7)
        label.setFont(font)
        label.setPos(SENDER_X - 70 - label.boundingRect().width() - 4, y - 9)
