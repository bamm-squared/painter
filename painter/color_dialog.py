"""Color picker with a hue/saturation wheel and three numeric color models."""

from __future__ import annotations

import math
from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QSlider, QSpinBox, QVBoxLayout, QWidget, QCheckBox, QPushButton,
)

from .gradient import default_gradient, gradient_tile
from .dialog_ui import IndependentDialog


class ColorPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(54, 36)
        self.color = QColor(0, 0, 0, 255)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        for y in range(0, self.height(), 8):
            for x in range(0, self.width(), 8):
                painter.fillRect(x, y, 8, 8,
                                 QColor("#ffffff") if (x // 8 + y // 8) % 2 else QColor("#d6dce6"))
        painter.fillRect(self.rect(), self.color)
        painter.setPen(QPen(QColor("#bcc5d3"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()


class HueWheel(QWidget):
    changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(228, 228)
        self.hue = 0
        self.saturation = 0
        self._image = QImage(220, 220, QImage.Format.Format_ARGB32)
        center, radius = 109.5, 105
        for y in range(220):
            for x in range(220):
                dx, dy = x - center, center - y
                distance = math.hypot(dx, dy)
                if distance > radius:
                    self._image.setPixelColor(x, y, QColor(0, 0, 0, 0))
                else:
                    hue = round(math.degrees(math.atan2(dy, dx))) % 360
                    saturation = round(min(1.0, distance / radius) * 255)
                    self._image.setPixelColor(x, y, QColor.fromHsv(hue, saturation, 255))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawImage(4, 4, self._image)
        angle = math.radians(self.hue)
        distance = self.saturation / 255 * 105
        x = 113.5 + math.cos(angle) * distance
        y = 113.5 - math.sin(angle) * distance
        painter.setPen(QPen(QColor("#1d2534"), 1.5))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(int(x - 5), int(y - 5), 10, 10)
        painter.end()

    def set_hs(self, hue: int, saturation: int) -> None:
        self.hue = hue % 360
        self.saturation = max(0, min(255, saturation))
        self.update()

    def pick(self, event) -> None:
        dx = event.position().x() - 113.5
        dy = 113.5 - event.position().y()
        self.hue = round(math.degrees(math.atan2(dy, dx))) % 360
        self.saturation = round(min(1, math.hypot(dx, dy) / 105) * 255)
        self.changed.emit(self.hue, self.saturation)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pick(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.pick(event)


class GradientPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.spec = default_gradient((0, 0, 0, 255))
        self.setFixedHeight(42)

    def paintEvent(self, event) -> None:
        image = gradient_tile((max(1, self.width()), max(1, self.height())), self.spec)
        qimage = QImage(image.tobytes(), image.width, image.height, image.width*4,
                        QImage.Format.Format_RGBA8888).copy()
        painter = QPainter(self)
        painter.drawImage(self.rect(), qimage)
        painter.setPen(QPen(QColor("#8792a7"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()


class GradientDialog(IndependentDialog):
    def __init__(self, spec: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure gradient")
        self.setMinimumWidth(360)
        self.spec = deepcopy(spec)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("START AND STOP COLORS"))
        colors = QHBoxLayout()
        self.start_button = QPushButton()
        self.stop_button = QPushButton()
        self.start_button.clicked.connect(lambda: self.choose_endpoint("start"))
        self.stop_button.clicked.connect(lambda: self.choose_endpoint("stop"))
        colors.addWidget(self.start_button)
        colors.addWidget(self.stop_button)
        layout.addLayout(colors)
        layout.addWidget(QLabel("Halfway color position"))
        self.midpoint = QSpinBox()
        self.midpoint.setRange(1, 99)
        self.midpoint.setSuffix("%")
        self.midpoint.setValue(round(float(self.spec.get("midpoint", .5))*100))
        self.midpoint.valueChanged.connect(self.update_spec)
        layout.addWidget(self.midpoint)
        layout.addWidget(QLabel("Start location"))
        self.mode = QComboBox()
        self.mode.addItem("Edge · linear", "edge")
        self.mode.addItem("Point · radial", "point")
        self.mode.setCurrentIndex(1 if self.spec.get("mode") == "point" else 0)
        self.mode.currentIndexChanged.connect(self.update_spec)
        layout.addWidget(self.mode)
        self.edge = QComboBox()
        for label, value in (("Left edge", "left"), ("Right edge", "right"),
                             ("Top edge", "top"), ("Bottom edge", "bottom")):
            self.edge.addItem(label, value)
        self.edge.setCurrentIndex(max(0, self.edge.findData(self.spec.get("edge", "left"))))
        self.edge.currentIndexChanged.connect(self.update_spec)
        layout.addWidget(self.edge)
        self.snap_center = QCheckBox("Snap start point to center")
        self.snap_center.setChecked(bool(self.spec.get("snap_center", True)))
        self.snap_center.toggled.connect(self.update_spec)
        layout.addWidget(self.snap_center)
        point_row = QHBoxLayout()
        self.point_x = QSpinBox()
        self.point_y = QSpinBox()
        for spin, value in ((self.point_x, "point_x"), (self.point_y, "point_y")):
            spin.setRange(0, 100)
            spin.setSuffix("%")
            spin.setValue(round(float(self.spec.get(value, .5))*100))
            spin.valueChanged.connect(self.update_spec)
        point_row.addWidget(QLabel("X"))
        point_row.addWidget(self.point_x)
        point_row.addWidget(QLabel("Y"))
        point_row.addWidget(self.point_y)
        layout.addLayout(point_row)
        self.preview = GradientPreview()
        layout.addWidget(self.preview)
        note = QLabel("The halfway setting changes the color curve without reversing it.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_spec()

    def choose_endpoint(self, endpoint: str) -> None:
        dialog = ColorDialog(tuple(self.spec[endpoint]), self, allow_gradient=False)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.spec[endpoint] = list(dialog.rgba())
            self.update_spec()

    def update_spec(self, *_args) -> None:
        self.spec["midpoint"] = self.midpoint.value()/100
        self.spec["mode"] = self.mode.currentData()
        self.spec["edge"] = self.edge.currentData()
        self.spec["point_x"] = self.point_x.value()/100
        self.spec["point_y"] = self.point_y.value()/100
        self.spec["snap_center"] = self.snap_center.isChecked()
        radial = self.spec["mode"] == "point"
        self.edge.setVisible(not radial)
        self.snap_center.setVisible(radial)
        self.point_x.setEnabled(radial and not self.snap_center.isChecked())
        self.point_y.setEnabled(radial and not self.snap_center.isChecked())
        for button, key, label in ((self.start_button, "start", "Start"),
                                   (self.stop_button, "stop", "Stop")):
            color = QColor(*self.spec[key])
            button.setText(f"{label} · {color.name(QColor.NameFormat.HexArgb)}")
        self.preview.spec = deepcopy(self.spec)
        self.preview.update()

    def gradient(self) -> dict:
        return deepcopy(self.spec)


class ColorDialog(IndependentDialog):
    def __init__(self, rgba: tuple[int, int, int, int], parent=None,
                 gradient: dict | None = None, allow_gradient: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Choose color")
        self.setMinimumWidth(340)
        self.color = QColor(*rgba)
        self._syncing = False
        self._gradient = deepcopy(gradient) if gradient is not None else default_gradient(rgba)
        self._has_gradient = gradient is not None
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel("Pick a hue and saturation")
        intro.setObjectName("sectionTitle")
        layout.addWidget(intro)
        self.wheel = HueWheel()
        layout.addWidget(self.wheel, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.wheel.changed.connect(self.wheel_changed)

        self.value_label = QLabel("Shade")
        self.value_slider = QSlider(Qt.Orientation.Horizontal)
        self.value_slider.setRange(0, 100)
        self.value_slider.valueChanged.connect(self.value_changed)
        layout.addWidget(self.value_label)
        layout.addWidget(self.value_slider)
        shade_labels = QHBoxLayout()
        shade_labels.addWidget(QLabel("Darker"))
        shade_labels.addStretch()
        shade_labels.addWidget(QLabel("Lighter"))
        layout.addLayout(shade_labels)

        layout.addWidget(QLabel("Alpha"))
        self.alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self.alpha_slider.setRange(0, 255)
        self.alpha_slider.valueChanged.connect(self.alpha_changed)
        layout.addWidget(self.alpha_slider)

        row = QHBoxLayout()
        self.preview = ColorPreview()
        row.addWidget(self.preview)
        self.hex_label = QLabel()
        row.addWidget(self.hex_label)
        row.addStretch()
        layout.addLayout(row)

        self.mode = QComboBox()
        self.mode.addItems(["RGBA", "HSV + alpha", "HSL + alpha"])
        self.mode.currentIndexChanged.connect(self.sync_controls)
        layout.addWidget(self.mode)
        fields = QHBoxLayout()
        self.field_labels: list[QLabel] = []
        self.fields: list[QSpinBox] = []
        for _ in range(4):
            column = QVBoxLayout()
            label = QLabel()
            spin = QSpinBox()
            spin.setRange(0, 255)
            spin.valueChanged.connect(self.fields_changed)
            column.addWidget(label)
            column.addWidget(spin)
            fields.addLayout(column)
            self.field_labels.append(label)
            self.fields.append(spin)
        layout.addLayout(fields)

        gradient_row = QHBoxLayout()
        self.gradient_enabled = QCheckBox("Use gradient")
        self.gradient_enabled.setChecked(gradient is not None)
        self.gradient_enabled.setVisible(allow_gradient)
        self.gradient_button = QPushButton("Configure gradient…")
        self.gradient_button.setVisible(allow_gradient)
        self.gradient_button.clicked.connect(self.configure_gradient)
        gradient_row.addWidget(self.gradient_enabled)
        gradient_row.addWidget(self.gradient_button)
        layout.addLayout(gradient_row)
        self.gradient_preview = GradientPreview()
        self.gradient_preview.spec = deepcopy(self._gradient)
        self.gradient_preview.setVisible(allow_gradient and gradient is not None)
        self.gradient_enabled.toggled.connect(self.gradient_preview.setVisible)
        layout.addWidget(self.gradient_preview)
        self.save_custom = QCheckBox("Add to custom colors for this session")
        self.save_custom.setVisible(allow_gradient)
        layout.addWidget(self.save_custom)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.sync_controls()

    def rgba(self) -> tuple[int, int, int, int]:
        return self.color.getRgb()

    def gradient_spec(self) -> dict | None:
        if not self.gradient_enabled.isChecked():
            return None
        result = deepcopy(self._gradient)
        if not self._has_gradient:
            result["start"] = list(self.rgba())
        return result

    def configure_gradient(self) -> None:
        if not self._has_gradient:
            self._gradient["start"] = list(self.rgba())
        dialog = GradientDialog(self._gradient, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._gradient = dialog.gradient()
            self._has_gradient = True
            self.gradient_preview.spec = deepcopy(self._gradient)
            self.gradient_preview.update()
            self.gradient_enabled.setChecked(True)

    def set_color(self, color: QColor) -> None:
        self.color = color
        self.sync_controls()

    def wheel_changed(self, hue: int, saturation: int) -> None:
        self._syncing = True
        self.value_slider.setValue(50)
        self._syncing = False
        self.apply_picker()

    def value_changed(self, value: int) -> None:
        if not self._syncing:
            self.apply_picker()

    def apply_picker(self) -> None:
        base = QColor.fromHsv(self.wheel.hue, self.wheel.saturation, 255)
        tone = self.value_slider.value()
        if tone <= 50:
            rgb = tuple(round(channel * tone / 50) for channel in base.getRgb()[:3])
        else:
            rgb = tuple(round(channel + (255 - channel) * (tone - 50) / 50)
                        for channel in base.getRgb()[:3])
        self.color = QColor(*rgb, self.alpha_slider.value())
        self.sync_controls(preserve_picker=True)

    def alpha_changed(self, alpha: int) -> None:
        if not self._syncing:
            color = QColor(self.color)
            color.setAlpha(alpha)
            self.color = color
            self.sync_controls(preserve_picker=True)

    def fields_changed(self) -> None:
        if self._syncing:
            return
        a, b, c, alpha = (field.value() for field in self.fields)
        if self.mode.currentIndex() == 0:
            color = QColor(a, b, c, alpha)
        elif self.mode.currentIndex() == 1:
            color = QColor.fromHsv(a % 360, round(b * 255 / 100), round(c * 255 / 100), alpha)
        else:
            color = QColor.fromHsl(a % 360, round(b * 255 / 100), round(c * 255 / 100), alpha)
        self.set_color(color)

    def sync_controls(self, _index=None, preserve_picker: bool = False) -> None:
        self._syncing = True
        mode = self.mode.currentIndex()
        hue = max(0, self.color.hsvHue())
        if not preserve_picker:
            self.wheel.set_hs(hue, self.color.hsvSaturation())
            self.value_slider.setValue(round(self.color.value() * 50 / 255))
        self.alpha_slider.setValue(self.color.alpha())
        if mode == 0:
            labels = ("R", "G", "B", "A")
            values = self.color.getRgb()
            limits = (255, 255, 255, 255)
        elif mode == 1:
            labels = ("H°", "S%", "V%", "A")
            values = (hue, round(self.color.hsvSaturation() * 100 / 255),
                      round(self.color.value() * 100 / 255), self.color.alpha())
            limits = (359, 100, 100, 255)
        else:
            labels = ("H°", "S%", "L%", "A")
            values = (max(0, self.color.hslHue()), round(self.color.hslSaturation() * 100 / 255),
                      round(self.color.lightness() * 100 / 255), self.color.alpha())
            limits = (359, 100, 100, 255)
        for label, field, text, value, limit in zip(self.field_labels, self.fields, labels, values, limits):
            label.setText(text)
            field.setMaximum(limit)
            field.setValue(value)
        r, g, b, a = self.rgba()
        self.hex_label.setText(f"#{r:02X}{g:02X}{b:02X} · alpha {a}")
        self.preview.color = self.color
        self.preview.update()
        base = QColor.fromHsv(self.wheel.hue, self.wheel.saturation, 255).name()
        self.value_slider.setStyleSheet(
            "QSlider::groove:horizontal {height: 10px; border-radius: 5px; "
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #000000,stop:0.5 %s,stop:1 #ffffff);}" 
            "QSlider::sub-page:horizontal {background: transparent;}"
            "QSlider::add-page:horizontal {background: transparent;}"
            "QSlider::handle:horizontal {background:#fff;border:2px solid #52617d;width:16px;"
            "margin:-5px 0;border-radius:9px;}" % base)
        self._syncing = False
