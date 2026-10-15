"""NetLab — a GUI lab for Data Communication and Networking (316U04C304).

Run with:  python main.py
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from netlab.ui.shell import MainWindow
from netlab.ui.theme import STYLESHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("NetLab")
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
