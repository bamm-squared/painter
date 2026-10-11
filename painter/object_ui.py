"""Right-side history and exact object controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .objects import PaintObject, object_label
from .theme import COLORS
from .icons import swatch_icon


class HistoryList(QListWidget):
    reordered = Signal(list)
    toggle_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_row = -1
        self._press_position = None
        self._target_row = -1
        self._dragging = False
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    def mousePressEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is not None and event.button() == Qt.MouseButton.LeftButton:
            value = item.data(Qt.ItemDataRole.UserRole)
            depth = len(value) - 1 if isinstance(value, tuple) else 0
            if (isinstance(value, (int, tuple)) and item.text().lstrip().startswith(("▾", "▸"))
                    and event.position().x() < 30 + depth*18):
                self.toggle_requested.emit(value)
                event.accept()
                return
        self._press_row = self.row(item) if item is not None and event.button() == Qt.MouseButton.LeftButton else -1
        self._press_position = event.position().toPoint()
        self._target_row = self._press_row
        self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self._press_row >= 0 and
                isinstance(self.item(self._press_row).data(Qt.ItemDataRole.UserRole), int) and
                event.buttons() & Qt.MouseButton.LeftButton):
            if (event.position().toPoint() - self._press_position).manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
            if self._dragging:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                item = self.itemAt(event.position().toPoint())
                if item is not None:
                    self._target_row = self.row(item)
                elif event.position().y() >= self.visualItemRect(self.item(self.count()-1)).bottom():
                    self._target_row = self.count()-1
                elif event.position().y() <= self.visualItemRect(self.item(0)).top():
                    self._target_row = 0
                self.viewport().update()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            source, destination = self._press_row, self._target_row
            self._press_row = -1
            self._target_row = -1
            self._dragging = False
            self.unsetCursor()
            self.viewport().update()
            if source != destination and destination >= 0:
                values = [self.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.count())]
                source_value = values[source]
                target_value = values[destination]
                if isinstance(target_value, tuple):
                    target_value = target_value[0]
                parents = [value for value in values if isinstance(value, int)]
                if source_value != target_value:
                    parents.remove(source_value)
                    parents.insert(parents.index(target_value) + (1 if source < destination else 0),
                                   source_value)
                    self.reordered.emit(list(reversed(parents)))
            event.accept()
            return
        self._press_row = -1
        self._target_row = -1
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._dragging and self._target_row >= 0:
            rect = self.visualItemRect(self.item(self._target_row))
            y = rect.bottom() + 1 if self._target_row > self._press_row else rect.top() - 1
            painter = QPainter(self.viewport())
            theme = QApplication.instance().property("painter_theme") or "dark"
            painter.setPen(QPen(QColor(COLORS[theme]["accent"]), 2))
            painter.drawLine(4, y, self.viewport().width()-4, y)
            painter.end()


class ObjectPanel(QWidget):
    selected = Signal(object)
    property_edited = Signal(str, object)
    point_edited = Signal(int, int, float)
    order_changed = Signal(list)
    delete_requested = Signal()
    move_requested = Signal(int)
    color_requested = Signal()
    fill_color_requested = Signal()
    font_requested = Signal()
    transform_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("objectPanel")
        self.setFixedWidth(285)
        self._syncing = False
        self.collapsed: set[tuple[int, ...]] = set()
        self._objects: list[PaintObject] = []
        self._selected_index: int | None = None
        self._selected_child_path: tuple[int, ...] = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(9)
        title = QLabel("OBJECT DETAILS")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        details_scroll = QScrollArea()
        details_scroll.setObjectName("objectDetailsScroll")
        details_scroll.setWidgetResizable(True)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroll = details_scroll
        details = QWidget()
        self.details = details
        form = QFormLayout(details)
        form.setContentsMargins(2, 2, 2, 2)
        form.setSpacing(7)
        self.kind_label = QLabel("Select an item in History")
        form.addRow(self.kind_label)
        self.center_x = self.number(-100000, 100000)
        self.center_y = self.number(-100000, 100000)
        self.angle = self.number(-3600, 3600)
        self.width = QSpinBox()
        self.width.setRange(1, 200)
        self.arrow_width = self.number(0, 10000)
        self.arc_start = self.number(-3600, 3600)
        self.arc_end = self.number(-3600, 3600)
        self.font_size = QSpinBox()
        self.font_size.setRange(1, 500)
        self.filled = QCheckBox("Filled")
        self.color_button = QPushButton("Choose color…")
        self.color_button.clicked.connect(self.color_requested)
        self.fill_color_button = QPushButton("Choose fill color…")
        self.fill_color_button.clicked.connect(self.fill_color_requested)
        self.font_button = QPushButton("Font…")
        self.font_button.clicked.connect(self.font_requested)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Type directly on the canvas or here")
        self.text_edit.setMaximumHeight(80)
        transforms = QWidget()
        transform_layout = QHBoxLayout(transforms)
        transform_layout.setContentsMargins(0, 0, 0, 0)
        transform_layout.setSpacing(3)
        for label, operation, tip in (("↔", "flip_h", "Flip horizontally"),
                                      ("↕", "flip_v", "Flip vertically"),
                                      ("⟳", "rotate_cw", "Rotate 90° clockwise"),
                                      ("⟲", "rotate_ccw", "Rotate 90° counterclockwise"),
                                      ("Invert", "invert", "Invert RGB colors")):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(lambda checked=False, operation=operation: self.transform_requested.emit(operation))
            transform_layout.addWidget(button)
        self.transforms = transforms
        self.points_table = QTableWidget(0, 6)
        self.points_table.setHorizontalHeaderLabels(("X", "Y", "In X", "In Y", "Out X", "Out Y"))
        self.points_table.setMaximumHeight(165)
        self.points_table.horizontalHeader().setDefaultSectionSize(68)
        self.rows = {}
        for key, label, widget in (
            ("center_x", "Center X", self.center_x), ("center_y", "Center Y", self.center_y),
            ("angle", "Rotation °", self.angle), ("width", "Pen width", self.width),
            ("arrow_width", "Arrow width", self.arrow_width),
            ("arc_start", "Arc start °", self.arc_start), ("arc_end", "Arc end °", self.arc_end),
            ("filled", "", self.filled), ("color", "Color", self.color_button),
            ("fill_color", "Fill color", self.fill_color_button),
            ("font_size", "Font size", self.font_size), ("font", "Font", self.font_button),
            ("text", "Text", self.text_edit),
            ("transforms", "Transform", self.transforms),
            ("points", "Points", self.points_table),
        ):
            if key == "transforms":
                form.addRow(widget)
            else:
                form.addRow(label, widget)
            self.rows[key] = (form.labelForField(widget), widget)
        for key in ("center_x", "center_y", "angle", "width", "arrow_width", "arc_start", "arc_end", "font_size"):
            self.__dict__[key].valueChanged.connect(
                lambda value, key=key: self.emit_property(key, value))
        self.filled.toggled.connect(lambda value: self.emit_property("filled", value))
        self.text_edit.textChanged.connect(lambda: self.emit_property("text", self.text_edit.toPlainText()))
        self.points_table.cellChanged.connect(self.emit_point)
        details_scroll.setWidget(details)
        layout.addWidget(details_scroll, 1)
        history_title = QLabel("HISTORY · TOP FIRST")
        history_title.setObjectName("sectionTitle")
        layout.addWidget(history_title)
        self.history = HistoryList()
        self.history.setObjectName("objectHistory")
        self.history.currentItemChanged.connect(self.history_selected)
        self.history.reordered.connect(self.order_changed)
        self.history.toggle_requested.connect(self.toggle_custom)
        layout.addWidget(self.history, 1)
        controls = QHBoxLayout()
        for label, tip, callback in (
            ("↑", "Move object above the next one", lambda: self.move_requested.emit(1)),
            ("↓", "Move object below the previous one", lambda: self.move_requested.emit(-1)),
            ("Delete", "Remove selected object", self.delete_requested.emit),
        ):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.details.setEnabled(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Keep the details legible while leaving at least half the panel for history.
        self.details_scroll.setMaximumHeight(max(1, self.height() // 2 - 28))

    @staticmethod
    def number(minimum: float, maximum: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(1)
        spin.setSingleStep(1)
        return spin

    def emit_property(self, key: str, value) -> None:
        if not self._syncing:
            self.property_edited.emit(key, value)

    def emit_point(self, row: int, column: int) -> None:
        if self._syncing:
            return
        item = self.points_table.item(row, column)
        if item is None:
            return
        try:
            value = float(item.text())
        except ValueError:
            return
        self.point_edited.emit(row, column, value)

    def history_selected(self, current, previous) -> None:
        if not self._syncing:
            self.selected.emit(current.data(Qt.ItemDataRole.UserRole) if current else None)

    def toggle_custom(self, value: int | tuple[int, ...]) -> None:
        path = (value,) if isinstance(value, int) else value
        if path in self.collapsed:
            self.collapsed.remove(path)
        else:
            self.collapsed.add(path)
        self.sync(self._objects, self._selected_index, self._selected_child_path)

    def sync(self, objects: list[PaintObject], selected_index: int | None,
             selected_child_path: tuple[int, ...] = ()) -> None:
        self._syncing = True
        self._objects = objects
        self._selected_index = selected_index
        self._selected_child_path = selected_child_path
        self.history.clear()
        selected_path = ((selected_index,) + selected_child_path if selected_index is not None else None)

        def append_children(parent: PaintObject, parent_path: tuple[int, ...], depth: int) -> None:
            if parent.kind != "custom" or parent_path in self.collapsed:
                return
            for child_index in range(len(parent.children)-1, -1, -1):
                child = parent.children[child_index]
                path = parent_path + (child_index,)
                prefix = ("▸ " if path in self.collapsed else "▾ ") if child.kind == "custom" else "↳ "
                item = QListWidgetItem("    "*depth + prefix + object_label(child))
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.history.addItem(item)
                if path == selected_path:
                    self.history.setCurrentItem(item)
                append_children(child, path, depth+1)

        for index in range(len(objects) - 1, -1, -1):
            parent = objects[index]
            path = (index,)
            prefix = ("▸ " if path in self.collapsed else "▾ ") if parent.kind == "custom" else ""
            item = QListWidgetItem(prefix + object_label(parent))
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.history.addItem(item)
            if path == selected_path:
                self.history.setCurrentItem(item)
            append_children(parent, path, 1)

        obj = None
        breadcrumb: list[str] = []
        if selected_index is not None and 0 <= selected_index < len(objects):
            obj = objects[selected_index]
            for child_index in selected_child_path:
                breadcrumb.append(obj.template_name or object_label(obj))
                if not 0 <= child_index < len(obj.children):
                    obj = None
                    break
                obj = obj.children[child_index]
        self.details.setEnabled(obj is not None)
        label = object_label(obj) if obj else "Select an item in History"
        if breadcrumb:
            label = " › ".join(breadcrumb + [label])
        self.kind_label.setText(label)
        self.rows["center_x"][0].setText("Local X" if selected_child_path else "Center X")
        self.rows["center_y"][0].setText("Local Y" if selected_child_path else "Center Y")
        self.rows["points"][0].setText("Local points" if selected_child_path else "Points")
        if obj is not None:
            red, green, blue, alpha = obj.color
            self.color_button.setIcon(swatch_icon(obj.color, 20))
            self.color_button.setIconSize(QSize(20, 20))
            self.color_button.setText("Gradient…" if obj.gradient else f"#{red:02X}{green:02X}{blue:02X} · α {alpha}")
            fill_red, fill_green, fill_blue, fill_alpha = obj.fill_color or obj.color
            self.fill_color_button.setIcon(swatch_icon((fill_red, fill_green, fill_blue, fill_alpha), 20))
            self.fill_color_button.setIconSize(QSize(20, 20))
            self.fill_color_button.setText("Gradient…" if obj.fill_gradient else
                                            f"#{fill_red:02X}{fill_green:02X}{fill_blue:02X} · α {fill_alpha}")
            cx, cy = obj.center()
            self.center_x.setValue(cx)
            self.center_y.setValue(cy)
            self.angle.setValue(obj.angle)
            self.width.setValue(obj.size)
            self.arrow_width.setValue(obj.arrow_width)
            self.arc_start.setValue(obj.start_angle)
            self.arc_end.setValue(obj.end_angle)
            self.font_size.setValue(obj.font_size)
            self.filled.setChecked(obj.filled)
            if self.text_edit.toPlainText() != obj.text:
                self.text_edit.setPlainText(obj.text)
            is_path = obj.kind == "spline"
            self.points_table.setColumnCount(6 if is_path else 2)
            self.points_table.setRowCount(len(obj.points))
            for row, (x, y) in enumerate(obj.points):
                values = [x, y]
                if is_path:
                    tangent = obj.tangents[row] if row < len(obj.tangents) else (0, 0, 0, 0)
                    values.extend(tangent)
                for column, value in enumerate(values):
                    self.points_table.setItem(row, column, QTableWidgetItem(f"{value:.1f}"))
        for key, (label, widget) in self.rows.items():
            visible = obj is not None and (
                key in ("center_x", "center_y", "points") and bool(obj.points) or
                key == "angle" and obj.kind not in ("fill", "cut") or
                key == "width" and obj.kind not in ("fill", "cut", "text", "image", "selection") or
                key == "transforms" and obj.kind not in ("fill", "cut") or
                key == "color" and obj.kind not in ("cut", "image", "selection", "custom") or
                key == "fill_color" and obj.filled and obj.kind in ("rectangle", "ellipse", "polygon", "arrow") or
                key == "arrow_width" and obj.kind == "arrow" or
                key in ("arc_start", "arc_end") and obj.kind == "arc" or
                key in ("font", "font_size", "text") and obj.kind == "text" or
                key == "filled" and obj.kind in ("rectangle", "ellipse", "polygon", "arrow"))
            if label is not None:
                label.setVisible(visible)
            widget.setVisible(visible)
        self._syncing = False
