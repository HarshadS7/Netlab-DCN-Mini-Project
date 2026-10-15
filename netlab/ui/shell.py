"""The application shell: a sidebar and a stack of pages.

Pages are registered with a placeholder until they are built, so the navigation
reflects the full syllabus coverage from day one and each page can be dropped in
as it is finished.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .pages.applayer import ApplicationPage
from .pages.journey import JourneyPage
from .pages.link import LinkPage
from .pages.network import NetworkPage
from .pages.physical import PhysicalPage
from .pages.transport import TransportPage
from .theme import COLORS

__all__ = ["MainWindow"]

# Page title, syllabus modules it covers, and the widget factory (None = to come).
PAGES = [
    ("Packet Journey", "Modules 1-5", JourneyPage),
    ("Application Lab", "Module 2", ApplicationPage),
    ("Transport Lab", "Module 3", TransportPage),
    ("Network Lab", "Module 4", NetworkPage),
    ("Link Lab", "Module 5.1-5.2", LinkPage),
    ("Physical Lab", "Module 5.3-5.4", PhysicalPage),
]


class _Placeholder(QWidget):
    """Stands in for a page that is not built yet."""

    def __init__(self, title: str, modules: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        heading = QLabel(title)
        heading.setProperty("role", "title")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)

        detail = QLabel(f"{modules} — not built yet.")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setStyleSheet(f"color: {COLORS['muted']};")

        layout.addWidget(heading)
        layout.addWidget(detail)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NetLab — Data Communication and Networking")
        self.resize(1480, 900)
        self.setMinimumSize(1100, 680)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        body = QWidget()
        layout.addWidget(body)

        from PySide6.QtWidgets import QHBoxLayout

        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(196)
        self.nav.setIconSize(QSize(16, 16))

        self.stack = QStackedWidget()

        for title, modules, factory in PAGES:
            item = QListWidgetItem(title)
            item.setToolTip(f"Syllabus {modules}")
            self.nav.addItem(item)
            self.stack.addWidget(factory() if factory else _Placeholder(title, modules))

        row.addWidget(self.nav)
        row.addWidget(self.stack, 1)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.statusBar().setStyleSheet(
            f"color: {COLORS['muted']}; border-top: 1px solid {COLORS['border']};"
        )
        self.statusBar().showMessage(
            "NetLab — headers are real bytes; export any frame to .pcap and open it in Wireshark."
        )
