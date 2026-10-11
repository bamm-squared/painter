import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton, QDialog

from PIL import Image

from painter.app import MainWindow, NewCanvasDialog, ExportImageDialog
from painter.color_dialog import ColorDialog
from painter.document import Document
from painter.objects import PaintObject
from painter.export import export_filters, export_target, supported_formats
from painter.layer_ui import PreviewImage, layer_thumbnail


def test_alpha_brush_and_selection_paste():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(20, 20, transparent=True))
    window.set_color((20, 40, 60, 128))
    window.size.setValue(3)
    window.show()
    app.processEvents()

    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    assert window.document.layers[0].image.getpixel((5, 5)) == (20, 40, 60, 128)

    window.canvas.selection = (4, 4, 7, 7)
    window.copy_selection()
    window.paste()
    assert len(window.document.layers) == 1
    assert window.selected_object().kind == "image"
    assert window.document.active == 0
    assert window.document.layers[0].image.getpixel((5, 5)) == (20, 40, 60, 192)
    window.dirty = False
    window.close()


def test_palette_and_layer_thumbnails():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert all(button.toolTip() for button in window.tool_buttons.values())
    assert window.swatch_buttons[0][1] == (0, 0, 0, 0)
    window.swatch_buttons[0][0].click()
    assert window.color == (0, 0, 0, 0)

    window.set_color((17, 33, 49, 100))
    window.add_custom_color()
    assert window.custom_colors == [(17, 33, 49, 100)]
    assert len(window.swatch_buttons) == 16

    window.layer_add_button.click()
    window.layer_add_button.click()
    assert window.document.active == 2
    assert window.layer_strip.currentRow() == 2
    assert window.document.layers[2].image.getpixel((0, 0)) == (255, 255, 255, 255)
    window.visibility_button.click()
    assert window.document.layers[2].visible is False
    window.opacity.setValue(50)
    assert window.document.layers[2].opacity == 128
    window.show()
    app.processEvents()
    first_thumbnail = window.layer_strip.visualItemRect(window.layer_strip.item(0)).center()
    QTest.mouseClick(window.layer_strip.viewport(), Qt.MouseButton.LeftButton, pos=first_thumbnail)
    assert window.document.active == 0
    window.dirty = False
    window.close()


def test_color_dialog_rgba_hsv_hsl_and_alpha():
    app = QApplication.instance() or QApplication([])
    dialog = ColorDialog((100, 150, 200, 128))
    assert dialog.rgba() == (100, 150, 200, 128)
    dialog.mode.setCurrentIndex(1)
    dialog.fields[0].setValue(0)
    dialog.fields[1].setValue(100)
    dialog.fields[2].setValue(100)
    assert dialog.rgba() == (255, 0, 0, 128)
    dialog.mode.setCurrentIndex(2)
    dialog.fields[0].setValue(120)
    dialog.fields[1].setValue(100)
    dialog.fields[2].setValue(50)
    assert all(abs(actual - expected) <= 1 for actual, expected in zip(dialog.rgba(), (0, 255, 0, 128)))
    dialog.mode.setCurrentIndex(0)
    dialog.fields[3].setValue(0)
    assert dialog.rgba()[1:] == (255, 1, 0)


def test_dark_and_light_themes_have_opposite_text_contrast():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.theme == "dark"
    palette = app.palette()
    assert palette.color(QPalette.ColorRole.Text).lightness() > palette.color(QPalette.ColorRole.Window).lightness()
    window.set_theme("light")
    palette = app.palette()
    assert palette.color(QPalette.ColorRole.Text).lightness() < palette.color(QPalette.ColorRole.Window).lightness()
    window.close()


def test_wheel_outer_color_can_be_lightened_and_center_is_white():
    app = QApplication.instance() or QApplication([])
    dialog = ColorDialog((0, 0, 0, 255))
    dialog.wheel.set_hs(0, 255)
    dialog.wheel_changed(0, 255)
    assert dialog.value_slider.value() == 50
    assert dialog.rgba() == (255, 0, 0, 255)
    dialog.value_slider.setValue(75)
    assert dialog.rgba() == (255, 128, 128, 255)
    dialog.value_slider.setValue(0)
    assert dialog.rgba() == (0, 0, 0, 255)
    dialog.wheel.set_hs(0, 0)
    dialog.wheel_changed(0, 0)
    assert dialog.rgba() == (255, 255, 255, 255)


