"""PySide6 interface for Painter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
from uuid import uuid4
from math import atan2, degrees, hypot
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageChops
from PySide6.QtCore import Qt, QSize, QRectF, Signal, QEvent
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QImage, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QDialogButtonBox,
    QFileDialog, QFontDialog, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
    QDoubleSpinBox, QPlainTextEdit, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from .color_dialog import ColorDialog
from .custom_objects import CustomLibrary, template_from_document
from .custom_ui import CustomObjectGallery, CustomObjectHeading, TemplateButton, invalidate_template_icon
from .gradient import gradient_canvas
from .fonts import font_file_for_family, load_font
from .document import Document, draw_stroke
from .export import export_filters, export_target, save_image, supported_formats
from .grid import add_grid, snap_point
from .icons import line_icon, set_icon_color, swatch_icon
from .layer_ui import CARD_WIDTH, LayerStrip, PreviewDialog, layer_thumbnail
from .objects import PaintObject, apply_object, automatic_tangents, object_mask, rotate_point, three_point_shape, wrapped_text_lines
from .object_ui import ObjectPanel
from .theme import COLORS, apply_theme


PRESET_COLORS = (
    ("Transparent · alpha 0", (0, 0, 0, 0)),
    ("Black", (0, 0, 0, 255)),
    ("White", (255, 255, 255, 255)),
    ("Slate", (91, 101, 119, 255)),
    ("50% black", (0, 0, 0, 128)),
    ("Red", (231, 69, 78, 255)),
    ("Orange", (247, 143, 57, 255)),
    ("Yellow", (251, 205, 63, 255)),
    ("Lime", (164, 213, 65, 255)),
    ("Green", (52, 171, 117, 255)),
    ("Cyan", (41, 191, 203, 255)),
    ("Blue", (58, 120, 231, 255)),
    ("Violet", (133, 91, 213, 255)),
    ("Pink", (225, 95, 167, 255)),
    ("Brown", (151, 102, 73, 255)),
)

TOOL_MODES = {
    "select": (("Rectangle selection", "select"), ("Polygon selection · Enter to finish", "select_polygon"),
               ("Freeform selection", "select_freeform")),
    "line": (("Line", "line"), ("Spline · click points, Enter", "spline"),
             ("Polyline · click points, Enter", "polyline"),
             ("Arrow · drag endpoints", "arrow"), ("Arrow · 3 points", "arrow_3point")),
    "rectangle": (("Rectangle · opposite corners", "rectangle"),
                  ("Rectangle · 3 points", "rectangle_3point"),
                  ("Polygon · click points, Enter", "polygon")),
    "ellipse": (("Oval · bounding box", "ellipse"),
                ("Circle · center and radius", "circle"),
                ("Oval · center and 2 axes", "ellipse_3point"),
                ("Arc · bounding box", "arc"), ("Arc · through 3 points", "arc_3point")),
}
TOOL_BASE = {mode: base for base, options in TOOL_MODES.items() for _, mode in options}


def pil_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    return QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4,
                  QImage.Format.Format_RGBA8888).copy()


def colorized_mask(mask: Image.Image, color: tuple[int, int, int, int]) -> Image.Image:
    result = Image.new("RGBA", mask.size, color[:3] + (0,))
    result.putalpha(mask.point(lambda value: value * color[3] // 255))
    return result


class SwatchButton(QToolButton):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def styled_preview(obj: PaintObject, dimensions: tuple[int, int]) -> Image.Image:
    return apply_object(Image.new("RGBA", dimensions), obj)


@dataclass
class EditableShape:
    tool: str
    x0: int
    y0: int
    x1: int
    y1: int
    color: tuple[int, int, int, int]
    size: int
    filled: bool
    layer_index: int
    fill_color: tuple[int, int, int, int] | None = None
    angle: float = 0.0
    arrow_width: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 180.0
    color_ref: str | None = None
    fill_color_ref: str | None = None
    gradient: dict | None = None
    fill_gradient: dict | None = None

    def to_object(self) -> PaintObject:
        return PaintObject(self.tool, [(self.x0, self.y0), (self.x1, self.y1)],
                           self.color, self.size, self.filled, angle=self.angle,
                           fill_color=self.fill_color, color_ref=self.color_ref,
                           fill_color_ref=self.fill_color_ref,
                           gradient=deepcopy(self.gradient), fill_gradient=deepcopy(self.fill_gradient))

    def normalize(self) -> None:
        if self.tool != "line":
            self.x0, self.x1 = sorted((self.x0, self.x1))
            self.y0, self.y1 = sorted((self.y0, self.y1))

    def handles(self) -> dict[str, tuple[float, float]]:
        if self.tool == "line":
            return {"start": (self.x0, self.y0), "end": (self.x1, self.y1)}
        left, right = sorted((self.x0, self.x1))
        top, bottom = sorted((self.y0, self.y1))
        center = ((left + right) / 2, (top + bottom) / 2)
        def turned(point):
            return rotate_point(point, center, self.angle)
        if self.tool == "rectangle":
            handles = {"nw": turned((left, top)), "ne": turned((right, top)),
                       "se": turned((right, bottom)), "sw": turned((left, bottom))}
        else:
            handles = {"left": turned((left, center[1])),
                       "right": turned((right, center[1])),
                       "top": turned((center[0], top)),
                       "bottom": turned((center[0], bottom))}
        handles["center"] = center
        handles["rotate"] = turned((center[0], top - 26))
        return handles


@dataclass
class EditorSnapshot:
    document: Document
    custom_colors: dict[str, tuple[int, int, int, int]]


class Canvas(QWidget):
    position_changed = Signal(int, int)

    def __init__(self, editor: MainWindow):
        super().__init__()
        self.editor = editor
        self.zoom = 1.0
        self.dragging = False
        self.start = (0, 0)
        self.points: list[tuple[int, int]] = []
        self.preview: Image.Image | None = None
        self.erase_mask: Image.Image | None = None
        self.preview_fill_color: tuple[int, int, int, int] | None = None
        self.selection: tuple[int, int, int, int] | None = None
        self.selection_mask: Image.Image | None = None
        self.selection_points: list[tuple[int, int]] = []
        self.selection_hover: tuple[int, int] | None = None
        self.selection_outline: list[tuple[int, int]] = []
        self.shape: EditableShape | None = None
        self.shape_drag: str | None = None
        self.shape_before_drag: EditableShape | None = None
        self.object_drag: str | None = None
        self.object_before_drag: PaintObject | None = None
        self.new_drag_object: PaintObject | None = None
        self.path_draft: PaintObject | None = None
        self.path_hover: tuple[int, int] | None = None
        self.text_editor: QPlainTextEdit | None = None
        self.text_draft: PaintObject | None = None
        self.drag_anchor = (0, 0)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update_size()

    def update_size(self) -> None:
        self.setFixedSize(QSize(round(self.editor.document.width * self.zoom),
                                round(self.editor.document.height * self.zoom)))
        self.update()

    def image_point(self, event) -> tuple[int, int]:
        position = event.position()
        return int(position.x() / self.zoom), int(position.y() / self.zoom)

    def snapped_point(self, point: tuple[int, int]) -> tuple[int, int]:
        if not self.editor.grid_snap:
            return point
        return snap_point(point, self.editor.grid_spacing,
                          (self.editor.document.width, self.editor.document.height))

    def in_bounds(self, point: tuple[int, int]) -> bool:
        return 0 <= point[0] < self.editor.document.width and 0 <= point[1] < self.editor.document.height

    def paintEvent(self, event) -> None:
        doc = self.editor.document
        painter = QPainter(self)
        tile = max(4, round(12 * self.zoom))
        for y in range(0, self.height(), tile):
            for x in range(0, self.width(), tile):
                painter.fillRect(x, y, min(tile, self.width() - x), min(tile, self.height() - y),
                                 QColor("#ffffff") if (x // tile + y // tile) % 2 == 0 else QColor("#d8d8d8"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 1)
        image = pil_to_qimage(doc.composite(None if self.text_editor is not None else self.preview,
                                           self.erase_mask, through_index=doc.active,
                                           erase_color=self.preview_fill_color or self.editor.background_color))
        painter.drawImage(QRectF(0, 0, self.width(), self.height()), image)
        if self.editor.grid_visible:
            ink = QColor("#43516d")
            ink.setAlpha(105)
            painter.setPen(QPen(ink, 1))
            for x in range(0, doc.width, self.editor.grid_spacing):
                screen_x = round(x * self.zoom)
                painter.drawLine(screen_x, 0, screen_x, self.height() - 1)
            for y in range(0, doc.height, self.editor.grid_spacing):
                screen_y = round(y * self.zoom)
                painter.drawLine(0, screen_y, self.width() - 1, screen_y)
        if self.new_drag_object is not None and self.new_drag_object.kind == "text":
            (x0, y0), (x1, y1) = self.new_drag_object.points[:2]
            painter.setPen(QPen(QColor("#8da0ff"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(min(x0, x1) * self.zoom, min(y0, y1) * self.zoom,
                                    abs(x1 - x0) * self.zoom, abs(y1 - y0) * self.zoom))
        if self.selection is not None:
            left, top, right, bottom = self.selection
            painter.setPen(QPen(QColor("#111111"), 1, Qt.PenStyle.DashLine))
            if self.selection_outline:
                closed = self.selection_outline + self.selection_outline[:1]
                for first, second in zip(closed, closed[1:]):
                    painter.drawLine(round(first[0]*self.zoom), round(first[1]*self.zoom),
                                     round(second[0]*self.zoom), round(second[1]*self.zoom))
            else:
                painter.drawRect(QRectF(left * self.zoom, top * self.zoom,
                                        (right - left) * self.zoom, (bottom - top) * self.zoom))
            painter.setPen(QPen(QColor("#8da0ff"), 2))
            painter.setBrush(QColor("#ffffff"))
            for x, y in ((left, top), (right, top), (right, bottom), (left, bottom)):
                painter.drawRect(QRectF(x*self.zoom-5, y*self.zoom-5, 10, 10))
        if self.selection_points:
            painter.setPen(QPen(QColor("#8da0ff"), 2, Qt.PenStyle.DashLine))
            outline = self.selection_points + ([self.selection_hover] if self.selection_hover else [])
            for first, second in zip(outline, outline[1:]):
                painter.drawLine(round(first[0]*self.zoom), round(first[1]*self.zoom),
                                 round(second[0]*self.zoom), round(second[1]*self.zoom))
        if self.shape is not None and self.shape_drag is None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#425ccc"), 2))
            handles = self.shape.handles()
            if "rotate" in handles:
                center, rotate = handles["center"], handles["rotate"]
                painter.drawLine(round((center[0]+.5)*self.zoom), round((center[1]+.5)*self.zoom),
                                 round((rotate[0]+.5)*self.zoom), round((rotate[1]+.5)*self.zoom))
            painter.setBrush(QColor("#ffffff"))
            for name, (x, y) in handles.items():
                cx, cy = (x + 0.5) * self.zoom, (y + 0.5) * self.zoom
                if self.shape.tool == "rectangle" and name not in ("center", "rotate"):
                    painter.drawRect(QRectF(cx - 6, cy - 6, 12, 12))
                else:
                    painter.drawEllipse(QRectF(cx - 6, cy - 6, 12, 12))
                if name == "center":
                    painter.drawLine(int(cx - 3), int(cy), int(cx + 3), int(cy))
                    painter.drawLine(int(cx), int(cy - 3), int(cx), int(cy + 3))
        selected = self.editor.selected_canvas_object() if not self.editor.selected_child_path else None
        if self.shape is None and self.editor.tool in ("select", "select_polygon", "select_freeform") and selected is not None:
            self.paint_object_handles(painter, selected)
        if self.path_draft is not None:
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(QPen(QColor("#8da0ff"), 2))
            for x, y in self.path_draft.points:
                painter.drawEllipse(QRectF((x+.5)*self.zoom-4, (y+.5)*self.zoom-4, 8, 8))
        painter.end()

    def update_path_preview(self) -> None:
        if self.path_draft is None:
            return
        draft = self.path_draft.copy()
        if self.path_hover is not None and (not draft.points or self.path_hover != draft.points[-1]):
            draft.points.append(self.path_hover)
        if draft.kind in ("rectangle_3point", "ellipse_3point", "arrow_3point", "arc_3point"):
            if len(draft.points) >= 3:
                source = draft
                draft = three_point_shape(draft.kind, draft.points, draft.color, draft.size,
                                          draft.filled, draft.fill_color)
                draft.color_ref, draft.fill_color_ref = source.color_ref, source.fill_color_ref
                draft.gradient, draft.fill_gradient = deepcopy(source.gradient), deepcopy(source.fill_gradient)
            else:
                draft.kind = "polyline"
        elif draft.kind == "spline":
            draft.tangents = automatic_tangents(draft.points)
        if draft.kind == "polygon" and len(draft.points) < 3:
            draft.kind = "polyline"
        self.preview_object(draft)
        self.update()
        self.editor.update_preview()

    def preview_object(self, obj: PaintObject) -> None:
        dimensions = (self.editor.document.width, self.editor.document.height)
        if obj.filled and obj.kind in ("rectangle", "ellipse", "polygon", "arrow"):
            self.erase_mask = object_mask(obj, dimensions)
            self.preview = styled_preview(obj, dimensions)
            self.preview_fill_color = (0, 0, 0, 0)
        else:
            self.preview = styled_preview(obj, dimensions)
            self.erase_mask = None
            self.preview_fill_color = None

    def finish_path(self) -> None:
        draft = self.path_draft
        if draft is None:
            return
        required = 3 if draft.kind in ("polygon", "rectangle_3point", "ellipse_3point",
                                        "arrow_3point", "arc_3point") else 2
        if len(draft.points) < required:
            self.editor.statusBar().showMessage(f"Add {required - len(draft.points)} more point(s)")
            return
        if draft.kind.endswith("_3point"):
            source = draft
            draft = three_point_shape(draft.kind, draft.points, draft.color, draft.size,
                                      draft.filled, draft.fill_color)
            draft.color_ref, draft.fill_color_ref = source.color_ref, source.fill_color_ref
            draft.gradient, draft.fill_gradient = deepcopy(source.gradient), deepcopy(source.fill_gradient)
        elif draft.kind == "spline":
            draft.tangents = automatic_tangents(draft.points)
        self.path_draft = None
        self.path_hover = None
        self.preview = None
        self.erase_mask = None
        self.preview_fill_color = None
        self.editor.begin_change()
        self.editor.add_object(draft)
        self.editor.selected_object_index = len(self.editor.document.layers[self.editor.document.active].objects) - 1
        self.editor.changed()
        self.editor.set_tool("select")
        self.editor.statusBar().showMessage("Shape placed; edit points and tangents in the canvas or Object details")

    def cancel_path(self) -> None:
        self.path_draft = None
        self.path_hover = None
        self.preview = None
        self.erase_mask = None
        self.preview_fill_color = None
        self.update()
        self.editor.update_preview()

    def update_new_drag(self, point: tuple[int, int]) -> None:
        obj = self.new_drag_object
        if obj is None:
            return
        start = self.start
        if self.editor.tool == "circle":
            radius = hypot(point[0]-start[0], point[1]-start[1])
            obj.points = [(start[0]-radius, start[1]-radius),
                          (start[0]+radius, start[1]+radius)]
        else:
            obj.points = [start, point]
        self.preview_object(obj)
        self.update()
        self.editor.update_preview()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.selection_points and self.editor.tool == "select_polygon":
            self.finish_polygon_selection()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.path_draft is not None:
            self.finish_path()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.selection_points:
            self.selection_points = []
            self.selection_hover = None
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.path_draft is not None:
            self.cancel_path()
            event.accept()
            return
        super().keyPressEvent(event)

    def finish_polygon_selection(self) -> None:
        points = self.selection_points
        self.selection_points = []
        self.selection_hover = None
        if len(points) >= 3:
            mask = Image.new("L", (self.editor.document.width, self.editor.document.height))
            ImageDraw.Draw(mask).polygon(points, fill=255)
            self.selection_mask = mask
            self.selection_outline = points.copy()
            self.selection = mask.getbbox()
            self.editor.selected_object_index = None
            self.editor.refresh()
        self.update()

    def selection_handle_at(self, position) -> str | None:
        if self.selection is None:
            return None
        left, top, right, bottom = self.selection
        for name, (x, y) in {"nw": (left, top), "ne": (right, top),
                             "se": (right, bottom), "sw": (left, bottom)}.items():
            if hypot(position.x()-x*self.zoom, position.y()-y*self.zoom) <= 6:
                return name
        point = (int(position.x()/self.zoom), int(position.y()/self.zoom))
        if self.in_bounds(point) and (self.selection_mask.getpixel(point) if self.selection_mask is not None
                                      else left <= point[0] < right and top <= point[1] < bottom):
            return "center"
        return None

    def start_text(self, point: tuple[int, int], opposite: tuple[int, int] | None = None) -> None:
        self.commit_text()
        if opposite is None or opposite == point:
            opposite = (min(self.editor.document.width - 1, point[0] + 220),
                        min(self.editor.document.height - 1, point[1] + 100))
        left, right = sorted((point[0], opposite[0]))
        top, bottom = sorted((point[1], opposite[1]))
        self.text_draft = PaintObject("text", [(left, top), (right, bottom)], self.editor.color,
                                      font_size=max(12, self.editor.size.value() * 4),
                                      color_ref=self.editor.active_color_ref,
                                      gradient=deepcopy(self.editor.color_gradient))
        editor = QPlainTextEdit(self)
        editor.setPlaceholderText("Type here · Ctrl+Enter to place")
        colors = COLORS[self.editor.theme]
        red, green, blue, _ = self.text_draft.color
        background = "#f8fafc" if red*0.299 + green*0.587 + blue*0.114 < 135 else "#19212e"
        editor.setStyleSheet(f"QPlainTextEdit {{ color: #{red:02x}{green:02x}{blue:02x}; background: {background}; "
                             f"border: 1px solid {colors['accent']}; padding: 3px; }}")
        from PySide6.QtGui import QFont
        font = QFont("DejaVu Sans")
        font.setPixelSize(max(8, round(self.text_draft.font_size * self.zoom)))
        editor.setFont(font)
        x, y = round(left*self.zoom), round(top*self.zoom)
        editor.setGeometry(x, y, max(28, round((right-left)*self.zoom)),
                           max(36, round((bottom-top)*self.zoom)))
        editor.textChanged.connect(self.update_text_preview)
        self.text_editor = editor
        editor.show()
        editor.setFocus()

    def update_text_preview(self) -> None:
        if self.text_editor is None or self.text_draft is None:
            return
        self.text_draft.text = self.text_editor.toPlainText()
        if len(self.text_draft.points) >= 2:
            (left, top), (right, bottom) = self.text_draft.points[:2]
            font = load_font(self.text_draft.font_family, self.text_draft.font_size,
                             self.text_draft.font_name)
            line_count = len(wrapped_text_lines(self.text_draft.text, font, right - left))
            line_height = font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + 4
            required_height = max(bottom - top, line_count * line_height + 10)
            self.text_editor.resize(self.text_editor.width(), max(36, round(required_height * self.zoom)))
        self.preview = styled_preview(self.text_draft, (self.editor.document.width,
                                                        self.editor.document.height))
        self.editor.update_preview()

    def commit_text(self) -> None:
        editor = self.text_editor
        draft = self.text_draft
        if editor is None:
            return
        self.text_editor = None
        self.text_draft = None
        editor.hide()
        editor.deleteLater()
        self.preview = None
        if draft is not None and draft.text.strip():
            self.editor.begin_change()
            self.editor.add_object(draft)
            self.editor.selected_object_index = len(self.editor.document.layers[self.editor.document.active].objects) - 1
            self.editor.changed()
        else:
            self.update()
            self.editor.update_preview()

    def cancel_text(self) -> None:
        if self.text_editor is not None:
            editor = self.text_editor
            self.text_editor = None
            self.text_draft = None
            self.preview = None
            editor.hide()
            editor.deleteLater()
            self.update()
            self.editor.update_preview()

    def paint_object_handles(self, painter: QPainter, obj: PaintObject) -> None:
        handles = obj.handles()
        center = handles.get("center")
        rotate = handles.get("rotate")
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#8da0ff"), 2))
        if obj.kind in ("text", "image", "selection", "custom") and all(name in handles for name in ("nw", "ne", "se", "sw")):
            painter.setPen(QPen(QColor("#8da0ff"), 1, Qt.PenStyle.DashLine))
            corners = [handles[name] for name in ("nw", "ne", "se", "sw", "nw")]
            for first, second in zip(corners, corners[1:]):
                painter.drawLine(round((first[0]+.5)*self.zoom), round((first[1]+.5)*self.zoom),
                                 round((second[0]+.5)*self.zoom), round((second[1]+.5)*self.zoom))
            painter.setPen(QPen(QColor("#8da0ff"), 2))
        if center is not None and rotate is not None:
            painter.drawLine(round((center[0]+.5)*self.zoom), round((center[1]+.5)*self.zoom),
                             round((rotate[0]+.5)*self.zoom), round((rotate[1]+.5)*self.zoom))
        painter.setBrush(QColor("#ffffff"))
        for name, (x, y) in handles.items():
            cx, cy = (x + .5)*self.zoom, (y + .5)*self.zoom
            box = QRectF(cx - 6, cy - 6, 12, 12)
            if name == "rotate":
                painter.setBrush(QColor("#8da0ff"))
            if obj.kind in ("rectangle", "polygon", "text", "image", "selection", "custom") and name not in ("rotate", "center"):
                painter.drawRect(box)
            else:
                painter.drawEllipse(box)
            if name == "rotate":
                painter.setBrush(QColor("#ffffff"))

    def handle_at(self, position) -> str | None:
        if self.shape is None:
            return None
        matches = []
        for name, (x, y) in self.shape.handles().items():
            distance = ((position.x() - (x + 0.5) * self.zoom) ** 2 +
                        (position.y() - (y + 0.5) * self.zoom) ** 2) ** 0.5
            if distance <= 10:
                matches.append((distance, name))
        return min(matches)[1] if matches else None

    def update_handle_cursor(self, position) -> None:
        handle = self.handle_at(position) if self.shape is not None else (
            self.selection_handle_at(position) or self.selected_handle_at(position)
            if self.editor.tool in ("select", "select_polygon", "select_freeform") else None)
        if handle == "rotate":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Drag the orientation handle to rotate")
            return
        if handle == "center" or handle in ("start", "end", "width") or (handle is not None and
                (handle.startswith(("p", "in", "out")) or self.shape is not None and self.shape.tool == "line")):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.setToolTip("Drag to move" if handle == "center" else "Drag to adjust this point")
        elif handle is not None:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if handle in ("nw", "se")
                           else Qt.CursorShape.SizeBDiagCursor if handle in ("ne", "sw")
                           else Qt.CursorShape.SizeHorCursor if handle in ("left", "right")
                           else Qt.CursorShape.SizeVerCursor if handle in ("top", "bottom")
                           else Qt.CursorShape.SizeAllCursor)
            self.setToolTip("Drag to resize the shape")
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.setToolTip("")

    def selected_handle_at(self, position) -> str | None:
        if self.editor.selected_child_path:
            return None
        obj = self.editor.selected_canvas_object()
        if obj is None:
            return None
        matches = []
        for name, (x, y) in obj.handles().items():
            distance = hypot(position.x() - (x + .5) * self.zoom,
                             position.y() - (y + .5) * self.zoom)
            if distance <= 10:
                matches.append((distance, name))
        return min(matches)[1] if matches else None

    def object_at(self, point: tuple[int, int]) -> int | None:
        objects = self.editor.document.layers[self.editor.document.active].objects or []
        for index in range(len(objects) - 1, -1, -1):
            obj = objects[index]
            if obj.kind in ("text", "image", "selection") and len(obj.points) >= 2:
                local = rotate_point(point, obj.center(), -obj.angle)
                (x0, y0), (x1, y1) = obj.points[:2]
                if min(x0, x1) <= local[0] <= max(x0, x1) and min(y0, y1) <= local[1] <= max(y0, y1):
                    return index
            if object_mask(obj, (self.editor.document.width, self.editor.document.height)).getpixel(point):
                return index
        return None

    def update_object_drag(self, point: tuple[int, int]) -> None:
        obj = self.editor.selected_canvas_object()
        original = self.object_before_drag
        handle = self.object_drag
        if obj is None or original is None or handle is None:
            return
        center = original.center()
        local = rotate_point(point, center, -original.angle)
        obj.points = original.points.copy()
        obj.tangents = original.tangents.copy()
        obj.angle = original.angle
        obj.arrow_width = original.arrow_width
        obj.start_angle = original.start_angle
        obj.end_angle = original.end_angle
        obj.mask = original.mask.copy() if original.mask is not None else None
        if handle == "center":
            dx, dy = point[0] - self.drag_anchor[0], point[1] - self.drag_anchor[1]
            if self.editor.grid_snap:
                target = self.snapped_point((round(center[0] + dx), round(center[1] + dy)))
                dx, dy = target[0] - center[0], target[1] - center[1]
            obj.translated(dx, dy)
        elif handle == "rotate":
            before = atan2(self.drag_anchor[1] - center[1], self.drag_anchor[0] - center[0])
            after = atan2(point[1] - center[1], point[0] - center[0])
            obj.angle = original.angle + degrees(after - before)
        elif handle in ("nw", "ne", "se", "sw"):
            first, second = list(obj.points[0]), list(obj.points[1])
            if "w" in handle:
                first[0] = local[0]
            else:
                second[0] = local[0]
            if "n" in handle:
                first[1] = local[1]
            else:
                second[1] = local[1]
            obj.points[:2] = [tuple(first), tuple(second)]
        elif handle in ("left", "right", "top", "bottom"):
            first, second = list(obj.points[0]), list(obj.points[1])
            if handle == "left":
                first[0] = local[0]
            if handle == "right":
                second[0] = local[0]
            if handle == "top":
                first[1] = local[1]
            if handle == "bottom":
                second[1] = local[1]
            obj.points[:2] = [tuple(first), tuple(second)]
        elif handle in ("start", "end"):
            obj.points[0 if handle == "start" else 1] = local
        elif handle == "width" and len(obj.points) >= 2:
            (sx, sy), (ex, ey) = original.points[:2]
            length = max(1, hypot(ex-sx, ey-sy))
            obj.arrow_width = 2 * abs((local[0]-center[0])*(-(ey-sy)/length) +
                                      (local[1]-center[1])*((ex-sx)/length))
        elif handle in ("arc_start", "arc_end"):
            (x0, y0), (x1, y1) = original.points[:2]
            rx, ry = max(1, abs(x1-x0)/2), max(1, abs(y1-y0)/2)
            angle = degrees(atan2((local[1]-center[1])/ry, (local[0]-center[0])/rx)) % 360
            if handle == "arc_start":
                obj.start_angle = angle
            else:
                obj.end_angle = angle
        elif handle.startswith("p") and handle[1:].isdigit():
            obj.points[int(handle[1:])] = local
        elif handle.startswith(("in", "out")):
            incoming = handle.startswith("in")
            index = int(handle[2:] if incoming else handle[3:])
            tangent = list(obj.tangents[index])
            tangent[0 if incoming else 2] = local[0] - obj.points[index][0]
            tangent[1 if incoming else 3] = local[1] - obj.points[index][1]
            obj.tangents[index] = tuple(tangent)
        self.editor.document.rebuild_layer()
        self.update()
        self.editor.update_preview()

    def update_shape_drag(self, point: tuple[int, int]) -> None:
        if self.shape is None or self.shape_drag is None:
            return
        shape, handle = self.shape, self.shape_drag
        if handle == "create":
            shape.x1, shape.y1 = point
        else:
            original = self.shape_before_drag
            assert original is not None
            center = ((original.x0 + original.x1) / 2, (original.y0 + original.y1) / 2)
            local = rotate_point(point, center, -original.angle)
            if handle == "start":
                shape.x0, shape.y0 = point
            elif handle == "end":
                shape.x1, shape.y1 = point
            elif handle in ("nw", "ne", "se", "sw"):
                if "w" in handle:
                    shape.x0 = local[0]
                else:
                    shape.x1 = local[0]
                if "n" in handle:
                    shape.y0 = local[1]
                else:
                    shape.y1 = local[1]
            elif handle == "left":
                shape.x0 = local[0]
            elif handle == "right":
                shape.x1 = local[0]
            elif handle == "top":
                shape.y0 = local[1]
            elif handle == "bottom":
                shape.y1 = local[1]
            elif handle == "center":
                width, height = self.editor.document.width, self.editor.document.height
                dx, dy = point[0] - self.drag_anchor[0], point[1] - self.drag_anchor[1]
                if self.editor.grid_snap:
                    target = self.snapped_point((round(center[0] + dx), round(center[1] + dy)))
                    dx, dy = target[0] - center[0], target[1] - center[1]
                dx = max(-original.x0, min(width - 1 - original.x1, dx))
                dy = max(-original.y0, min(height - 1 - original.y1, dy))
                shape.x0, shape.x1 = original.x0 + dx, original.x1 + dx
                shape.y0, shape.y1 = original.y0 + dy, original.y1 + dy
            elif handle == "rotate":
                before = atan2(self.drag_anchor[1] - center[1], self.drag_anchor[0] - center[0])
                after = atan2(point[1] - center[1], point[0] - center[0])
                shape.angle = original.angle + degrees(after - before)
        self.preview_object(shape.to_object())
        self.update()
        self.editor.update_preview()

    def finalize_shape(self) -> None:
        if self.shape is None:
            return
        shape = self.shape
        self.shape = None
        self.shape_drag = None
        self.shape_before_drag = None
        self.dragging = False
        self.preview = None
        self.erase_mask = None
        self.preview_fill_color = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip("")
        self.editor.pending = self.editor.snapshot()
        self.editor.add_object(shape.to_object(), shape.layer_index)
        self.editor.selected_object_index = len(self.editor.document.layers[shape.layer_index].objects) - 1
        self.editor.changed()
        self.editor.statusBar().showMessage("Shape placed")

    def cancel_shape(self) -> None:
        self.shape = None
        self.shape_drag = None
        self.shape_before_drag = None
        self.dragging = False
        self.preview = None
        self.erase_mask = None
        self.preview_fill_color = None
        self.editor.statusBar().showMessage("Shape canceled")
        self.update_handle_cursor(self.mapFromGlobal(self.cursor().pos()))
        self.update()
        self.editor.update_preview()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            if self.shape is not None:
                self.finalize_shape()
            return
        point = self.image_point(event)
        if not self.in_bounds(point):
            return
        event.accept()
        editor = self.editor
        tool = editor.tool
        if tool not in ("picker", "fill", "select", "select_polygon", "select_freeform"):
            point = self.snapped_point(point)
        if self.shape is not None:
            handle = self.handle_at(event.position())
            if handle is not None:
                self.shape_drag = handle
                self.shape_before_drag = replace(self.shape)
                self.drag_anchor = point
                self.dragging = True
                if self.shape.tool == "line" or handle == "center":
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                event.accept()
                return
            self.finalize_shape()
        if tool in ("select", "select_polygon", "select_freeform"):
            selection_handle = self.selection_handle_at(event.position())
            if selection_handle is not None:
                editor.lift_selection()
                self.object_drag = selection_handle
                self.object_before_drag = editor.selected_object().copy()
                self.drag_anchor = point
                self.dragging = True
                self.update_handle_cursor(event.position())
                return
        selected_handle = self.selected_handle_at(event.position()) if tool in ("select", "select_polygon", "select_freeform") else None
        if selected_handle is None and tool in ("select", "select_polygon", "select_freeform"):
            selected = editor.selected_object()
            if selected is not None and selected.kind in ("image", "selection") and self.object_at(point) == editor.selected_object_index:
                selected_handle = "center"
        if selected_handle is not None:
            self.editor.pending = self.editor.snapshot()
            self.object_drag = selected_handle
            self.object_before_drag = self.editor.selected_canvas_object().copy()
            self.drag_anchor = point
            self.dragging = True
            self.update_handle_cursor(event.position())
            return
        tool = editor.tool
        if tool in ("polyline", "spline", "polygon", "rectangle_3point",
                    "ellipse_3point", "arrow_3point", "arc_3point"):
            self.setFocus()
            if self.path_draft is None or self.path_draft.kind != tool:
                self.path_draft = PaintObject(tool, color=editor.color,
                                              size=editor.size.value(), filled=editor.shape_fill.isChecked(),
                                              fill_color=editor.background_color,
                                              color_ref=editor.active_color_ref,
                                              fill_color_ref=editor.active_background_ref,
                                              gradient=deepcopy(editor.color_gradient),
                                              fill_gradient=deepcopy(editor.background_gradient))
            self.path_draft.points.append(point)
            self.path_hover = point
            if tool.endswith("_3point") and len(self.path_draft.points) == 3:
                self.finish_path()
            else:
                self.update_path_preview()
                editor.statusBar().showMessage("Click to add points; press Enter to finish, Esc to cancel")
            return
        if tool == "picker":
            editor.set_color(editor.document.composite(through_index=editor.document.active).getpixel(point))
            return
        if tool == "fill":
            editor.begin_change()
            if editor.document.flood_fill(point, editor.color, editor.tolerance.value(),
                                          color_ref=editor.active_color_ref,
                                          gradient=deepcopy(editor.color_gradient)):
                editor.selected_object_index = len(editor.document.layers[editor.document.active].objects) - 1
                editor.changed()
            else:
                editor.discard_change()
            return
        if tool == "custom":
            editor.place_custom_template(point)
            return
        if tool == "text":
            self.dragging = True
            self.start = point
            self.new_drag_object = PaintObject("text", [point, point], editor.color)
            self.update()
            return
        if tool in ("select", "select_polygon", "select_freeform"):
            self.setFocus()
            if tool != "select_polygon" or not self.selection_points:
                editor.clear_selection()
            if tool == "select_polygon":
                self.selection_points.append(point)
                self.selection_hover = point
                self.update()
                editor.statusBar().showMessage("Click polygon corners, then press Enter to finish")
                return
            self.dragging = True
            self.start = point
            if tool == "select_freeform":
                self.selection_points = [point]
            else:
                self.selection = (point[0], point[1], point[0] + 1, point[1] + 1)
            self.update()
            return
        if tool in ("line", "rectangle", "ellipse"):
            self.shape = EditableShape(tool, point[0], point[1], point[0], point[1],
                                       editor.color, editor.size.value(),
                                       editor.shape_fill.isChecked(), editor.document.active,
                                       editor.background_color, color_ref=editor.active_color_ref,
                                       fill_color_ref=editor.active_background_ref,
                                       gradient=deepcopy(editor.color_gradient),
                                       fill_gradient=deepcopy(editor.background_gradient))
            self.shape_drag = "create"
            self.dragging = True
            self.update_shape_drag(point)
            return
        if tool in ("arrow", "arc", "circle"):
            self.dragging = True
            self.start = point
            kind = "ellipse" if tool == "circle" else tool
            self.new_drag_object = PaintObject(kind, [point, point], editor.color,
                                               editor.size.value(), editor.shape_fill.isChecked(),
                                               fill_color=editor.background_color,
                                               color_ref=editor.active_color_ref,
                                               fill_color_ref=editor.active_background_ref,
                                               gradient=deepcopy(editor.color_gradient),
                                               fill_gradient=deepcopy(editor.background_gradient))
            self.update_new_drag(point)
            return
        self.dragging = True
        self.start = point
        self.points = [point]
        self.make_preview(point)

    def mouseMoveEvent(self, event) -> None:
        point = self.image_point(event)
        self.position_changed.emit(point[0], point[1])
        if (self.dragging or self.path_draft is not None) and self.editor.tool not in ("select_freeform", "select_polygon") and not (
                self.object_drag == "center" or self.shape_drag == "center"):
            point = self.snapped_point(point)
        if not self.dragging:
            if self.selection_points and self.editor.tool == "select_polygon":
                self.selection_hover = point
                self.update()
            if self.path_draft is not None:
                self.path_hover = (max(0, min(self.editor.document.width - 1, point[0])),
                                   max(0, min(self.editor.document.height - 1, point[1])))
                self.update_path_preview()
            self.update_handle_cursor(event.position())
            return
        point = (max(0, min(self.editor.document.width - 1, point[0])),
                 max(0, min(self.editor.document.height - 1, point[1])))
        if self.object_drag is not None:
            self.update_object_drag(point)
            return
        if self.new_drag_object is not None:
            self.update_new_drag(point)
            return
        if self.shape_drag is not None:
            self.update_shape_drag(point)
            return
        if self.editor.tool in ("select", "select_freeform"):
            if self.editor.tool == "select_freeform":
                if point != self.selection_points[-1]:
                    self.selection_points.append(point)
                self.update()
                return
            self.selection = (min(self.start[0], point[0]), min(self.start[1], point[1]),
                              max(self.start[0], point[0]) + 1, max(self.start[1], point[1]) + 1)
            self.update()
            return
        if self.editor.tool in ("brush", "pencil", "eraser") and point != self.points[-1]:
            self.points.append(point)
        self.make_preview(point)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.dragging:
            return
        point = self.image_point(event)
        if self.object_drag != "center" and self.shape_drag != "center":
            point = self.snapped_point(point)
        point = (max(0, min(self.editor.document.width - 1, point[0])),
                 max(0, min(self.editor.document.height - 1, point[1])))
        if self.object_drag is not None:
            self.update_object_drag(point)
            obj = self.editor.selected_canvas_object()
            if obj is not None and obj.kind in ("rectangle", "ellipse", "arc", "text", "image", "selection") and len(obj.points) >= 2:
                (x0, y0), (x1, y1) = obj.points[:2]
                obj.points[:2] = [(min(x0, x1), min(y0, y1)), (max(x0, x1), max(y0, y1))]
            self.object_drag = None
            self.object_before_drag = None
            self.dragging = False
            self.editor.changed()
            self.update_handle_cursor(event.position())
            return
        if self.new_drag_object is not None:
            self.update_new_drag(point)
            obj = self.new_drag_object
            self.new_drag_object = None
            self.preview = None
            if obj.kind == "text":
                self.dragging = False
                self.start_text(obj.points[0], obj.points[1])
                self.update()
                return
            self.erase_mask = None
            self.preview_fill_color = None
            self.dragging = False
            self.editor.begin_change()
            self.editor.add_object(obj)
            self.editor.selected_object_index = len(self.editor.document.layers[self.editor.document.active].objects) - 1
            self.editor.changed()
            self.editor.set_tool("select")
            return
        if self.shape_drag is not None:
            self.update_shape_drag(point)
            assert self.shape is not None
            self.shape.normalize()
            self.shape_drag = None
            self.shape_before_drag = None
            self.dragging = False
            self.update_handle_cursor(event.position())
            self.editor.statusBar().showMessage("Drag the handles to adjust; click elsewhere to finish. Esc cancels.")
            self.update()
            return
        if self.editor.tool in ("select", "select_freeform"):
            if self.editor.tool == "select_freeform":
                if point != self.selection_points[-1]:
                    self.selection_points.append(point)
                self.finish_polygon_selection()
            else:
                self.selection = (min(self.start[0], point[0]), min(self.start[1], point[1]),
                                  max(self.start[0], point[0]) + 1, max(self.start[1], point[1]) + 1)
                mask = Image.new("L", (self.editor.document.width, self.editor.document.height))
                box = self.selection
                ImageDraw.Draw(mask).rectangle((box[0], box[1], box[2]-1, box[3]-1), fill=255)
                self.selection_mask = mask
                self.selection_outline = []
                if self.start == point:
                    object_index = self.object_at(point)
                    if object_index is not None:
                        self.editor.clear_selection()
                        self.editor.select_object(object_index)
            self.dragging = False
            self.update()
            return
        if self.editor.tool in ("brush", "pencil", "eraser") and point != self.points[-1]:
            self.points.append(point)
        self.make_preview(point)
        self.editor.begin_change()
        tool = self.editor.tool
        color = self.editor.background_color if tool == "eraser" else self.editor.color
        self.editor.add_object(PaintObject(
            tool, [(x, y) for x, y in self.points], color,
            1 if tool == "pencil" else self.editor.size.value(),
            color_ref=self.editor.active_background_ref if tool == "eraser" else self.editor.active_color_ref,
            gradient=deepcopy(self.editor.background_gradient if tool == "eraser" else self.editor.color_gradient)))
        self.editor.selected_object_index = len(self.editor.document.layers[self.editor.document.active].objects) - 1
        self.dragging = False
        self.preview = None
        self.erase_mask = None
        self.points = []
        self.editor.changed()

    def make_preview(self, end: tuple[int, int]) -> None:
        doc = self.editor.document
        tool = self.editor.tool
        mask = Image.new("L", (doc.width, doc.height))
        size = 1 if tool == "pencil" else self.editor.size.value()
        draw_stroke(mask, self.points, size)
        if tool == "eraser":
            self.erase_mask = mask
            if self.editor.background_gradient is not None:
                preview = gradient_canvas((doc.width, doc.height), mask, self.editor.background_gradient)
                preview.putalpha(ImageChops.multiply(preview.getchannel("A"), mask))
                self.preview = preview
                self.preview_fill_color = (0, 0, 0, 0)
            else:
                self.preview = None
                self.preview_fill_color = None
        else:
            if self.editor.color_gradient is not None:
                preview = gradient_canvas((doc.width, doc.height), mask, self.editor.color_gradient)
                preview.putalpha(ImageChops.multiply(preview.getchannel("A"), mask))
                self.preview = preview
            else:
                self.preview = colorized_mask(mask, self.editor.color)
            self.erase_mask = None
        self.update()
        self.editor.update_preview()


class NewCanvasDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New canvas")
        layout = QFormLayout(self)
        self.width_field = QSpinBox()
        self.width_field.setRange(1, 10000)
        self.width_field.setValue(800)
        self.height_field = QSpinBox()
        self.height_field.setRange(1, 10000)
        self.height_field.setValue(600)
        self.transparent = QCheckBox("Transparent background")
        layout.addRow("Width (pixels)", self.width_field)
        layout.addRow("Height (pixels)", self.height_field)
        layout.addRow(self.transparent)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)


class ExportImageDialog(QFileDialog):
    def __init__(self, filters: str, default_filter: str, parent=None):
        super().__init__(parent, "Export image", "Untitled", filters)
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        self.setFileMode(QFileDialog.FileMode.AnyFile)
        self.selectNameFilter(default_filter)
        self.include_grid = QCheckBox("Include grid in exported image")
        layout = self.layout()
        layout.addWidget(self.include_grid, layout.rowCount(), 0, 1, layout.columnCount())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.document = Document()
        self.file_path: Path | None = None
        self.dirty = False
        self.undo_stack: list[EditorSnapshot] = []
        self.redo_stack: list[EditorSnapshot] = []
        self.pending: EditorSnapshot | None = None
        self.color = (0, 0, 0, 255)
        self.background_color = (0, 0, 0, 0)
        self.grid_visible = False
        self.grid_snap = False
        self.grid_spacing = 20
        self.custom_colors: list[tuple[int, int, int, int]] = []
        self.custom_color_ids: list[str] = []
        self.custom_swatch_buttons: list[SwatchButton] = []
        self.active_color_ref: str | None = None
        self.active_background_ref: str | None = None
        self.color_gradient: dict | None = None
        self.background_gradient: dict | None = None
        self.custom_library = CustomLibrary()
        self.pending_custom_template_id: str | None = None
        self.custom_editor: MainWindow | None = None
        self.selected_child_path: tuple[int, ...] = ()
        self.tool = "brush"
        self.copy_buffer: Image.Image | None = None
        self.copy_origin = (0, 0)
        self.selected_object_index: int | None = None
        self.theme = "dark"
        self.preview_dialog: PreviewDialog | None = None
        self.setWindowTitle("Painter")
        self.resize(1190, 790)
        apply_theme(QApplication.instance(), self.theme)
        set_icon_color(COLORS[self.theme]["icon"])
        self.canvas = Canvas(self)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        workspace = QWidget()
        workspace.setObjectName("workspace")
        outer = QHBoxLayout(workspace)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.palette = self.make_palette()
        palette_scroll = QScrollArea()
        palette_scroll.setFixedWidth(230)
        palette_scroll.setWidgetResizable(True)
        palette_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        palette_scroll.setWidget(self.palette)
        outer.addWidget(palette_scroll)
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.make_layers())
        main_layout.addWidget(scroll, 1)
        outer.addWidget(main, 1)
        self.object_panel = ObjectPanel()
        self.object_panel.selected.connect(self.select_object)
        self.object_panel.property_edited.connect(self.edit_object_property)
        self.object_panel.point_edited.connect(self.edit_object_point)
        self.object_panel.order_changed.connect(self.reorder_objects)
        self.object_panel.delete_requested.connect(self.delete_selected_object)
        self.object_panel.move_requested.connect(self.move_selected_object)
        self.object_panel.color_requested.connect(self.choose_object_color)
        self.object_panel.fill_color_requested.connect(self.choose_object_fill_color)
        self.object_panel.font_requested.connect(self.choose_object_font)
        self.object_panel.transform_requested.connect(self.transform_selected_object)
        outer.addWidget(self.object_panel)
        self.setCentralWidget(workspace)
        self.make_actions()
        self.make_status_controls()
        self.statusBar().showMessage("Ready")
        self.canvas.position_changed.connect(self.show_position)
        self.refresh()
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if hasattr(self, "canvas") and watched is self.canvas.text_editor:
            if event.type() == QEvent.Type.FocusOut:
                self.canvas.commit_text()
            elif event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self.canvas.commit_text()
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    self.canvas.cancel_text()
                    return True
        if hasattr(self, "canvas") and self.canvas.shape is not None:
            if event.type() == QEvent.Type.MouseButtonPress and watched is not self.canvas:
                canvas_point = self.canvas.mapFromGlobal(event.globalPosition().toPoint())
                if not self.canvas.rect().contains(canvas_point):
                    self.canvas.finalize_shape()
            elif event.type() == QEvent.Type.WindowDeactivate and watched is self:
                self.canvas.finalize_shape()
        return super().eventFilter(watched, event)

    def action(self, label: str, slot, shortcut: str | None = None) -> QAction:
        action = QAction(label, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        return action

    def make_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        for label, slot, shortcut in (
            ("&New…", self.new_document, "Ctrl+N"), ("&Open…", self.open_document, "Ctrl+O"),
            ("&Save", self.save, "Ctrl+S"), ("Save &As…", self.save_as, "Ctrl+Shift+S"),
            ("Export &image…", self.export_image, "Ctrl+E"), ("&Quit", self.close, "Ctrl+Q"),
        ):
            file_menu.addAction(self.action(label, slot, shortcut))
        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.action("&Undo", self.undo, "Ctrl+Z"))
        edit_menu.addAction(self.action("&Redo", self.redo, "Ctrl+Shift+Z"))
        edit_menu.addSeparator()
        edit_menu.addAction(self.action("&Copy selection", self.copy_selection, "Ctrl+C"))
        edit_menu.addAction(self.action("Cu&t selection", self.cut_selection, "Ctrl+X"))
        edit_menu.addAction(self.action("&Paste into active layer", self.paste, "Ctrl+V"))
        edit_menu.addAction(self.action("Cancel shape / clear selection", self.cancel_active, "Escape"))
        edit_menu.addAction(self.action("Crop to selection", self.crop_to_selection))
        edit_menu.addSeparator()
        edit_menu.addAction(self.action("Resize canvas…", self.resize_canvas))
        layer_menu = self.menuBar().addMenu("&Layer")
        layer_menu.addAction(self.action("&New layer", self.add_layer, "Ctrl+Shift+N"))
        layer_menu.addAction(self.action("&Delete layer", self.delete_layer))
        layer_menu.addAction(self.action("Move up", lambda: self.move_layer(1)))
        layer_menu.addAction(self.action("Move down", lambda: self.move_layer(-1)))
        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.action("Zoom in", lambda: self.set_zoom(self.canvas.zoom * 1.25), "Ctrl++"))
        view_menu.addAction(self.action("Zoom out", lambda: self.set_zoom(self.canvas.zoom / 1.25), "Ctrl+-"))
        view_menu.addAction(self.action("Actual size", lambda: self.set_zoom(1), "Ctrl+0"))
        view_menu.addSeparator()
        view_menu.addAction(self.action("Create custom object…", self.create_custom_object))
        view_menu.addAction(self.action("Browse custom objects…", self.open_custom_gallery))
        view_menu.addSeparator()
        self.show_grid_action = self.action("Show grid", self.grid_checkbox.setChecked)
        self.show_grid_action.setCheckable(True)
        self.show_grid_action.toggled.connect(self.grid_checkbox.setChecked)
        self.grid_checkbox.toggled.connect(self.show_grid_action.setChecked)
        view_menu.addAction(self.show_grid_action)
        self.snap_grid_action = self.action("Snap to grid", self.snap_checkbox.setChecked)
        self.snap_grid_action.setCheckable(True)
        self.snap_grid_action.toggled.connect(self.snap_checkbox.setChecked)
        self.snap_checkbox.toggled.connect(self.snap_grid_action.setChecked)
        view_menu.addAction(self.snap_grid_action)
        theme_menu = view_menu.addMenu("Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        self.theme_actions = {}
        for name in ("dark", "light"):
            theme_action = self.action(name.capitalize(), lambda checked=False, name=name: self.set_theme(name))
            theme_action.setCheckable(True)
            theme_action.setChecked(name == self.theme)
            theme_group.addAction(theme_action)
            theme_menu.addAction(theme_action)
            self.theme_actions[name] = theme_action

    def set_grid_visible(self, visible: bool) -> None:
        self.grid_visible = visible
        self.canvas.update()

    def set_grid_snap(self, enabled: bool) -> None:
        self.grid_snap = enabled

    def set_grid_spacing(self, spacing: int) -> None:
        if spacing == self.grid_spacing:
            return
        factor = spacing / self.grid_spacing
        self.canvas.commit_text()
        self.begin_change()
        self.document.scale_objects(factor)
        self.document.grid_spacing = spacing
        self.grid_spacing = spacing
        if self.canvas.selection is not None:
            self.canvas.selection = None
            self.canvas.selection_mask = None
        self.canvas.selection_outline = []
        if self.canvas.path_draft is not None:
            draft = self.canvas.path_draft
            draft.points = [(x * factor, y * factor) for x, y in draft.points]
            draft.size = max(1, round(draft.size * factor))
            draft.tangents = [tuple(value * factor for value in tangent) for tangent in draft.tangents]
            if self.canvas.path_hover is not None:
                self.canvas.path_hover = tuple(round(value * factor) for value in self.canvas.path_hover)
            self.canvas.update_path_preview()
        self.changed()

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.theme_actions[theme].setChecked(True)
        apply_theme(QApplication.instance(), theme)
        set_icon_color(COLORS[theme]["icon"])
        for name, button in self.tool_buttons.items():
            button.setIcon(line_icon(name))
        self.custom_add_button.setIcon(line_icon("plus", size=17))
        self.layer_add_button.setIcon(line_icon("plus", size=17))
        self.preview_button.setIcon(line_icon("eye", size=17))
        self.refresh()

    def make_palette(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("palette")
        panel.setMinimumWidth(210)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(7)
        title = QLabel("TOOLS")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.tool_buttons: dict[str, QToolButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        tools = (
            ("Select", "select", "S"), ("Brush", "brush", "B"), ("Pencil", "pencil", "P"), ("Eraser", "eraser", "E"),
            ("Fill", "fill", "F"), ("Picker", "picker", "I"), ("Line", "line", "L"),
            ("Rectangle", "rectangle", "R"), ("Ellipse", "ellipse", "O"), ("Text", "text", "T"),
        )
        for index, (label, name, shortcut) in enumerate(tools):
            button = QToolButton()
            button.setObjectName("toolButton")
            button.setIcon(line_icon(name))
            button.setIconSize(QSize(23, 23))
            button.setFixedSize(42, 34)
            button.setCheckable(True)
            button.setChecked(name == self.tool)
            button.setToolTip(f"{label} ({shortcut})")
            button.clicked.connect(lambda checked=False, name=name: self.set_tool(name))
            if name in TOOL_MODES:
                menu = QMenu(button)
                for mode_label, mode_name in TOOL_MODES[name]:
                    menu.addAction(mode_label, lambda checked=False, mode_name=mode_name: self.set_tool(mode_name))
                button.setMenu(menu)
                button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            group.addButton(button)
            grid.addWidget(button, index // 4, index % 4)
            self.tool_buttons[name] = button
            shortcut_action = self.action(label, lambda checked=False, name=name: self.set_tool(name), shortcut)
            self.addAction(shortcut_action)
        layout.addLayout(grid)
        heading = QLabel("COLORS")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        color_row = QGridLayout()
        color_row.setHorizontalSpacing(6)
        color_row.setVerticalSpacing(3)
        self.foreground_label = QLabel("FOREGROUND")
        self.foreground_label.setObjectName("sectionTitle")
        color_row.addWidget(self.foreground_label, 0, 0)
        self.background_label = QLabel("BACKGROUND")
        self.background_label.setObjectName("sectionTitle")
        color_row.addWidget(self.background_label, 0, 1)
        self.color_button = QToolButton()
        self.color_button.setObjectName("currentColor")
        self.color_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.color_button.setIconSize(QSize(30, 30))
        self.color_button.setFixedHeight(42)
        self.color_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.color_button.clicked.connect(self.choose_color)
        color_row.addWidget(self.color_button, 1, 0)
        self.background_color_button = QToolButton()
        self.background_color_button.setObjectName("currentColor")
        self.background_color_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.background_color_button.setIconSize(QSize(30, 30))
        self.background_color_button.setFixedHeight(42)
        self.background_color_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.background_color_button.clicked.connect(self.choose_background_color)
        color_row.addWidget(self.background_color_button, 1, 1)
        layout.addLayout(color_row)
        self.update_color_button()
        self.update_background_color_button()
        presets_label = QLabel("Presets")
        layout.addWidget(presets_label)
        preset_grid = QGridLayout()
        preset_grid.setSpacing(4)
        self.swatch_buttons: list[tuple[QToolButton, tuple[int, int, int, int]]] = []
        for index, (name, rgba) in enumerate(PRESET_COLORS):
            button = self.make_swatch(name, rgba)
            preset_grid.addWidget(button, index // 5, index % 5)
            self.swatch_buttons.append((button, rgba))
        layout.addLayout(preset_grid)
        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Custom · this session"))
        custom_row.addStretch()
        add_custom = QToolButton()
        add_custom.setObjectName("smallButton")
        add_custom.setIcon(line_icon("plus", size=17))
        add_custom.setIconSize(QSize(17, 17))
        add_custom.setToolTip("Save current color to custom colors for this session")
        add_custom.clicked.connect(self.add_custom_color)
        self.custom_add_button = add_custom
        custom_row.addWidget(add_custom)
        layout.addLayout(custom_row)
        self.custom_grid = QGridLayout()
        self.custom_grid.setSpacing(4)
        layout.addLayout(self.custom_grid)
        layout.addSpacing(5)
        options_label = QLabel("OPTIONS")
        options_label.setObjectName("sectionTitle")
        layout.addWidget(options_label)
        options = QFormLayout()
        options.setSpacing(6)
        self.size = QSpinBox()
        self.size.setRange(1, 200)
        self.size.setValue(5)
        options.addRow("Size", self.size)
        self.shape_fill = QCheckBox("Filled shapes")
        options.addRow(self.shape_fill)
        self.tolerance = QSpinBox()
        self.tolerance.setRange(0, 255)
        self.tolerance.setValue(0)
        self.tolerance.setToolTip("Maximum difference per RGBA channel for flood fill")
        options.addRow("Fill tolerance", self.tolerance)
        layout.addLayout(options)
        layout.addSpacing(4)
        grid_label = QLabel("GRID")
        grid_label.setObjectName("sectionTitle")
        layout.addWidget(grid_label)
        self.grid_checkbox = QCheckBox("Show grid")
        self.grid_checkbox.toggled.connect(self.set_grid_visible)
        layout.addWidget(self.grid_checkbox)
        self.snap_checkbox = QCheckBox("Snap to grid")
        self.snap_checkbox.toggled.connect(self.set_grid_snap)
        layout.addWidget(self.snap_checkbox)
        grid_options = QFormLayout()
        self.grid_spacing_spin = QSpinBox()
        self.grid_spacing_spin.setRange(2, 512)
        self.grid_spacing_spin.setValue(self.grid_spacing)
        self.grid_spacing_spin.setSuffix(" px")
        self.grid_spacing_spin.setKeyboardTracking(False)
        self.grid_spacing_spin.setToolTip("Change grid spacing and scale editable objects; canvas size stays fixed")
        self.grid_spacing_spin.valueChanged.connect(self.set_grid_spacing)
        grid_options.addRow("Spacing", self.grid_spacing_spin)
        layout.addLayout(grid_options)
        layout.addSpacing(5)
        heading = CustomObjectHeading("CUSTOM OBJECTS  ↗")
        heading.setObjectName("sectionTitle")
        heading.setToolTip("Double-click to open the full custom object gallery")
        heading.doubleClicked.connect(self.open_custom_gallery)
        layout.addWidget(heading)
        custom_scroll = QScrollArea()
        custom_scroll.setWidgetResizable(True)
        custom_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        custom_scroll.setMinimumHeight(128)
        custom_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        custom_content = QWidget()
        self.custom_objects_layout = QVBoxLayout(custom_content)
        self.custom_objects_layout.setContentsMargins(2, 2, 2, 2)
        self.custom_objects_layout.setSpacing(4)
        custom_scroll.setWidget(custom_content)
        self.custom_objects_scroll = custom_scroll
        layout.addWidget(custom_scroll, 1)
        self.refresh_custom_objects()
        self.update_swatch_selection()
        return panel

    def make_swatch(self, name: str, rgba: tuple[int, int, int, int],
                    custom_index: int | None = None) -> SwatchButton:
        button = SwatchButton()
        button.setObjectName("swatchButton")
        button.setProperty("selected", False)
        button.setIcon(swatch_icon(rgba, 26))
        button.setIconSize(QSize(24, 24))
        button.setFixedSize(30, 30)
        button.setToolTip(f"{name} · RGBA {', '.join(map(str, rgba))}")
        if custom_index is None:
            button.clicked.connect(lambda checked=False, rgba=rgba: self.set_color(rgba))
        else:
            button.clicked.connect(lambda checked=False, index=custom_index: self.select_custom_color(index))
            button.doubleClicked.connect(lambda index=custom_index: self.edit_custom_color(index))
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda position, index=custom_index: self.custom_color_menu(index, button.mapToGlobal(position)))
        return button

    def add_custom_color(self, rgba: tuple[int, int, int, int] | None = None) -> None:
        rgba = rgba or self.color
        if rgba in self.custom_colors:
            return
        self.custom_colors.append(rgba)
        self.custom_color_ids.append(uuid4().hex)
        index = len(self.custom_colors) - 1
        button = self.make_swatch("Custom · double-click to edit", rgba, index)
        self.custom_grid.addWidget(button, index // 5, index % 5)
        self.swatch_buttons.append((button, rgba))
        self.custom_swatch_buttons.append(button)
        self.update_swatch_selection()

    def select_custom_color(self, index: int) -> None:
        self.set_color(self.custom_colors[index], self.custom_color_ids[index])

    def custom_color_menu(self, index: int, position) -> None:
        menu = QMenu(self)
        menu.addAction("Use as foreground", lambda: self.select_custom_color(index))
        menu.addAction("Use as background / fill", lambda: self.set_background_color(
            self.custom_colors[index], self.custom_color_ids[index]))
        menu.addAction("Edit color…", lambda: self.edit_custom_color(index))
        menu.exec(position)

    def edit_custom_color(self, index: int) -> None:
        old = self.custom_colors[index]
        dialog = ColorDialog(old, self, allow_gradient=False)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.rgba() == old:
            return
        new = dialog.rgba()
        swatch_id = self.custom_color_ids[index]
        self.begin_change()
        self.custom_colors[index] = new
        button = self.custom_swatch_buttons[index]
        button.setIcon(swatch_icon(new, 26))
        button.setToolTip(f"Custom · RGBA {', '.join(map(str, new))} · double-click to edit")
        self.swatch_buttons = [(item, new if item is button else rgba)
                               for item, rgba in self.swatch_buttons]
        if self.active_color_ref == swatch_id:
            self.set_color(new, swatch_id)
        if self.active_background_ref == swatch_id:
            self.set_background_color(new, swatch_id)
        def recolor(obj: PaintObject) -> None:
            if obj.color_ref == swatch_id:
                obj.color = new
            if obj.fill_color_ref == swatch_id:
                obj.fill_color = new
            for spec in (obj.gradient, obj.fill_gradient):
                if spec is not None:
                    for endpoint in ("start", "stop"):
                        if spec.get(f"{endpoint}_ref") == swatch_id:
                            spec[endpoint] = list(new)
            for child in obj.children:
                recolor(child)
        for layer_index, layer in enumerate(self.document.layers):
            for obj in layer.objects or []:
                recolor(obj)
            self.document.rebuild_layer(layer_index)
        self.changed()

    def update_swatch_selection(self) -> None:
        for button, rgba in self.swatch_buttons:
            button.setProperty("selected", rgba == self.color)
            button.style().unpolish(button)
            button.style().polish(button)

    def refresh_custom_objects(self) -> None:
        layout = self.custom_objects_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for template in self.custom_library.ranked():
            button = TemplateButton(template, compact=True)
            button.clicked.connect(lambda checked=False, template_id=template.template_id:
                                   self.arm_custom_template(template_id))
            layout.addWidget(button)
        layout.addStretch()

    def open_custom_gallery(self) -> None:
        dialog = CustomObjectGallery(self.custom_library, self)
        dialog.library_changed.connect(self.refresh_after_custom_library_change)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_id:
            return
        if dialog.action == "edit":
            self.edit_custom_object(dialog.selected_id)
        else:
            self.arm_custom_template(dialog.selected_id)

    def refresh_after_custom_library_change(self) -> None:
        self.refresh_custom_objects()
        if (self.pending_custom_template_id is not None and
                self.pending_custom_template_id not in self.custom_library.templates):
            self.pending_custom_template_id = None
            if self.tool == "custom":
                self.set_tool("select")

    def arm_custom_template(self, template_id: str) -> None:
        self.pending_custom_template_id = template_id
        self.set_tool("custom")
        self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        self.statusBar().showMessage("Click the canvas to place the custom object")

    def place_custom_template(self, point: tuple[int, int]) -> None:
        template_id = self.pending_custom_template_id
        if template_id is None:
            return
        template = self.custom_library.templates[template_id]
        self.begin_change()
        self.document.add_object(template.instantiate(*point))
        self.selected_object_index = len(self.document.layers[self.document.active].objects) - 1
        self.selected_child_path = ()
        self.custom_library.record_use(template_id)
        self.refresh_custom_objects()
        self.changed()
        self.set_tool("select")

    def create_custom_object(self) -> None:
        self.open_custom_editor()

    def edit_custom_object(self, template_id: str) -> None:
        self.open_custom_editor(template_id)

    def open_custom_editor(self, template_id: str | None = None) -> None:
        editor = MainWindow()
        editor.custom_library = self.custom_library
        editor.refresh_custom_objects()
        if template_id is None:
            editor.replace_document(Document(600, 400, transparent=True))
            editor.setWindowTitle("Create custom object — Painter")
            save_label = "Save to custom objects…"
            editor.statusBar().showMessage(
                "Draw the object, then choose Custom Object → Save to custom objects")
        else:
            template = self.custom_library.templates[template_id]
            document = Document(template.width, template.height, transparent=True)
            for child in template.children:
                document.add_object(child.copy())
            editor.replace_document(document)
            editor.setWindowTitle(f"Edit {template.name} — Painter")
            save_label = "Save changes…"
            editor.statusBar().showMessage(
                "Edit the object, then choose Custom Object → Save changes")
        editor.resize(1180, 780)
        menu = editor.menuBar().addMenu("&Custom Object")
        menu.addAction(editor.action(
            save_label, lambda: self.save_custom_editor(editor, template_id), "Ctrl+Shift+K"))
        self.custom_editor = editor
        editor.show()

    def save_custom_editor(self, editor: MainWindow, template_id: str | None = None) -> None:
        if template_id is None:
            name, accepted = QInputDialog.getText(editor, "Save custom object", "Object name:")
        else:
            current_name = self.custom_library.templates[template_id].name
            name, accepted = QInputDialog.getText(
                editor, "Save changes", "Object name:", text=current_name)
        if not accepted or not name.strip():
            return
        try:
            template = template_from_document(editor.document, name)
            if template_id is None:
                self.custom_library.add(template)
            else:
                self.custom_library.replace(template_id, template)
                invalidate_template_icon(template_id)
        except (ValueError, OSError) as error:
            QMessageBox.warning(editor, "Cannot save custom object", str(error))
            return
        self.refresh_custom_objects()
        self.arm_custom_template(template.template_id)
        editor.dirty = False
        editor.close()

    def make_layers(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("layerBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 7, 14, 7)
        layout.setSpacing(9)
        self.layer_strip = LayerStrip()
        self.layer_strip.currentRowChanged.connect(self.select_layer)
        self.layer_strip.itemDoubleClicked.connect(lambda item: self.rename_layer(self.layer_strip.row(item)))
        self.layer_strip.order_changed.connect(self.reorder_layers)
        self.layer_strip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.layer_strip.customContextMenuRequested.connect(self.layer_context_menu)
        layout.addWidget(self.layer_strip)
        add_button = QToolButton()
        add_button.setObjectName("smallButton")
        add_button.setIcon(line_icon("plus", size=17))
        add_button.setIconSize(QSize(17, 17))
        add_button.setToolTip("Add a new top layer (Ctrl+Shift+N)")
        add_button.clicked.connect(self.add_layer)
        self.layer_add_button = add_button
        layout.addWidget(add_button)
        self.visibility_button = QToolButton()
        self.visibility_button.setObjectName("smallButton")
        self.visibility_button.setIconSize(QSize(17, 17))
        self.visibility_button.setToolTip("Show or hide selected layer")
        self.visibility_button.clicked.connect(self.toggle_layer)
        layout.addWidget(self.visibility_button)
        layout.addWidget(QLabel("Opacity"))
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 100)
        self.opacity.setSuffix("%")
        self.opacity.setValue(100)
        self.opacity.setFixedWidth(70)
        self.opacity.valueChanged.connect(self.set_opacity)
        layout.addWidget(self.opacity)
        layout.addStretch()
        self.preview_button = QPushButton("Preview")
        self.preview_button.setIcon(line_icon("eye", size=17))
        self.preview_button.setToolTip("Open a view-only preview of the final image")
        self.preview_button.clicked.connect(self.open_preview)
        layout.addWidget(self.preview_button)
        return bar

    def open_preview(self) -> None:
        self.canvas.finalize_shape()
        if self.preview_dialog is not None and self.preview_dialog.isVisible():
            self.update_preview()
            self.preview_dialog.raise_()
            self.preview_dialog.activateWindow()
            return
        self.preview_dialog = PreviewDialog(self.document.composite(), self)
        self.preview_dialog.finished.connect(self.preview_closed)
        self.preview_dialog.show()

    def preview_closed(self) -> None:
        self.preview_dialog = None

    def update_preview(self) -> None:
        if self.preview_dialog is not None and self.preview_dialog.isVisible():
            self.preview_dialog.set_image(self.document.composite(
                self.canvas.preview, self.canvas.erase_mask,
                erase_color=self.canvas.preview_fill_color or self.background_color))

    def make_status_controls(self) -> None:
        size_button = QToolButton()
        size_button.setObjectName("smallButton")
        size_button.setToolTip("Change canvas width and height")
        size_button.clicked.connect(self.resize_canvas)
        self.canvas_size_button = size_button
        self.statusBar().addPermanentWidget(size_button)
        zoom_out = QToolButton()
        zoom_out.setObjectName("smallButton")
        zoom_out.setText("−")
        zoom_out.setToolTip("Zoom out")
        zoom_out.clicked.connect(lambda: self.set_zoom(self.canvas.zoom / 1.25))
        self.zoom_out_button = zoom_out
        self.statusBar().addPermanentWidget(zoom_out)
        self.zoom_percent = QDoubleSpinBox()
        self.zoom_percent.setRange(12.5, 1600)
        self.zoom_percent.setDecimals(1)
        self.zoom_percent.setSingleStep(25)
        self.zoom_percent.setSuffix("%")
        self.zoom_percent.setFixedWidth(86)
        self.zoom_percent.setToolTip("Canvas zoom percentage")
        self.zoom_percent.setValue(100)
        self.zoom_percent.valueChanged.connect(lambda value: self.set_zoom(value / 100))
        self.statusBar().addPermanentWidget(self.zoom_percent)
        zoom_in = QToolButton()
        zoom_in.setObjectName("smallButton")
        zoom_in.setText("+")
        zoom_in.setToolTip("Zoom in")
        zoom_in.clicked.connect(lambda: self.set_zoom(self.canvas.zoom * 1.25))
        self.zoom_in_button = zoom_in
        self.statusBar().addPermanentWidget(zoom_in)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "layer_strip"):
            self.update_layer_strip_width()

    def update_layer_strip_width(self) -> None:
        available = max(120, self.width() - 520)
        self.layer_strip.setFixedWidth(min(CARD_WIDTH * self.layer_strip.count() + 8, available))

    def set_tool(self, tool: str) -> None:
        self.canvas.commit_text()
        if self.canvas.shape is not None and tool != self.canvas.shape.tool:
            self.canvas.finalize_shape()
        if self.canvas.path_draft is not None and tool != self.tool:
            required = 3 if self.canvas.path_draft.kind == "polygon" or self.canvas.path_draft.kind.endswith("_3point") else 2
            if len(self.canvas.path_draft.points) >= required:
                self.canvas.finish_path()
            else:
                self.canvas.cancel_path()
        if self.tool in ("select", "select_polygon", "select_freeform") and tool != self.tool:
            self.clear_selection()
        self.tool = tool
        if tool in self.tool_buttons or TOOL_BASE.get(tool) in self.tool_buttons:
            self.tool_buttons[TOOL_BASE.get(tool, tool)].setChecked(True)
        self.statusBar().showMessage(f"{tool.replace('_', ' ').capitalize()} selected")

    def clear_selection(self) -> None:
        self.canvas.selection = None
        self.canvas.selection_mask = None
        self.canvas.selection_points = []
        self.canvas.selection_hover = None
        self.canvas.selection_outline = []
        self.canvas.update()

    def selection_mask(self) -> Image.Image | None:
        box = self.canvas.selection
        if box is None:
            return None
        if self.canvas.selection_mask is not None:
            return self.canvas.selection_mask.copy()
        mask = Image.new("L", (self.document.width, self.document.height))
        ImageDraw.Draw(mask).rectangle((box[0], box[1], box[2]-1, box[3]-1), fill=255)
        return mask

    def selection_pixels(self) -> tuple[Image.Image, tuple[int, int, int, int]] | None:
        mask = self.selection_mask()
        if mask is None or (box := mask.getbbox()) is None:
            return None
        pixels = self.document.layers[self.document.active].image.crop(box)
        pixels.putalpha(ImageChops.multiply(pixels.getchannel("A"), mask.crop(box)))
        return pixels, box

    def lift_selection(self) -> None:
        mask = self.selection_mask()
        if mask is None or (box := mask.getbbox()) is None:
            return
        self.begin_change()
        self.add_object(PaintObject("selection", points=[box[:2], box[2:]], mask=mask))
        self.selected_object_index = len(self.document.layers[self.document.active].objects) - 1
        self.clear_selection()
        self.changed()

    def cancel_active(self) -> None:
        if self.canvas.text_editor is not None:
            self.canvas.cancel_text()
        elif self.canvas.path_draft is not None:
            self.canvas.cancel_path()
        elif self.canvas.shape is not None:
            self.canvas.cancel_shape()
        else:
            self.clear_selection()

    def copy_selection(self) -> None:
        result = self.selection_pixels()
        if result is None:
            obj = self.selected_object()
            if obj is None or obj.kind not in ("image", "selection"):
                return
            box = tuple(round(value) for point in obj.points[:2] for value in point)
            left, right = sorted((box[0], box[2]))
            top, bottom = sorted((box[1], box[3]))
            self.copy_buffer = self.document.layers[self.document.active].image.crop((left, top, right, bottom))
            self.copy_origin = (left, top)
        else:
            self.copy_buffer, box = result
            self.copy_origin = box[:2]
        QApplication.clipboard().setImage(pil_to_qimage(self.copy_buffer))

    def cut_selection(self) -> None:
        mask = self.selection_mask()
        if mask is None:
            obj = self.selected_object()
            if obj is not None and obj.kind in ("image", "selection"):
                self.copy_selection()
                if obj.kind == "selection":
                    self.begin_change()
                    obj.kind = "cut"
                    obj.points = []
                    obj.angle = 0
                    self.document.rebuild_layer()
                    self.changed()
                else:
                    self.delete_selected_object()
            return
        self.copy_selection()
        self.begin_change()
        self.add_object(PaintObject("cut", mask=mask))
        self.selected_object_index = len(self.document.layers[self.document.active].objects) - 1
        self.clear_selection()
        self.changed()

    def paste(self) -> None:
        qimage = QApplication.clipboard().image()
        if qimage.isNull():
            if self.copy_buffer is None:
                return
            image = self.copy_buffer.copy()
        else:
            qimage = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
            image = Image.frombytes("RGBA", (qimage.width(), qimage.height()), bytes(qimage.bits()))
        origin = self.copy_origin if self.copy_buffer is not None else (0, 0)
        self.begin_change()
        self.add_object(PaintObject("image", points=[origin,
             (origin[0] + image.width, origin[1] + image.height)], bitmap=image))
        self.clear_selection()
        self.selected_object_index = len(self.document.layers[self.document.active].objects) - 1
        self.changed()
        self.set_tool("select")

    def crop_to_selection(self) -> None:
        box = self.canvas.selection
        if box is None:
            return
        self.begin_change()
        self.document.crop(box)
        self.clear_selection()
        self.changed()

    def set_color(self, rgba: tuple[int, int, int, int], custom_id: str | None = None) -> None:
        self.color = rgba
        self.active_color_ref = custom_id
        self.color_gradient = None
        self.update_color_button()
        self.update_swatch_selection()

    def set_background_color(self, rgba: tuple[int, int, int, int], custom_id: str | None = None) -> None:
        self.background_color = rgba
        self.active_background_ref = custom_id
        self.background_gradient = None
        self.update_background_color_button()
        if self.canvas.erase_mask is not None:
            self.canvas.update()
            self.update_preview()

    def update_color_button(self) -> None:
        r, g, b, a = self.color
        self.color_button.setIcon(swatch_icon(self.color, 30))
        self.color_button.setText(f"#{r:02X}{g:02X}{b:02X} · α {a}")
        self.color_button.setToolTip(f"Foreground #{r:02X}{g:02X}{b:02X}, alpha {a} · click to choose")
        self.foreground_label.setText(f"FG · α {a}")

    def update_background_color_button(self) -> None:
        r, g, b, a = self.background_color
        self.background_color_button.setIcon(swatch_icon(self.background_color, 30))
        self.background_color_button.setText(f"#{r:02X}{g:02X}{b:02X} · α {a}")
        self.background_color_button.setToolTip(f"Fill / eraser #{r:02X}{g:02X}{b:02X}, alpha {a} · click to choose")
        self.background_label.setText(f"BG · α {a}")

    def choose_color(self) -> None:
        dialog = ColorDialog(self.color, self, gradient=self.color_gradient)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            previous_color, previous_ref = self.color, self.active_color_ref
            self.set_color(dialog.rgba(), previous_ref if dialog.rgba() == previous_color else None)
            self.color_gradient = self.link_gradient_refs(dialog.gradient_spec())
            if dialog.save_custom.isChecked():
                self.add_custom_color()

    def choose_background_color(self) -> None:
        dialog = ColorDialog(self.background_color, self, gradient=self.background_gradient)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            previous_color, previous_ref = self.background_color, self.active_background_ref
            self.set_background_color(dialog.rgba(), previous_ref if dialog.rgba() == previous_color else None)
            self.background_gradient = self.link_gradient_refs(dialog.gradient_spec())
            if dialog.save_custom.isChecked():
                self.add_custom_color(dialog.rgba())

    def link_gradient_refs(self, spec: dict | None) -> dict | None:
        if spec is None:
            return None
        result = deepcopy(spec)
        for endpoint in ("start", "stop"):
            color = tuple(result.get(endpoint, ()))
            result.pop(f"{endpoint}_ref", None)
            for index, custom_color in enumerate(self.custom_colors):
                if color == custom_color:
                    result[f"{endpoint}_ref"] = self.custom_color_ids[index]
                    break
        return result

    def add_object(self, obj: PaintObject, layer_index: int | None = None) -> None:
        if obj.color_ref is None and self.active_color_ref and obj.color == self.color:
            obj.color_ref = self.active_color_ref
        if obj.fill_color_ref is None and self.active_background_ref and obj.fill_color == self.background_color:
            obj.fill_color_ref = self.active_background_ref
        if obj.gradient is None and obj.color == self.color:
            obj.gradient = deepcopy(self.color_gradient)
        if obj.fill_gradient is None and obj.fill_color == self.background_color:
            obj.fill_gradient = deepcopy(self.background_gradient)
        self.document.add_object(obj, layer_index)

    def snapshot(self) -> EditorSnapshot:
        return EditorSnapshot(self.document.copy(), dict(zip(self.custom_color_ids, self.custom_colors)))

    def restore_snapshot(self, snapshot: EditorSnapshot) -> None:
        self.document = snapshot.document
        for index, swatch_id in enumerate(self.custom_color_ids):
            if swatch_id not in snapshot.custom_colors:
                continue
            color = snapshot.custom_colors[swatch_id]
            self.custom_colors[index] = color
            button = self.custom_swatch_buttons[index]
            button.setIcon(swatch_icon(color, 26))
            button.setToolTip(f"Custom · RGBA {', '.join(map(str, color))} · double-click to edit")
            self.swatch_buttons = [(item, color if item is button else rgba)
                                   for item, rgba in self.swatch_buttons]
            if self.active_color_ref == swatch_id:
                self.color = color
                self.update_color_button()
            if self.active_background_ref == swatch_id:
                self.background_color = color
                self.update_background_color_button()
        self.update_swatch_selection()

    def begin_change(self) -> None:
        self.canvas.finalize_shape()
        self.pending = self.snapshot()

    def discard_change(self) -> None:
        self.pending = None

    def changed(self) -> None:
        if self.pending is not None:
            self.undo_stack.append(self.pending)
            self.undo_stack = self.undo_stack[-30:]
            self.pending = None
        self.redo_stack.clear()
        self.dirty = True
        self.refresh()

    def undo(self) -> None:
        self.canvas.finalize_shape()
        if self.undo_stack:
            self.redo_stack.append(self.snapshot())
            self.restore_snapshot(self.undo_stack.pop())
            self.pending = None
            self.dirty = True
            self.clear_selection()
            self.refresh()

    def redo(self) -> None:
        self.canvas.finalize_shape()
        if self.redo_stack:
            self.undo_stack.append(self.snapshot())
            self.restore_snapshot(self.redo_stack.pop())
            self.pending = None
            self.dirty = True
            self.clear_selection()
            self.refresh()

    def refresh(self) -> None:
        if self.grid_spacing != self.document.grid_spacing:
            self.grid_spacing = self.document.grid_spacing
            self.grid_spacing_spin.blockSignals(True)
            self.grid_spacing_spin.setValue(self.grid_spacing)
            self.grid_spacing_spin.blockSignals(False)
        self.layer_strip.blockSignals(True)
        self.layer_strip.clear()
        for index, layer in enumerate(self.document.layers):
            item = QListWidgetItem(layer.name)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setData(Qt.ItemDataRole.UserRole + 1, layer_thumbnail(layer))
            item.setData(Qt.ItemDataRole.UserRole + 2, layer.visible)
            item.setToolTip(f"{layer.name} · {'visible' if layer.visible else 'hidden'} · drag to reorder; double-click to rename")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            self.layer_strip.addItem(item)
        self.layer_strip.setCurrentRow(self.document.active)
        self.layer_strip.blockSignals(False)
        self.update_layer_strip_width()
        self.update_layer_controls()
        self.canvas.update_size()
        self.canvas_size_button.setText(f"{self.document.width} × {self.document.height}")
        objects = self.document.layers[self.document.active].objects or []
        if self.selected_object_index is not None and self.selected_object_index >= len(objects):
            self.selected_object_index = None
            self.selected_child_path = ()
        if self.selected_object_index is not None and self.selected_child_path:
            if self.selected_object() is None:
                self.selected_child_path = ()
        self.object_panel.sync(objects, self.selected_object_index, self.selected_child_path)
        self.update_preview()
        self.setWindowTitle(f"{'*' if self.dirty else ''}{self.file_path.name if self.file_path else 'Untitled'} — Painter")

    def update_layer_controls(self) -> None:
        layer = self.document.layers[self.document.active]
        self.visibility_button.setIcon(line_icon("eye" if layer.visible else "eye_off", size=17))
        self.visibility_button.setToolTip("Hide selected layer" if layer.visible else "Show selected layer")
        self.opacity.blockSignals(True)
        self.opacity.setValue(round(layer.opacity * 100 / 255))
        self.opacity.blockSignals(False)

    def select_layer(self, index: int) -> None:
        if index >= 0 and not self.layer_strip.reordering:
            self.canvas.commit_text()
            had_shape = self.canvas.shape is not None
            self.canvas.finalize_shape()
            self.document.active = index
            if had_shape:
                self.layer_strip.blockSignals(True)
                self.layer_strip.setCurrentRow(index)
                self.layer_strip.blockSignals(False)
            self.update_layer_controls()
            self.selected_object_index = None
            self.selected_child_path = ()
            self.object_panel.sync(self.document.layers[index].objects or [], None)
            self.canvas.update()

    def selected_canvas_object(self) -> PaintObject | None:
        objects = self.document.layers[self.document.active].objects or []
        if self.selected_object_index is None or not 0 <= self.selected_object_index < len(objects):
            return None
        return objects[self.selected_object_index]

    def selected_object(self) -> PaintObject | None:
        obj = self.selected_canvas_object()
        if obj is None:
            return None
        for child_index in self.selected_child_path:
            if not 0 <= child_index < len(obj.children):
                return None
            obj = obj.children[child_index]
        return obj

    def select_object(self, index: int | tuple[int, ...] | None) -> None:
        self.canvas.finalize_shape()
        if index is not None and self.tool != "select":
            self.set_tool("select")
        if isinstance(index, tuple):
            self.selected_object_index = index[0]
            self.selected_child_path = index[1:]
        else:
            self.selected_object_index, self.selected_child_path = index, ()
        self.object_panel.sync(self.document.layers[self.document.active].objects or [],
                               self.selected_object_index, self.selected_child_path)
        self.canvas.update()

    def transform_selected_object(self, operation: str) -> None:
        obj = self.selected_object()
        if obj is None or obj.kind in ("fill", "cut"):
            return
        self.begin_change()
        if operation in ("flip_h", "flip_v"):
            if obj.kind in ("image", "selection", "text", "custom"):
                if operation == "flip_h":
                    obj.flip_horizontal = not obj.flip_horizontal
                else:
                    obj.flip_vertical = not obj.flip_vertical
            else:
                cx, cy = obj.center()
                if operation == "flip_h":
                    obj.points = [(2*cx-x, y) for x, y in obj.points]
                    obj.tangents = [(-a, b, -c, d) for a, b, c, d in obj.tangents]
                else:
                    obj.points = [(x, 2*cy-y) for x, y in obj.points]
                    obj.tangents = [(a, -b, c, -d) for a, b, c, d in obj.tangents]
        elif operation == "rotate_cw":
            obj.angle = (obj.angle + 90) % 360
        elif operation == "rotate_ccw":
            obj.angle = (obj.angle - 90) % 360
        elif operation == "invert":
            obj.inverted = not obj.inverted
        else:
            self.discard_change()
            return
        self.document.rebuild_layer()
        self.changed()

    def edit_object_property(self, key: str, value) -> None:
        obj = self.selected_object()
        if obj is None:
            return
        self.begin_change()
        if key == "center_x":
            obj.translated(float(value) - obj.center()[0], 0)
        elif key == "center_y":
            obj.translated(0, float(value) - obj.center()[1])
        elif key == "width":
            obj.size = int(value)
        elif key == "font_size":
            obj.font_size = int(value)
        elif key == "text":
            obj.text = str(value)
        elif key == "filled":
            obj.filled = bool(value)
            if obj.filled and obj.fill_color is None:
                obj.fill_color = self.background_color
        else:
            setattr(obj, key, value)
        self.document.rebuild_layer()
        self.changed()

    def edit_object_point(self, row: int, column: int, value: float) -> None:
        obj = self.selected_object()
        if obj is None or row >= len(obj.points):
            return
        self.begin_change()
        if column < 2:
            point = list(obj.points[row])
            point[column] = value
            obj.points[row] = tuple(point)
        elif row < len(obj.tangents):
            tangent = list(obj.tangents[row])
            tangent[column - 2] = value
            obj.tangents[row] = tuple(tangent)
        self.document.rebuild_layer()
        self.changed()

    def reorder_objects(self, order: list[int]) -> None:
        layer = self.document.layers[self.document.active]
        if sorted(order) != list(range(len(layer.objects or []))):
            return
        selected = self.selected_object()
        self.begin_change()
        layer.objects = [layer.objects[index] for index in order]
        self.selected_object_index = next((i for i, obj in enumerate(layer.objects) if obj is selected), None)
        self.document.rebuild_layer()
        self.changed()

    def selected_child_container(self) -> tuple[list[PaintObject], int] | None:
        parent = self.selected_canvas_object()
        if parent is None or not self.selected_child_path:
            return None
        for child_index in self.selected_child_path[:-1]:
            parent = parent.children[child_index]
        return parent.children, self.selected_child_path[-1]

    def move_selected_object(self, direction: int) -> None:
        layer = self.document.layers[self.document.active]
        index = self.selected_object_index
        if index is None:
            return
        container = self.selected_child_container()
        if container is not None:
            children, child_index = container
            target = child_index + direction
            if not 0 <= target < len(children):
                return
            self.begin_change()
            children[child_index], children[target] = children[target], children[child_index]
            self.selected_child_path = self.selected_child_path[:-1] + (target,)
            self.document.rebuild_layer()
            self.changed()
            return
        target = index + direction
        if not 0 <= target < len(layer.objects or []):
            return
        self.begin_change()
        self.document.move_object(index, target)
        self.selected_object_index = target
        self.changed()

    def delete_selected_object(self) -> None:
        index = self.selected_object_index
        if index is None:
            return
        self.begin_change()
        container = self.selected_child_container()
        if container is not None:
            children, child_index = container
            children.pop(child_index)
            self.document.rebuild_layer()
            self.selected_child_path = self.selected_child_path[:-1]
        else:
            self.document.delete_object(index)
            self.selected_object_index = None
        self.changed()

    def choose_object_color(self) -> None:
        obj = self.selected_object()
        if obj is None:
            return
        dialog = ColorDialog(obj.color, self, gradient=obj.gradient)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.begin_change()
            obj.color = dialog.rgba()
            obj.gradient = self.link_gradient_refs(dialog.gradient_spec())
            obj.color_ref = next((self.custom_color_ids[index] for index, color in enumerate(self.custom_colors)
                                  if color == obj.color), None)
            self.document.rebuild_layer()
            self.changed()

    def choose_object_fill_color(self) -> None:
        obj = self.selected_object()
        if obj is None or obj.kind not in ("rectangle", "ellipse", "polygon", "arrow"):
            return
        dialog = ColorDialog(obj.fill_color or self.background_color, self,
                             gradient=obj.fill_gradient)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.begin_change()
            obj.fill_color = dialog.rgba()
            obj.fill_gradient = self.link_gradient_refs(dialog.gradient_spec())
            obj.fill_color_ref = next((self.custom_color_ids[index] for index, color in enumerate(self.custom_colors)
                                       if color == obj.fill_color), None)
            self.document.rebuild_layer()
            self.changed()

    def choose_object_font(self) -> None:
        obj = self.selected_object()
        if obj is None or obj.kind != "text":
            return
        from PySide6.QtGui import QFont
        accepted, font = QFontDialog.getFont(QFont(obj.font_name, obj.font_size), self, "Text font")
        if not accepted:
            return
        style = font.styleName() or ("Bold" if font.bold() else "Regular")
        if font.italic() and "italic" not in style.lower() and "oblique" not in style.lower():
            style += " Italic"
        font_path = font_file_for_family(font.family(), style)
        self.begin_change()
        obj.font_family = font_path
        obj.font_size = max(1, font.pointSize())
        obj.font_name = font.family()
        self.document.rebuild_layer()
        self.changed()

    def toggle_layer(self) -> None:
        self.begin_change()
        layer = self.document.layers[self.document.active]
        layer.visible = not layer.visible
        self.changed()

    def rename_layer(self, index: int = -1) -> None:
        if index >= 0:
            self.select_layer(index)
        layer = self.document.layers[self.document.active]
        name, accepted = QInputDialog.getText(self, "Rename layer", "Name:", text=layer.name)
        if accepted and name.strip():
            self.begin_change()
            layer.name = name.strip()
            self.changed()

    def layer_context_menu(self, position) -> None:
        item = self.layer_strip.itemAt(position)
        if item is None:
            return
        index = self.layer_strip.row(item)
        self.layer_strip.setCurrentRow(index)
        menu = QMenu(self)
        layer = self.document.layers[self.document.active]
        menu.addAction("Rename", lambda: self.rename_layer(index))
        menu.addAction("Hide" if layer.visible else "Show", self.toggle_layer)
        menu.addSeparator()
        menu.addAction("Move up", lambda: self.move_layer(1))
        menu.addAction("Move down", lambda: self.move_layer(-1))
        menu.addSeparator()
        menu.addAction("Delete layer", self.delete_layer)
        menu.exec(self.layer_strip.mapToGlobal(position))

    def reorder_layers(self, order: list[int]) -> None:
        self.begin_change()
        self.document.reorder_layers(order)
        self.changed()

    def set_opacity(self, value: int) -> None:
        self.begin_change()
        self.document.layers[self.document.active].opacity = round(value * 255 / 100)
        self.changed()

    def add_layer(self) -> None:
        self.begin_change()
        self.document.add_layer()
        self.changed()

    def delete_layer(self) -> None:
        self.begin_change()
        self.document.delete_layer()
        self.changed()

    def move_layer(self, direction: int) -> None:
        self.begin_change()
        if self.document.move_layer(direction):
            self.changed()
        else:
            self.discard_change()

    def set_zoom(self, zoom: float) -> None:
        self.canvas.zoom = max(0.125, min(16.0, zoom))
        self.canvas.update_size()
        self.zoom_percent.blockSignals(True)
        self.zoom_percent.setValue(self.canvas.zoom * 100)
        self.zoom_percent.blockSignals(False)
        self.statusBar().showMessage(f"Zoom: {self.canvas.zoom * 100:.0f}%")

    def show_position(self, x: int, y: int) -> None:
        self.statusBar().showMessage(f"{x}, {y}     {self.document.width} × {self.document.height}     {self.canvas.zoom * 100:.0f}%")

    def confirm_discard(self) -> bool:
        self.canvas.commit_text()
        self.canvas.finalize_shape()
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, "Unsaved changes", "Save changes before continuing?",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                      QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def replace_document(self, document: Document, path: Path | None = None) -> None:
        self.canvas.cancel_text()
        self.canvas.cancel_path()
        self.canvas.cancel_shape()
        self.document = document
        self.selected_object_index = None
        self.selected_child_path = ()
        self.object_panel.collapsed.clear()
        self.file_path = path
        self.dirty = False
        self.pending = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.clear_selection()
        self.refresh()

    def new_document(self) -> None:
        if not self.confirm_discard():
            return
        dialog = NewCanvasDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.replace_document(Document(dialog.width_field.value(), dialog.height_field.value(),
                                           dialog.transparent.isChecked()))

    def open_document(self) -> None:
        if not self.confirm_discard():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Open image or project", "",
                                                   "Painter projects (*.painter);;Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)")
        if not filename:
            return
        try:
            path = Path(filename)
            if path.suffix.lower() == ".painter":
                self.replace_document(Document.load_project(path), path)
            else:
                self.replace_document(Document.from_image(path))
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))

    def save(self) -> bool:
        self.canvas.finalize_shape()
        if self.file_path is None:
            return self.save_as()
        try:
            self.document.save_project(self.file_path)
            self.dirty = False
            self.refresh()
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False

    def save_as(self) -> bool:
        filename, _ = QFileDialog.getSaveFileName(self, "Save layered project", str(self.file_path or "Untitled.painter"),
                                                   "Painter projects (*.painter)")
        if not filename:
            return False
        self.file_path = Path(filename).with_suffix(".painter")
        return self.save()

    def export_image(self) -> None:
        self.canvas.finalize_shape()
        formats = supported_formats()
        filters, filter_formats = export_filters(formats)
        dialog = ExportImageDialog(filters, next(iter(filter_formats)), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                filename = dialog.selectedFiles()[0]
                selected_filter = dialog.selectedNameFilter()
                path, format_name = export_target(filename, selected_filter, formats, filter_formats)
                image = self.document.composite()
                if dialog.include_grid.isChecked():
                    image = add_grid(image, self.grid_spacing)
                save_image(image, path, format_name)
            except Exception as exc:
                QMessageBox.critical(self, "Export failed", str(exc))

    def resize_canvas(self) -> None:
        dialog = NewCanvasDialog(self)
        dialog.setWindowTitle("Resize canvas")
        dialog.width_field.setValue(self.document.width)
        dialog.height_field.setValue(self.document.height)
        dialog.transparent.hide()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.begin_change()
            self.document.resize_canvas(dialog.width_field.value(), dialog.height_field.value())
            self.clear_selection()
            self.changed()

    def closeEvent(self, event) -> None:
        if self.confirm_discard():
            QApplication.instance().removeEventFilter(self)
            event.accept()
        else:
            event.ignore()


def run() -> None:
    if "--version" in sys.argv:
        from . import __version__
        print(f"Painter {__version__}")
        return
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Painter")
    app.setApplicationDisplayName("Painter")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "painter.png")))
    window = MainWindow()
    window.show()
    if "--smoke-test" in sys.argv:
        app.processEvents()
        if window.document.composite().size != (window.document.width, window.document.height):
            raise RuntimeError("Painter canvas did not initialize")
        window.close()
        return
    app.exec()
