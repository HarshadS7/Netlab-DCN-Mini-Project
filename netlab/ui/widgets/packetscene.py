"""The Packet Journey animation.

Two host stacks and one packet that visibly grows a header at every layer on
the way down, crosses a wire, and is stripped back down on the way up. The
packet is a real scene item animated with :class:`QPropertyAnimation`, so the
motion is interpolated by Qt rather than stepped by hand.

The page supplies a list of :class:`JourneyStep`; this widget only knows how to
draw and animate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from ..theme import COLORS, layer_color

__all__ = ["Segment", "JourneyStep", "PacketScene", "LAYER_ORDER"]

LAYER_ORDER = ["Application", "Transport", "Network", "Data Link", "Physical"]

SCENE_W, SCENE_H = 1040.0, 500.0
BOX_W, BOX_H = 150.0, 56.0
SENDER_X, RECEIVER_X = 16.0, SCENE_W - 16.0 - BOX_W
LAYER_Y = {name: 48.0 + index * 74.0 for index, name in enumerate(LAYER_ORDER)}
DESCEND_X, ASCEND_X = 380.0, 690.0
PACKET_MAX_W = 330.0
PACKET_H = 40.0


@dataclass(frozen=True)
class Segment:
    """One coloured block of the packet bar."""

    label: str
    layer: str
    size: int
    detail: str = ""


@dataclass
class JourneyStep:
    """One frame of the story the page wants told."""

    caption: str
    layer: str
    side: str  # "sender" | "wire" | "receiver"
    segments: list[Segment] = dc_field(default_factory=list)
    corrupt_ratio: float = 0.0
    failed: bool = False
    note: str = ""


class _LayerBox(QGraphicsItem):
    """A labelled layer in one host's stack."""

    def __init__(self, layer: str, protocol: str, x: float, y: float) -> None:
        super().__init__()
        self.layer = layer
        self.protocol = protocol
        self.active = False
        self.status: str | None = None  # None | "ok" | "fail"
        self.setPos(x, y)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt naming
        return QRectF(0, 0, BOX_W, BOX_H)

    def set_state(self, active: bool, status: str | None = None) -> None:
        if (active, status) != (self.active, self.status):
            self.active, self.status = active, status
            self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = layer_color(self.layer)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, BOX_W, BOX_H), 9, 9)

        fill = QColor(color)
        fill.setAlpha(46 if self.active else 20)
        painter.fillPath(path, fill)

        pen_color = QColor(color)
        if self.status == "fail":
            pen_color = QColor(COLORS["bad"])
        elif self.status == "ok":
            pen_color = QColor(COLORS["good"])
        painter.setPen(QPen(pen_color, 2.0 if self.active else 1.0))
        painter.drawPath(path)

        painter.setPen(QColor(COLORS["text"] if self.active else COLORS["muted"]))
        font = QFont()
        font.setPointSize(9)
        font.setBold(self.active)
        painter.setFont(font)
        painter.drawText(
            QRectF(10, 6, BOX_W - 20, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.layer,
        )

        font.setBold(False)
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor(color if self.active else COLORS["muted"]))
        painter.drawText(
            QRectF(10, BOX_H - 26, BOX_W - 20, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.protocol,
        )

        if self.status:
            painter.setPen(QColor(COLORS["good"] if self.status == "ok" else COLORS["bad"]))
            painter.drawText(
                QRectF(BOX_W - 30, 6, 20, 20),
                Qt.AlignmentFlag.AlignCenter,
                "✓" if self.status == "ok" else "✗",
            )


class _PacketItem(QGraphicsObject):
    """The packet bar. A QGraphicsObject so ``pos`` can be animated."""

    def __init__(self) -> None:
        super().__init__()
        self._segments: list[Segment] = []
        self._widths: list[float] = []
        self._corrupt_ratio = 0.0
        self._failed = False
        self.setZValue(10)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt naming
        width = sum(self._widths) or 10.0
        return QRectF(-width / 2, -PACKET_H / 2, width, PACKET_H)

    def set_segments(
        self,
        segments: list[Segment],
        reference: int,
        corrupt_ratio: float = 0.0,
        failed: bool = False,
    ) -> None:
        self.prepareGeometryChange()
        self._segments = segments
        self._corrupt_ratio = corrupt_ratio
        self._failed = failed
        self._widths = self._layout(segments, reference)
        self.update()

    @staticmethod
    def _layout(segments: list[Segment], reference: int) -> list[float]:
        """Size blocks by byte count against a fixed reference.

        ``reference`` is the size of the largest composition in the journey --
        the complete frame. Measuring every stage against that one scale is what
        makes the bar visibly grow on the way down and shrink on the way up. A
        per-stage scale would keep the bar the same width throughout and lose
        the entire point of the animation.

        Headers still get a floor width so their labels stay readable, which
        costs a little proportional accuracy on the smallest blocks.
        """
        if not segments or reference <= 0:
            return []
        scale = PACKET_MAX_W / reference
        widths = [max(26.0, max(1, item.size) * scale) for item in segments]
        total = sum(widths)
        if total > PACKET_MAX_W:
            widths = [width * PACKET_MAX_W / total for width in widths]
        return widths

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if not self._segments:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = sum(self._widths)
        x = -width / 2
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)

        for segment, segment_width in zip(self._segments, self._widths):
            rect = QRectF(x, -PACKET_H / 2, segment_width, PACKET_H)
            color = layer_color(segment.layer)

            path = QPainterPath()
            path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
            fill = QColor(color)
            fill.setAlpha(80 if self._failed else 200)
            painter.fillPath(path, fill)
            painter.setPen(QPen(QColor(color).darker(160), 1))
            painter.drawPath(path)

            painter.setFont(font)
            painter.setPen(QColor("#0c1017") if not self._failed else QColor(COLORS["muted"]))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, segment.label)
            x += segment_width

        if self._corrupt_ratio > 0:
            # Red ticks scattered across the bar stand in for flipped bits.
            painter.setPen(QPen(QColor(COLORS["bad"]), 2))
            count = max(1, int(self._corrupt_ratio * 24))
            for index in range(count):
                tick = -width / 2 + width * ((index + 0.5) / count)
                painter.drawLine(
                    QPointF(tick, -PACKET_H / 2 - 4), QPointF(tick, PACKET_H / 2 + 4)
                )