def test_line_endpoint_can_be_resized_before_click_away_and_undone():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(100, 100, transparent=True))
    window.set_tool("line")
    window.size.setValue(1)
    window.show()
    app.processEvents()
    canvas = window.canvas
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(canvas, QPoint(60, 60))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
    assert canvas.shape is not None
    assert window.document.layers[0].image.getpixel((15, 15))[3] == 0
    global_handle = canvas.mapToGlobal(QPoint(60, 60))
    parent_widget = window.centralWidget()
    propagated_press = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(parent_widget.mapFromGlobal(global_handle)),
        QPointF(global_handle), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(parent_widget, propagated_press)
    assert canvas.shape is not None
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
    QTest.mouseMove(canvas, QPoint(70, 30))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(70, 30))
    assert canvas.shape.handles()["end"] == (70, 30)
    QTest.mouseClick(window.palette, Qt.MouseButton.LeftButton, pos=QPoint(180, 730))
    assert canvas.shape is None
    assert window.document.layers[0].image.getpixel((70, 30))[3] == 255
    assert window.document.layers[0].image.getpixel((60, 60))[3] == 0
    window.undo()
    assert window.document.layers[0].image.getpixel((70, 30))[3] == 0
    window.dirty = False
    window.close()


def test_rectangle_corner_and_oval_axis_center_handles():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(120, 100, transparent=True))
    window.show()
    app.processEvents()
    canvas = window.canvas
    window.set_tool("rectangle")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(canvas, QPoint(40, 40))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
    QTest.mouseMove(canvas, QPoint(60, 50))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(60, 50))
    assert canvas.shape.handles()["se"] == (60, 50)
    canvas.finalize_shape()

    window.set_tool("ellipse")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseMove(canvas, QPoint(60, 60))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
    QTest.mouseMove(canvas, QPoint(50, 45))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 45))
    assert canvas.shape.handles()["center"] == (50, 45)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 25))
    QTest.mouseMove(canvas, QPoint(50, 15))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 15))
    assert canvas.shape.handles()["top"] == (50, 15)
    QApplication.sendEvent(window, QEvent(QEvent.Type.WindowDeactivate))
    assert canvas.shape is None
    window.dirty = False
    window.close()


def test_switching_layers_commits_shape_to_original_layer_and_save_includes_it(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(80, 80, transparent=True))
    window.add_layer()
    window.set_tool("line")
    window.size.setValue(1)
    window.show()
    app.processEvents()
    canvas = window.canvas
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(canvas, QPoint(50, 50))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    assert canvas.shape is not None

    lower_thumbnail = window.layer_strip.visualItemRect(window.layer_strip.item(0)).center()
    QTest.mouseClick(window.layer_strip.viewport(), Qt.MouseButton.LeftButton, pos=lower_thumbnail)
    assert canvas.shape is None
    assert window.document.active == 0
    assert window.layer_strip.currentRow() == 0
    assert window.document.layers[1].image.getpixel((10, 10))[3] == 255
    assert window.document.layers[0].image.getpixel((15, 15))[3] == 0

    window.file_path = tmp_path / "drawing.painter"
    assert window.save()
    restored = Document.load_project(window.file_path)
    assert restored.layers[1].image.getpixel((10, 10))[3] == 255
    window.close()


