"""One dark palette, and one colour per layer.

The layer colours are the backbone of the Packet Journey page: the same colour
marks a header segment in the animation, its row in the field table and its
bytes in the hex dump, so the three panels read as one picture.
"""

from __future__ import annotations

from PySide6.QtGui import QColor

__all__ = ["COLORS", "LAYER_COLORS", "layer_color", "STYLESHEET", "MONO_FAMILY"]

COLORS = {
    "bg": "#0f1219",
    "panel": "#161a23",
    "panel_alt": "#1c222e",
    "border": "#2a3140",
    "text": "#e4e8f0",
    "muted": "#8b94a8",
    "accent": "#4da3ff",
    "good": "#27c093",
    "bad": "#ff5c5c",
    "warn": "#f2c14a",
}

# Warm at the top of the stack, cool at the bottom -- an easy mental ladder.
LAYER_COLORS = {
    "Application": "#f2994a",
    "Transport": "#27c093",
    "Network": "#4da3ff",
    "Data Link": "#b57bee",
    "Physical": "#7a879e",
    "Padding": "#5b6478",
    "Payload": "#c8cfdd",
}

MONO_FAMILY = "Cascadia Mono, Consolas, DejaVu Sans Mono, monospace"


def layer_color(name: str, alpha: int = 255) -> QColor:
    """Colour for a layer name, falling back to the payload grey."""
    color = QColor(LAYER_COLORS.get(name, LAYER_COLORS["Payload"]))
    color.setAlpha(alpha)
    return color


STYLESHEET = f"""
QWidget {{
    background: {COLORS["bg"]};
    color: {COLORS["text"]};
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
}}

QLabel[role="title"] {{
    font-size: 19px;
    font-weight: 600;
    padding: 2px 0;
}}
QLabel[role="subtitle"] {{
    color: {COLORS["muted"]};
    font-size: 12px;
    padding-bottom: 6px;
}}
QLabel[role="section"] {{
    color: {COLORS["muted"]};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 10px 0 4px 0;
}}

QFrame[role="card"] {{
    background: {COLORS["panel"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 10px;
}}

/* Sidebar navigation */
QListWidget#nav {{
    background: {COLORS["panel"]};
    border: none;
    border-right: 1px solid {COLORS["border"]};
    outline: none;
    padding: 8px 6px;
}}
QListWidget#nav::item {{
    padding: 9px 12px;
    border-radius: 8px;
    margin: 2px 4px;
    color: {COLORS["muted"]};
}}
QListWidget#nav::item:selected {{
    background: {COLORS["panel_alt"]};
    color: {COLORS["text"]};
    font-weight: 600;
}}
QListWidget#nav::item:hover:!selected {{
    background: {COLORS["panel_alt"]};
}}

QPushButton {{
    background: {COLORS["panel_alt"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 7px;
    padding: 7px 14px;
    color: {COLORS["text"]};
}}
QPushButton:hover {{ border-color: {COLORS["accent"]}; }}
QPushButton:disabled {{ color: {COLORS["muted"]}; border-color: {COLORS["border"]}; }}
QPushButton[role="primary"] {{
    background: {COLORS["accent"]};
    border-color: {COLORS["accent"]};
    color: #08101c;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: #6cb6ff; }}
QPushButton[role="primary"]:disabled {{ background: {COLORS["border"]}; color: {COLORS["muted"]}; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {COLORS["panel_alt"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: {COLORS["accent"]};
    selection-color: #08101c;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {COLORS["accent"]}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {COLORS["panel_alt"]};
    border: 1px solid {COLORS["border"]};
    selection-background-color: {COLORS["accent"]};
    selection-color: #08101c;
    outline: none;
}}

QTableWidget {{
    background: {COLORS["panel"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    gridline-color: {COLORS["border"]};
    outline: none;
}}
QTableWidget::item {{ padding: 5px 7px; }}
QTableWidget::item:selected {{ background: {COLORS["panel_alt"]}; color: {COLORS["text"]}; }}
QHeaderView::section {{
    background: {COLORS["panel_alt"]};
    color: {COLORS["muted"]};
    border: none;
    border-bottom: 1px solid {COLORS["border"]};
    padding: 7px;
    font-weight: 600;
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {COLORS["border"]};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {COLORS["accent"]};
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {COLORS["accent"]}; border-radius: 2px; }}

QGraphicsView {{
    background: {COLORS["bg"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 10px;
}}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {COLORS["border"]}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {COLORS["muted"]}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {COLORS["border"]}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QSplitter::handle {{ background: {COLORS["border"]}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {COLORS["border"]};
    border-radius: 4px;
    background: {COLORS["panel_alt"]};
}}
QCheckBox::indicator:checked {{ background: {COLORS["accent"]}; border-color: {COLORS["accent"]}; }}

QToolTip {{
    background: {COLORS["panel_alt"]};
    color: {COLORS["text"]};
    border: 1px solid {COLORS["border"]};
    padding: 5px;
}}
"""
