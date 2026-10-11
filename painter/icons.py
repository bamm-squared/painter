"""Small original line icons and alpha-aware swatches for the interface."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer


PATHS = {
    "select": '<rect x="4" y="4" width="16" height="16" rx="1" stroke-dasharray="3 2"/>',
    "brush": '<path d="M14 4c2-2 4-2 6 0s2 4 0 6l-8 8-5-5z"/><path d="M7 13c-3 0-4 3-4 7 3-1 6-1 7-4"/>',
    "pencil": '<path d="M4 17 16.5 4.5a2.1 2.1 0 0 1 3 3L7 20l-4 1z"/><path d="m14 7 3 3M4 17l3 3"/>',
    "eraser": '<path d="m4 14 9-10a2 2 0 0 1 3 0l5 5a2 2 0 0 1 0 3l-8 8H8z"/><path d="m8 10 8 8M13 20h8"/>',
    "fill": '<path d="m12 3 8 8-8 8-8-8z"/><path d="M6 13h12M20 17c0 2-2 3-2 4a2 2 0 0 0 4 0c0-1-2-2-2-4z"/>',
    "picker": '<path d="m14 5 5 5M7 16l10-10a2 2 0 0 1 3 3L10 19H6v-4z"/><path d="m5 20 2-2"/>',
    "line": '<path d="M4 19 20 5"/><circle cx="4" cy="19" r="1"/><circle cx="20" cy="5" r="1"/>',
    "rectangle": '<rect x="4" y="5" width="16" height="14" rx="1"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="8" ry="7"/>',
    "text": '<path d="M4 5h16M12 5v15M8 20h8M4 5v3M20 5v3"/>',
    "plus": '<path d="M12 4v16M4 12h16"/>',
    "eye": '<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/>',
    "eye_off": '<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6-10-6z"/><path d="M3 3 21 21"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 2-2c0-1-1-2-1-3s1-2 2-2h3a2 2 0 0 0 2-2 9 9 0 0 0-9-9z"/><circle cx="7" cy="11" r=".8"/><circle cx="10" cy="7" r=".8"/><circle cx="15" cy="7" r=".8"/>',
}

_icon_color = "#566074"


def set_icon_color(color: str) -> None:
    global _icon_color
    _icon_color = color


def line_icon(name: str, color: str | None = None, size: int = 24) -> QIcon:
    color = color or _icon_color
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" '
           f'stroke-linejoin="round">{PATHS[name]}</svg>')
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def swatch_icon(rgba: tuple[int, int, int, int], size: int = 28) -> QIcon:
    pixmap = QPixmap(size, size)
    painter = QPainter(pixmap)
    half = size // 2
    painter.fillRect(0, 0, size, size, QColor("#ffffff"))
    painter.fillRect(0, 0, half, half, QColor("#d7dce5"))
    painter.fillRect(half, half, size - half, size - half, QColor("#d7dce5"))
    painter.fillRect(QRectF(0, 0, size, size), QColor(*rgba))
    painter.setPen(QPen(QColor("#c9ced8"), 1))
    painter.drawRect(0, 0, size - 1, size - 1)
    painter.end()
    return QIcon(pixmap)