def test_thumbnail_is_layer_image_and_drag_reorders_stack():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.add_layer()
    window.add_layer()
    window.document.layers[0].image.paste((255, 0, 0, 255), (0, 0, 800, 600))
    window.refresh()
    thumbnail = layer_thumbnail(window.document.layers[0]).toImage()
    assert thumbnail.pixelColor(48, 36).getRgb() == (255, 0, 0, 255)
    window.show()
    app.processEvents()

    strip = window.layer_strip
    start = strip.visualItemRect(strip.item(0)).center()
    end = strip.visualItemRect(strip.item(2)).center()
    QTest.mousePress(strip.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(strip.viewport(), end, 100)
    QTest.mouseRelease(strip.viewport(), Qt.MouseButton.LeftButton, pos=end)

    assert [layer.name for layer in window.document.layers] == ["Layer 2", "Layer 3", "Background"]
    assert window.document.active == 2
    assert window.document.composite().getpixel((0, 0)) == (255, 0, 0, 255)
    window.dirty = False
    window.close()


def test_preview_is_read_only_flattened_image():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    document = Document(8, 8, transparent=True)
    document.layers[0].image.paste((5, 10, 15, 128), (0, 0, 8, 8))
    window.replace_document(document)
    window.preview_button.click()
    preview = window.preview_dialog.findChild(PreviewImage)
    assert preview.image.pixelColor(4, 4).getRgb() == (5, 10, 15, 128)
    QTest.mouseClick(preview, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
    assert window.document.layers[0].image.getpixel((4, 4)) == (5, 10, 15, 128)
    window.preview_dialog.close()
    window.close()


def test_selecting_lower_thumbnail_reveals_it_while_preview_keeps_full_stack():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    document = Document(20, 20)
    document.layers[0].image.paste((255, 0, 0, 255), (0, 0, 20, 20))
    document.add_layer()
    window.replace_document(document)
    window.show()
    app.processEvents()
    assert window.canvas.grab().toImage().pixelColor(10, 10).getRgb() == (255, 255, 255, 255)

    first = window.layer_strip.visualItemRect(window.layer_strip.item(0)).center()
    QTest.mouseClick(window.layer_strip.viewport(), Qt.MouseButton.LeftButton, pos=first)
    app.processEvents()
    assert window.document.active == 0
    assert window.canvas.grab().toImage().pixelColor(10, 10).getRgb() == (255, 0, 0, 255)
    window.preview_button.click()
    preview = window.preview_dialog.findChild(PreviewImage)
    assert preview.image.pixelColor(10, 10).getRgb() == (255, 255, 255, 255)
    window.preview_dialog.close()
    window.close()


def test_open_preview_follows_drawing_and_layer_changes():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(32, 32, transparent=True))
    window.set_color((220, 30, 40, 255))
    window.size.setValue(1)
    window.show()
    window.preview_button.click()
    preview = window.preview_dialog.findChild(PreviewImage)
    assert preview.image.pixelColor(10, 10).alpha() == 0

    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert preview.image.pixelColor(10, 10).getRgb() == (220, 30, 40, 255)
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    window.add_layer()
    assert preview.image.pixelColor(10, 10).getRgb() == (255, 255, 255, 255)
    window.toggle_layer()
    assert preview.image.pixelColor(10, 10).getRgb() == (220, 30, 40, 255)
    window.preview_dialog.close()
    window.dirty = False
    window.close()


def test_eraser_uses_selectable_background_color_with_transparent_default():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(30, 30))
    assert window.background_color == (0, 0, 0, 0)
    window.set_tool("eraser")
    window.size.setValue(1)
    window.show()
    QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    assert window.document.layers[0].image.getpixel((5, 5)) == (0, 0, 0, 0)
    window.set_background_color((12, 34, 56, 128))
    QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
    assert window.document.layers[0].image.getpixel((8, 8)) == (12, 34, 56, 128)
    assert "#0C2238" in window.background_color_button.text()
    window.dirty = False
    window.close()


def test_oval_handles_cross_opposite_axis_and_line_handle_uses_move_cursor():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(100, 100, transparent=True))
    window.show()
    canvas = window.canvas
    window.set_tool("ellipse")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseMove(canvas, QPoint(60, 60))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 40))
    QTest.mouseMove(canvas, QPoint(80, 40))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(80, 40))
    assert canvas.shape.handles()["left"] == (60, 40)
    assert canvas.shape.handles()["right"] == (80, 40)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(70, 20))
    QTest.mouseMove(canvas, QPoint(70, 80))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(70, 80))
    assert canvas.shape.handles()["top"] == (70, 60)
    assert canvas.shape.handles()["bottom"] == (70, 80)
    canvas.finalize_shape()
    window.set_tool("line")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    QTest.mouseMove(canvas, QPoint(30, 30))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    assert canvas.shape is not None
    assert canvas.shape.handles()["end"] == (30, 30)
    assert canvas.cursor().shape() == Qt.CursorShape.SizeAllCursor
    assert canvas.handle_at(QPointF(28, 28)) == "end"
    assert not canvas.dragging
    QTest.mouseMove(canvas, QPoint(10, 70))
    QTest.mouseMove(canvas, QPoint(28, 28))
    assert canvas.cursor().shape() == Qt.CursorShape.SizeAllCursor
    canvas.finalize_shape()
    window.dirty = False
    window.close()


def test_visible_canvas_size_and_zoom_controls(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(40, 30))
    assert window.canvas_size_button.text() == "40 × 30"

    def accept_resize(dialog):
        dialog.width_field.setValue(64)
        dialog.height_field.setValue(48)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(NewCanvasDialog, "exec", accept_resize)
    window.canvas_size_button.click()
    assert (window.document.width, window.document.height) == (64, 48)
    assert window.canvas_size_button.text() == "64 × 48"
    window.zoom_percent.setValue(200)
    assert window.canvas.size().width() == 128
    assert window.canvas.size().height() == 96
    window.zoom_in_button.click()
    assert window.canvas.zoom == 2.5
    window.zoom_out_button.click()
    assert window.canvas.zoom == 2.0
    window.dirty = False
    window.close()


