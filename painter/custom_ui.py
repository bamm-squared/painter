"""Compact custom object rail and larger searchable gallery."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize, QPoint
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget, QSizePolicy, QFrame,
                               QMenu, QMessageBox, QToolButton)

from .custom_objects import CustomLibrary, CustomTemplate
from .dialog_ui import IndependentDialog


_ICON_CACHE: dict[tuple[str, int, int], QIcon] = {}


def invalidate_template_icon(template_id: str) -> None:
    for key in list(_ICON_CACHE):
        if key[0] == template_id:
            del _ICON_CACHE[key]


def template_icon(template: CustomTemplate, width: int = 80, height: int = 60) -> QIcon:
    key = (template.template_id, width, height)
    if key not in _ICON_CACHE:
        image = template.preview((width, height)).convert("RGBA")
        qimage = QImage(image.tobytes(), image.width, image.height, image.width*4,
                        QImage.Format.Format_RGBA8888).copy()
        _ICON_CACHE[key] = QIcon(QPixmap.fromImage(qimage))
    return _ICON_CACHE[key]


class CustomObjectHeading(QLabel):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TemplateButton(QPushButton):
    def __init__(self, template: CustomTemplate, compact: bool = False, parent=None):
        super().__init__(parent)
        self.template_id = template.template_id
        self.setAccessibleName(template.name)
        self.setToolTip(f"Place {template.name} · used {template.uses} times")
        preview = QLabel(self)
        preview.setObjectName("templatePreview")
        preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        size = QSize(42, 42) if compact else QSize(108, 70)
        preview.setFixedSize(size)
        preview.setPixmap(template_icon(template, size.width(), size.height()).pixmap(size))
        caption = QLabel(template.name, self)
        caption.setObjectName("templateCaption")
        caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        caption.setAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if compact else Qt.AlignmentFlag.AlignHCenter))
        if compact:
            self.setFixedHeight(50)
            self.setMinimumWidth(170)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            contents = QHBoxLayout(self)
            contents.setContentsMargins(5, 3, 5, 3)
            contents.setSpacing(5)
            contents.addWidget(preview)
            contents.addWidget(caption, 1)
        else:
            self.setFixedSize(145, 115)
            contents = QVBoxLayout(self)
            contents.setContentsMargins(5, 5, 5, 6)
            contents.setSpacing(0)
            contents.addWidget(preview, alignment=Qt.AlignmentFlag.AlignHCenter)
            contents.addStretch(1)
            caption.setFixedHeight(22)
            contents.addWidget(caption)


class CustomObjectGallery(IndependentDialog):
    library_changed = Signal()

    def __init__(self, library: CustomLibrary, parent=None):
        super().__init__(parent)
        self.library = library
        self.setWindowTitle("Custom objects")
        self.resize(760, 560)
        self.selected_id: str | None = None
        self.action: str | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("MOST USED"))
        self.popular_row = QHBoxLayout()
        self.popular_row.setContentsMargins(0, 0, 0, 0)
        self.popular_row.setSpacing(8)
        layout.addLayout(self.popular_row)
        layout.addWidget(QLabel("ALL OTHER OBJECTS · NAME ORDER"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.other_grid = QGridLayout(content)
        self.other_grid.setContentsMargins(0, 0, 0, 0)
        self.other_grid.setHorizontalSpacing(8)
        self.other_grid.setVerticalSpacing(8)
        self.other_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        layout.addWidget(QLabel("Click a tile to place it. Use ⋯ or right-click to edit or delete."))
        self.refresh_tiles()

    @staticmethod
    def clear_tiles(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()

    def make_tile(self, template: CustomTemplate) -> TemplateButton:
        button = TemplateButton(template)
        template_id = template.template_id
        button.clicked.connect(lambda checked=False: self.choose(template_id))
        button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(
            lambda point: self.show_tile_menu(template_id, button.mapToGlobal(point)))
        more = QToolButton(button)
        more.setObjectName("templateMenu")
        more.setText("⋯")
        more.setToolTip(f"Edit or delete {template.name}")
        more.setFixedSize(23, 23)
        more.move(button.width() - 29, 6)
        more.clicked.connect(
            lambda checked=False: self.show_tile_menu(
                template_id, more.mapToGlobal(QPoint(0, more.height()))))
        return button

    def refresh_tiles(self) -> None:
        self.clear_tiles(self.popular_row)
        self.clear_tiles(self.other_grid)
        popular, rest = self.library.gallery()
        for template in popular:
            self.popular_row.addWidget(self.make_tile(template))
        self.popular_row.addStretch()
        for index, template in enumerate(rest):
            self.other_grid.addWidget(self.make_tile(template), index // 4, index % 4)

    def show_tile_menu(self, template_id: str, position: QPoint) -> None:
        if template_id not in self.library.templates:
            return
        menu = QMenu(self)
        menu.addAction("Edit…", lambda: self.edit_template(template_id))
        menu.addAction("Delete…", lambda: self.delete_template(template_id))
        self._tile_menu = menu
        menu.popup(position)

    def choose(self, template_id: str) -> None:
        self.selected_id = template_id
        self.action = "place"
        self.accept()

    def edit_template(self, template_id: str) -> None:
        self.selected_id = template_id
        self.action = "edit"
        self.accept()

    def delete_template(self, template_id: str) -> None:
        template = self.library.templates[template_id]
        answer = QMessageBox.question(
            self, "Delete custom object",
            f'Delete "{template.name}" from the browser? Objects already on canvases will remain.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.library.delete(template_id)
            invalidate_template_icon(template_id)
        except OSError as error:
            QMessageBox.warning(self, "Cannot delete custom object", str(error))
            return
        self.refresh_tiles()
        self.library_changed.emit()