class PacketScene(QGraphicsView):
    """Draws the two stacks and animates the packet through a step list."""

    stepChanged = Signal(int, str, str)  # index, caption, note
    finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(0, 0, SCENE_W, SCENE_H, self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._steps: list[JourneyStep] = []
        self._reference = 1
        self._index = -1
        self._animation: QPropertyAnimation | None = None
        self._auto = False
        self._speed = 1.0

        self._sender: dict[str, _LayerBox] = {}
        self._receiver: dict[str, _LayerBox] = {}
        self._packet = _PacketItem()
        self._build()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        for layer in LAYER_ORDER:
            for side, x, store in (
                ("sender", SENDER_X, self._sender),
                ("receiver", RECEIVER_X, self._receiver),
            ):
                box = _LayerBox(layer, "", x, LAYER_Y[layer])
                self._scene.addItem(box)
                store[layer] = box

        wire_y = LAYER_Y["Physical"] + BOX_H / 2
        pen = QPen(QColor(COLORS["border"]), 2, Qt.PenStyle.DashLine)
        self._wire = self._scene.addLine(
            SENDER_X + BOX_W, wire_y, RECEIVER_X, wire_y, pen
        )

        for x, text in ((SENDER_X, "SENDER"), (RECEIVER_X, "RECEIVER")):
            label = self._scene.addText(text)
            label.setDefaultTextColor(QColor(COLORS["muted"]))
            font = QFont()
            font.setPointSize(8)
            font.setBold(True)
            label.setFont(font)
            label.setPos(x + 2, 18)

        self._scene.addItem(self._packet)
        self._packet.setPos(DESCEND_X, LAYER_Y["Application"] + BOX_H / 2)
        self._packet.setVisible(False)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        # Keep the widget itself at the scene's aspect ratio. Without this the
        # view expands to whatever height the layout offers and letterboxes the
        # drawing with dead space above and below it.
        self.setMaximumHeight(int(self.width() * SCENE_H / SCENE_W) + 2)
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # -- driving the story --------------------------------------------------

    def set_steps(self, steps: list[JourneyStep], protocols: dict[str, str]) -> None:
        self._stop()
        self._steps = steps
        # The complete frame sets the scale every stage is drawn against.
        self._reference = max(
            (sum(item.size for item in step.segments) for step in steps), default=1
        )
        self._index = -1
        for store in (self._sender, self._receiver):
            for layer, box in store.items():
                box.protocol = protocols.get(layer, "")
                box.set_state(False, None)
        self._packet.setVisible(False)
        self._packet.set_segments([], self._reference)

    def set_speed(self, multiplier: float) -> None:
        self._speed = max(0.1, multiplier)

    def play(self) -> None:
        self._auto = True
        self.next_step()

    def next_step(self) -> None:
        if self._index + 1 >= len(self._steps):
            self._auto = False
            self.finished.emit()
            return
        self._index += 1
        self._apply(self._steps[self._index])

    def reset(self) -> None:
        self._stop()
        self._index = -1
        for store in (self._sender, self._receiver):
            for box in store.values():
                box.set_state(False, None)
        self._packet.setVisible(False)
        self._packet.set_segments([], self._reference)

    @property
    def at_end(self) -> bool:
        return self._index + 1 >= len(self._steps)

    def _stop(self) -> None:
        self._auto = False
        if self._animation is not None:
            self._animation.stop()
            self._animation = None

    def _apply(self, step: JourneyStep) -> None:
        for store in (self._sender, self._receiver):
            for box in store.values():
                box.set_state(False, box.status)

        if step.side == "sender":
            self._sender[step.layer].set_state(True)
        elif step.side == "receiver":
            box = self._receiver[step.layer]
            box.set_state(True, "fail" if step.failed else "ok")
        else:
            self._sender["Physical"].set_state(True)
            self._receiver["Physical"].set_state(True)

        self._packet.setVisible(True)
        self._packet.set_segments(
            step.segments, self._reference, step.corrupt_ratio, step.failed
        )
        self.stepChanged.emit(self._index, step.caption, step.note)

        target = self._target_for(step)
        self._animate_to(target)

    @staticmethod
    def _target_for(step: JourneyStep) -> QPointF:
        y = LAYER_Y[step.layer] + BOX_H / 2
        if step.side == "sender":
            return QPointF(DESCEND_X, y)
        if step.side == "receiver":
            return QPointF(ASCEND_X, y)
        return QPointF(ASCEND_X, LAYER_Y["Physical"] + BOX_H / 2)

    def _animate_to(self, target: QPointF) -> None:
        if self._animation is not None:
            self._animation.stop()

        animation = QPropertyAnimation(self._packet, b"pos", self)
        animation.setDuration(int(520 / self._speed))
        animation.setStartValue(self._packet.pos())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.finished.connect(self._on_animation_finished)
        self._animation = animation
        animation.start()

    def _on_animation_finished(self) -> None:
        self._animation = None
        if self._auto:
            self.next_step()