def test_export_defaults_to_png_and_accepts_other_image_extensions(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    document = Document(16, 16, transparent=True)
    document.layers[0].image.paste((255, 0, 0, 128), (0, 0, 16, 16))
    window.replace_document(document)

    png_path = tmp_path / "painting"

    def choose_png(dialog):
        assert dialog.windowTitle() == "Export image"
        assert dialog.selectedNameFilter().startswith("PNG image")
        assert "JPEG image" in " ".join(dialog.nameFilters())
        assert not dialog.include_grid.isChecked()
        dialog.selectFile(str(png_path))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExportImageDialog, "exec", choose_png)
    window.export_image()
    with Image.open(png_path.with_suffix(".png")) as image:
        assert image.format == "PNG"
        assert image.convert("RGBA").getpixel((8, 8)) == (255, 0, 0, 128)

    jpg_path = tmp_path / "painting.jpg"
    def choose_jpg(dialog):
        dialog.selectFile(str(jpg_path))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExportImageDialog, "exec", choose_jpg)
    window.export_image()
    with Image.open(jpg_path) as image:
        assert image.format == "JPEG"
        r, g, b = image.convert("RGB").getpixel((8, 8))
        assert r >= 250 and 120 <= g <= 140 and 120 <= b <= 140
    window.close()


def test_export_filter_choice_sets_extension_when_filename_has_none():
    formats = supported_formats()
    _, filter_formats = export_filters(formats)
    jpeg_filter = next(label for label, name in filter_formats.items() if name == "JPEG")
    path, format_name = export_target("picture", jpeg_filter, formats, filter_formats)
    assert path.name == "picture.jpg"
    assert format_name == "JPEG"
    path, format_name = export_target("picture.png", jpeg_filter, formats, filter_formats)
    assert path.name == "picture.jpg"
    assert format_name == "JPEG"


def test_grid_snaps_drawing_without_changing_canvas_pixels():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    document = Document(80, 80)
    document.grid_spacing = 10
    window.replace_document(document)
    window.set_tool("line")
    window.snap_checkbox.setChecked(True)
    window.show()
    app.processEvents()
    plain_pixel = window.canvas.grab().toImage().pixelColor(20, 5).getRgb()
    window.grid_checkbox.setChecked(True)
    app.processEvents()
    grid_pixel = window.canvas.grab().toImage().pixelColor(20, 5).getRgb()
    assert grid_pixel != plain_pixel
    assert window.show_grid_action.isChecked() and window.snap_grid_action.isChecked()
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(13, 18))
    QTest.mouseMove(window.canvas, QPoint(46, 52))
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(46, 52))
    assert window.canvas.shape.handles() == {"start": (10, 20), "end": (50, 50)}
    window.canvas.finalize_shape()
    assert window.document.layers[0].image.getpixel((20, 5)) == (255, 255, 255, 255)
    window.dirty = False
    window.close()


def test_export_grid_checkbox_defaults_off_and_can_include_grid(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(32, 32))
    window.grid_spacing_spin.setValue(8)
    without = tmp_path / "without.png"
    with_grid = tmp_path / "with.png"

    def export_without(dialog):
        assert not dialog.include_grid.isChecked()
        dialog.selectFile(str(without))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExportImageDialog, "exec", export_without)
    window.export_image()
    with Image.open(without) as image:
        assert image.convert("RGBA").getpixel((8, 4)) == (255, 255, 255, 255)

    def export_with(dialog):
        dialog.include_grid.setChecked(True)
        dialog.selectFile(str(with_grid))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExportImageDialog, "exec", export_with)
    window.export_image()
    with Image.open(with_grid) as image:
        assert image.convert("RGBA").getpixel((8, 4)) != (255, 255, 255, 255)
    assert window.document.layers[0].image.getpixel((8, 4)) == (255, 255, 255, 255)
    window.dirty = False
    window.close()


