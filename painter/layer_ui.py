"""Layer thumbnails and a read-only flattened preview."""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import Qt, QSize, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListView,
    QListWidget, QPushButton, QScrollArea, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from .document import Layer
from .theme import COLORS


THUMBNAIL_SIZE = QSize(96, 72)
CARD_WIDTH = 116


def qimage_from_pil(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    return QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4,
                  QImage.Format.Format_RGBA8888).copy()


def paint_checker(painter: QPainter, width: int, height: int, tile: int = 8) -> None:
    for y in range(0, height, tile):
        for x in range(0, width, tile):
            painter.fillRect(x, y, min(tile, width - x), min(tile, height - y),
                             QColor("#ffffff") if (x // tile + y // tile) % 2 else QColor("#d5dbe5"))


def layer_thumbnail(layer: Layer) -> QPixmap:
    pixmap = QPixmap(THUMBNAIL_SIZE)
    painter = QPainter(pixmap)
    paint_checker(painter, pixmap.width(), pixmap.height())
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scale = min(pixmap.width() / layer.image.width, pixmap.height() / layer.image.height)
    width, height = layer.image.width * scale, layer.image.height * scale
    target = QRectF((pixmap.width() - width) / 2, (pixmap.height() - height) / 2, width, height)
    pixels = layer.image
    if layer.opacity != 255:
        pixels = pixels.copy()
        pixels.putalpha(pixels.getchannel("A").point(lambda a: a * layer.opacity // 255))
    painter.drawImage(target, qimage_from_pil(pixels))
    painter.end()
    return pixmap


class LayerThumbnailDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(CARD_WIDTH - 4, 90)

    def paint(self, painter: QPainter, option, index) -> None:
        theme = QApplication.instance().property("painter_theme") or "dark"
        colors = COLORS[theme]
        selected = bool(option.state & option.state.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = option.rect.adjusted(2, 2, -2, -2)
        painter.setBrush(QColor(colors["active"] if selected else colors["surface"]))
        painter.setPen(QPen(QColor(colors["accent_border"] if selected else colors["border"]),
                            2 if selected else 1))
        painter.drawRoundedRect(card, 8, 8)
        pixmap = index.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(pixmap, QPixmap):
            x = card.x() + (card.width() - pixmap.width()) / 2
            y = card.y() + (card.height() - pixmap.height()) / 2
            image_rect = QRectF(x, y, pixmap.width(), pixmap.height())
            painter.drawPixmap(image_rect, pixmap, QRectF(pixmap.rect()))
            if not index.data(Qt.ItemDataRole.UserRole + 2):
                painter.fillRect(image_rect, QColor(0, 0, 0, 105))
        painter.restore()


class LayerStrip(QListWidget):
    order_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reordering = False
        self._press_row = -1
        self._drag_target = -1
        self._dragging_thumb = False
        self._press_position = None
        self.setObjectName("layerStrip")
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setSpacing(4)
        self.setFixedHeight(96)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setItemDelegate(LayerThumbnailDelegate(self))

    def order(self) -> list[int]:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def mousePressEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        self._press_row = self.row(item) if item is not None and event.button() == Qt.MouseButton.LeftButton else -1
        self._press_position = event.position().toPoint()
        self._drag_target = self._press_row
        self._dragging_thumb = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_row >= 0 and event.buttons() & Qt.MouseButton.LeftButton:
            if (event.position().toPoint() - self._press_position).manhattanLength() >= QApplication.startDragDistance():
                self._dragging_thumb = True
            if self._dragging_thumb:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                scrollbar = self.horizontalScrollBar()
                if event.position().x() >= self.viewport().width() - 16:
                    scrollbar.setValue(scrollbar.value() + 14)
                elif event.position().x() <= 16:
                    scrollbar.setValue(scrollbar.value() - 14)
                item = self.itemAt(event.position().toPoint())
                if item is not None:
                    self._drag_target = self.row(item)
                elif event.position().x() > self.visualItemRect(self.item(self.count() - 1)).right():
                    self._drag_target = self.count() - 1
                elif event.position().x() < self.visualItemRect(self.item(0)).left():
                    self._drag_target = 0
                self.viewport().update()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_thumb:
            source, destination = self._press_row, self._drag_target
            self.reordering = True
            super().mouseReleaseEvent(event)
            self.reordering = False
            self._press_row = -1
            self._drag_target = -1
            self._dragging_thumb = False
            self.unsetCursor()
            self.viewport().update()
            if source != destination and destination >= 0:
                order = self.order()
                moved = order.pop(source)
                order.insert(destination, moved)
                self.order_changed.emit(order)
            return
        self._press_row = -1
        self._drag_target = -1
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._dragging_thumb and self._drag_target >= 0:
            target = self.visualItemRect(self.item(self._drag_target))
            x = target.right() + 2 if self._drag_target > self._press_row else target.left() - 2
            painter = QPainter(self.viewport())
            theme = QApplication.instance().property("painter_theme") or "dark"
            painter.setPen(QPen(QColor(COLORS[theme]["accent"]), 3))
            painter.drawLine(x, 8, x, self.viewport().height() - 8)
            painter.end()


class PreviewImage(QWidget):
    def __init__(self, image: Image.Image):
        super().__init__()
        self.set_image(image)

    def set_image(self, image: Image.Image) -> None:
        self.image = qimage_from_pil(image)
        self.setFixedSize(image.width, image.height)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        paint_checker(painter, self.width(), self.height(), tile=12)
        painter.drawImage(0, 0, self.image)
        painter.end()


class PreviewDialog(QDialog):
    def __init__(self, image: Image.Image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Final image preview")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        heading = QLabel("Final image · view only")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        scroll = QScrollArea()
        self.image_view = PreviewImage(image)
        scroll.setWidget(self.image_view)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(scroll, 1)
        bottom = QHBoxLayout()
        bottom.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.resize(min(1050, max(420, image.width + 36)),
                    min(820, max(320, image.height + 96)))

    def set_image(self, image: Image.Image) -> None:
        self.image_view.set_image(image)
