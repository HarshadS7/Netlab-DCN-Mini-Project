"""A draggable router topology.

Nodes can be moved around, links carry their cost, and the view can highlight
the set of routers an algorithm has settled plus the path it chose. Dragging is
Qt's own ``ItemIsMovable``; the link lines simply ask their endpoints where
they are whenever the scene redraws.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from ...core.routing.algorithms import Topology
from ..theme import COLORS

__all__ = ["TopologyView"]

RADIUS = 22.0


class _Node(QGraphicsEllipseItem):
    def __init__(self, name: str, view: "TopologyView") -> None:
        super().__init__(-RADIUS, -RADIUS, RADIUS * 2, RADIUS * 2)
        self.name = name
        self._view = view
        self.state = "idle"  # idle | source | settled | path
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges, True)
        self.setZValue(5)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def itemChange(self, change, value):  # noqa: N802 - Qt naming
        if change == QGraphicsItem.GraphicsItemChange.ItemScenePositionHasChanged:
            self._view.node_moved(self.name, self.pos())
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._view.nodeChosen.emit(self.name)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = {
            "idle": COLORS["muted"],
            "source": COLORS["accent"],
            "settled": COLORS["good"],
            "path": COLORS["warn"],
        }
        color = QColor(colors[self.state])

        fill = QColor(color)
        fill.setAlpha(70 if self.state != "idle" else 30)
        painter.setBrush(fill)
        painter.setPen(QPen(color, 2.0 if self.state != "idle" else 1.2))
        painter.drawEllipse(self.rect())

        painter.setPen(QColor(COLORS["text"]))
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.name)


class TopologyView(QGraphicsView):
    """Renders a :class:`Topology` and highlights algorithm state."""

    nodeChosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._topology: Topology | None = None
        self._nodes: dict[str, _Node] = {}
        self._settled: set[str] = set()
        self._path: list[str] = []
        self._source: str | None = None
        self._suspend = False

    def set_topology(self, topology: Topology) -> None:
        self._topology = topology
        self._nodes.clear()
        self._scene.clear()

        for name in topology.nodes:
            node = _Node(name, self)
            x, y = topology.positions.get(name, (0.0, 0.0))
            self._suspend = True
            node.setPos(x, y)
            self._suspend = False
            self._scene.addItem(node)
            self._nodes[name] = node

        self._redraw_links()
        self._apply_states()

    def node_moved(self, name: str, position: QPointF) -> None:
        if self._suspend or self._topology is None:
            return
        self._topology.positions[name] = (position.x(), position.y())
        self._redraw_links()

    def set_highlight(
        self, settled: set[str] | None = None, path: list[str] | None = None,
        source: str | None = None,
    ) -> None:
        self._settled = settled or set()
        self._path = path or []
        self._source = source
        self._apply_states()
        self._redraw_links()

    def _apply_states(self) -> None:
        for name, node in self._nodes.items():
            if name == self._source:
                node.state = "source"
            elif name in self._path:
                node.state = "path"
            elif name in self._settled:
                node.state = "settled"
            else:
                node.state = "idle"
            node.update()

    def _redraw_links(self) -> None:
        if self._topology is None:
            return
        for item in list(self._scene.items()):
            if not isinstance(item, _Node):
                self._scene.removeItem(item)

        path_pairs = {
            frozenset((self._path[i], self._path[i + 1]))
            for i in range(len(self._path) - 1)
        }

        for link in self._topology.links:
            if link.a not in self._nodes or link.b not in self._nodes:
                continue
            start = self._nodes[link.a].pos()
            end = self._nodes[link.b].pos()
            on_path = frozenset((link.a, link.b)) in path_pairs

            color = QColor(COLORS["warn"] if on_path else COLORS["border"])
            pen = QPen(color, 3.0 if on_path else 1.6)
            line = self._scene.addLine(start.x(), start.y(), end.x(), end.y(), pen)
            line.setZValue(1)

            middle = QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)
            label = self._scene.addText(str(link.cost))
            label.setDefaultTextColor(
                QColor(COLORS["warn"] if on_path else COLORS["muted"])
            )
            font = QFont()
            font.setPointSize(8)
            font.setBold(on_path)
            label.setFont(font)
            rect = label.boundingRect()
            label.setPos(middle.x() - rect.width() / 2, middle.y() - rect.height() / 2)
            label.setZValue(2)

        bounds = self._scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        self._scene.setSceneRect(bounds)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if self._scene.sceneRect().isValid():
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