def test_grid_spacing_scales_artwork_without_resizing_canvas_with_undo_and_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    document = Document(80, 60, transparent=True)
    document.add_object(PaintObject("brush", [(20, 20), (40, 20)], (0, 0, 0, 255), 5))
    document.add_object(PaintObject("rectangle", [(20, 20), (60, 40)], (255, 0, 0, 255), 3))
    document.add_layer("Text", opaque=False)
    document.add_object(PaintObject("text", [(20, 20), (60, 40)], (0, 0, 255, 255),
                                    text="Grid", font_size=12))
    window.replace_document(document)
    window.grid_spacing_spin.setValue(30)
    assert (window.document.width, window.document.height) == (80, 60)
    assert window.document.grid_spacing == 30
    brush, rectangle = window.document.layers[0].objects
    text_obj = window.document.layers[1].objects[0]
    assert brush.points == [(30, 30), (60, 30)] and brush.size == 8
    assert rectangle.points == [(30, 30), (90, 60)]
    assert text_obj.points == [(30, 30), (90, 60)] and text_obj.font_size == 18
    assert window.document.layers[0].image.getpixel((79, 30))[0] == 255
    window.undo()
    assert (window.document.width, window.document.height, window.grid_spacing) == (80, 60, 20)
    assert window.grid_spacing_spin.value() == 20
    window.redo()
    assert (window.document.width, window.document.height, window.grid_spacing) == (80, 60, 30)
    path = tmp_path / "scaled.painter"
    window.document.save_project(path)
    reopened = Document.load_project(path)
    assert (reopened.width, reopened.height, reopened.grid_spacing) == (80, 60, 30)
    assert reopened.layers[0].objects[0].points == [(30, 30), (60, 30)]
    window.dirty = False
    window.close()


def test_palette_has_single_icon_menus_and_colors_side_by_side():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    assert window.tool_buttons["line"].menu() is not None
    assert window.tool_buttons["rectangle"].menu() is not None
    assert window.tool_buttons["select"].menu() is not None
    assert window.tool_buttons["line"].popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert window.color_button.y() == window.background_color_button.y()
    assert window.color_button.x() < window.background_color_button.x()
    assert window.color_button.width() >= 90
    assert window.custom_objects_scroll.height() >= 128
    assert window.palette.height() < 950
    window.resize(1400, 1000)
    app.processEvents()
    assert window.custom_objects_scroll.height() > 128
    assert window.palette.height() - window.custom_objects_scroll.geometry().bottom() <= 12
    window.close()


def test_selection_modes_move_resize_and_transform_selected_pixels(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    document = Document(60, 50, transparent=True)
    document.layers[0].image.putpixel((15, 15), (255, 0, 0, 255))
    window.replace_document(document)
    window.show()
    app.processEvents()
    window.set_tool("select")
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    QTest.mouseMove(window.canvas, QPoint(25, 25))
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(25, 25))
    assert window.canvas.selection == (5, 5, 26, 26)
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(15, 15))
    QTest.mouseMove(window.canvas, QPoint(25, 15))
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(25, 15))
    assert window.selected_object().kind == "selection"
    assert window.document.layers[0].image.getpixel((15, 15))[3] == 0
    assert window.document.layers[0].image.getpixel((25, 15)) == (255, 0, 0, 255)
    source_bounds = window.selected_object().mask.getbbox()
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(36, 26))
    QTest.mouseMove(window.canvas, QPoint(46, 36))
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(46, 36))
    assert window.selected_object().points[1] == (46, 36)
    assert window.selected_object().mask.getbbox() == source_bounds
    window.object_panel.transform_requested.emit("invert")
    assert window.document.layers[0].image.getpixel((30, 20))[1] > 0
    window.object_panel.transform_requested.emit("flip_h")
    assert window.selected_object().flip_horizontal
    window.document.save_project(tmp_path / "moved.painter")
    assert Document.load_project(tmp_path / "moved.painter").layers[0].objects[-1].kind == "selection"
    window.dirty = False
    window.close()


def test_polygon_and_freeform_selection_create_masks():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(50, 50, transparent=True))
    window.show()
    app.processEvents()
    window.set_tool("select_polygon")
    for point in (QPoint(5, 5), QPoint(20, 5), QPoint(20, 20)):
        QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=point)
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    assert window.canvas.selection_mask.getpixel((15, 10)) == 255
    assert window.canvas.selection_mask.getpixel((5, 20)) == 0
    window.set_tool("select_freeform")
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(6, 6))
    QTest.mouseMove(window.canvas, QPoint(20, 6))
    QTest.mouseMove(window.canvas, QPoint(20, 20))
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(6, 20))
    assert window.canvas.selection_mask.getpixel((15, 10)) == 255
    window.close()
