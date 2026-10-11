import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from painter.app import MainWindow
from painter.document import Document
from painter.fonts import font_file_for_family, load_font
from painter.objects import PaintObject, object_mask, wrapped_text_lines


def test_object_history_rebuild_reorder_delete_and_project_roundtrip(tmp_path):
    document = Document(40, 40, transparent=True)
    red = PaintObject("line", [(5, 5), (30, 5)], (255, 0, 0, 255), 3)
    blue = PaintObject("line", [(5, 5), (30, 5)], (0, 0, 255, 255), 3)
    document.add_object(red)
    document.add_object(blue)
    assert document.layers[0].image.getpixel((15, 5))[:3] == (0, 0, 255)
    document.move_object(1, 0)
    assert document.layers[0].image.getpixel((15, 5))[:3] == (255, 0, 0)
    document.delete_object(1)
    assert document.layers[0].image.getpixel((15, 5))[:3] == (0, 0, 255)
    path = tmp_path / "editable.painter"
    document.save_project(path)
    reopened = Document.load_project(path)
    assert len(reopened.layers[0].objects) == 1
    reopened.layers[0].objects[0].points[1] = (35, 20)
    reopened.rebuild_layer()
    assert reopened.layers[0].image.getpixel((35, 20))[:3] == (0, 0, 255)


def test_path_modes_finish_on_enter_and_inspector_edits_points():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(120, 120, transparent=True))
    window.show()
    canvas = window.canvas
    window.set_tool("spline")
    for point in (QPoint(10, 10), QPoint(40, 70), QPoint(90, 30)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    assert canvas.path_draft is not None
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    obj = window.document.layers[0].objects[0]
    assert obj.kind == "spline"
    assert len(obj.tangents) == 3
    assert window.selected_object_index == 0
    window.object_panel.points_table.item(1, 0).setText("50")
    assert obj.points[1][0] == 50
    window.object_panel.width.setValue(9)
    assert obj.size == 9
    window.delete_selected_object()
    assert window.document.layers[0].objects == []
    window.dirty = False
    window.close()


def test_three_point_shapes_and_rotating_rectangle():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(150, 150, transparent=True))
    window.show()
    canvas = window.canvas
    window.set_tool("rectangle_3point")
    for point in (QPoint(30, 30), QPoint(80, 30), QPoint(60, 60)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    obj = window.document.layers[0].objects[0]
    assert obj.kind == "rectangle"
    assert obj.center() == (55, 45)
    window.object_panel.angle.setValue(30)
    assert obj.angle == 30
    assert obj.handles()["rotate"] != (55, -11)
    window.dirty = False
    window.close()


def test_arrow_width_zero_is_a_line_and_can_be_widened():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(100, 100, transparent=True))
    window.show()
    canvas = window.canvas
    window.set_tool("arrow")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 50))
    QTest.mouseMove(canvas, QPoint(80, 50))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(80, 50))
    obj = window.document.layers[0].objects[0]
    assert obj.kind == "arrow" and obj.arrow_width == 0
    assert object_mask(obj, (100, 100)).getpixel((40, 50)) == 255
    window.object_panel.arrow_width.setValue(14)
    assert obj.arrow_width == 14
    assert object_mask(obj, (100, 100)).getpixel((40, 55)) == 255
    handle = obj.handles()["width"]
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(round(handle[0]), round(handle[1])))
    QTest.mouseMove(canvas, QPoint(round(handle[0]), 75))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(round(handle[0]), 75))
    assert obj.arrow_width >= 45
    window.dirty = False
    window.close()


def test_text_is_typed_on_canvas_and_remains_editable():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(160, 100, transparent=True))
    window.show()
    window.set_tool("text")
    QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert window.canvas.text_editor is not None
    QTest.keyClicks(window.canvas.text_editor, "Hello")
    assert window.canvas.text_draft.text == "Hello"
    QTest.keyClick(window.canvas.text_editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    obj = window.document.layers[0].objects[0]
    assert obj.kind == "text" and obj.text == "Hello"
    window.object_panel.text_edit.setPlainText("Hello world")
    assert obj.text == "Hello world"
    window.dirty = False
    window.close()


def test_font_dialog_applies_selected_font_and_cancel_keeps_text():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(240, 100, transparent=True))
    window.document.add_object(PaintObject("text", [(10, 10)], text="Hello", font_size=28))
    window.select_object(0)
    obj = window.selected_object()
    before = window.document.layers[0].image.tobytes()

    installed_font = font_file_for_family("Arial")
    assert os.path.isfile(installed_font)
    with patch("painter.app.QFontDialog.getFont", return_value=(True, QFont("Arial", 28))):
        window.choose_object_font()
    assert obj.font_name == "Arial"
    assert obj.font_family == installed_font
    assert window.document.layers[0].image.tobytes() != before

    with patch("painter.app.QFontDialog.getFont", return_value=(False, QFont("DejaVu Sans", 12))):
        window.choose_object_font()
    assert obj.font_name == "Arial" and obj.font_size == 28
    window.dirty = False
    window.close()


def test_object_details_and_history_share_panel_height():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(240, 100, transparent=True))
    window.document.add_object(PaintObject("text", [(10, 10)], text="Hello"))
    window.select_object(0)
    window.resize(1190, 790)
    window.show()
    app.processEvents()
    panel = window.object_panel
    assert panel.details_scroll.height() > 220
    assert panel.details_scroll.height() <= panel.height() // 2
    assert panel.history.height() > 220
    window.dirty = False
    window.close()


def test_filled_shapes_use_separate_border_and_background_colors(tmp_path):
    border = (230, 20, 30, 255)
    interior = (20, 40, 220, 128)
    shapes = (
        ("rectangle", [(10, 10), (60, 50)], (35, 30), (10, 30)),
        ("ellipse", [(10, 10), (60, 50)], (35, 30), (35, 10)),
        ("polygon", [(10, 10), (60, 10), (35, 50)], (35, 25), (35, 10)),
        ("arrow", [(10, 30), (70, 30)], (25, 30), (25, 22)),
    )
    for kind, points, middle, edge in shapes:
        document = Document(80, 60, transparent=True)
        obj = PaintObject(kind, points, border, 3, filled=True, fill_color=interior,
                          arrow_width=16 if kind == "arrow" else 0)
        document.add_object(obj)
        assert document.layers[0].image.getpixel(middle) == interior
        assert document.layers[0].image.getpixel(edge) == border
        path = tmp_path / f"{kind}.painter"
        document.save_project(path)
        reopened = Document.load_project(path)
        assert reopened.layers[0].objects[0].fill_color == interior
        assert reopened.layers[0].image.getpixel(middle) == interior


def test_rectangle_preview_and_placement_clear_transparent_fill():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(80, 60))
    window.set_color((230, 20, 30, 255))
    window.set_background_color((0, 0, 0, 0))
    window.shape_fill.setChecked(True)
    window.set_tool("rectangle")
    window.show()
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(window.canvas, QPoint(60, 50))
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(60, 50))
    preview = window.document.composite(window.canvas.preview, window.canvas.erase_mask,
                                        erase_color=window.canvas.preview_fill_color)
    assert preview.getpixel((35, 30))[3] == 0
    assert preview.getpixel((10, 30)) == (230, 20, 30, 255)
    window.canvas.finalize_shape()
    obj = window.document.layers[0].objects[0]
    assert obj.fill_color == (0, 0, 0, 0)
    assert window.document.layers[0].image.getpixel((35, 30))[3] == 0
    assert window.document.layers[0].image.getpixel((10, 30)) == (230, 20, 30, 255)
    window.object_panel.filled.setChecked(False)
    assert window.document.layers[0].image.getpixel((35, 30)) == (255, 255, 255, 255)
    window.object_panel.filled.setChecked(True)
    assert window.document.layers[0].image.getpixel((35, 30))[3] == 0
    window.dirty = False
    window.close()


def test_select_tool_rotates_rectangle_and_edits_spline_tangent():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(160, 160, transparent=True))
    window.document.add_object(PaintObject("rectangle", [(40, 50), (90, 90)], (220, 30, 30, 255), 3))
    window.document.add_object(PaintObject("spline", [(20, 120), (70, 110), (130, 130)],
                                           (0, 0, 255, 255), 3,
                                           tangents=[(-8, 0, 8, 0), (-15, 0, 15, 0), (-8, 0, 8, 0)]))
    window.refresh()
    window.show()
    window.set_tool("select")
    window.select_object(0)
    canvas = window.canvas
    rotate = window.selected_object().handles()["rotate"]
    center = window.selected_object().center()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(round(rotate[0]), round(rotate[1])))
    QTest.mouseMove(canvas, QPoint(round(center[0] + 35), round(center[1])))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                       pos=QPoint(round(center[0] + 35), round(center[1])))
    assert 75 < window.document.layers[0].objects[0].angle < 105

    window.select_object(1)
    outgoing = window.selected_object().handles()["out1"]
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(round(outgoing[0]), round(outgoing[1])))
    QTest.mouseMove(canvas, QPoint(round(outgoing[0] + 12), round(outgoing[1] - 8)))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                       pos=QPoint(round(outgoing[0] + 12), round(outgoing[1] - 8)))
    assert window.selected_object().tangents[1][2] > 15
    window.dirty = False
    window.close()


def test_history_panel_changes_stroke_order_and_polygon_arc_modes():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(120, 120, transparent=True))
    window.document.add_object(PaintObject("brush", [(10, 10), (50, 10)], (255, 0, 0, 255), 5))
    window.document.add_object(PaintObject("brush", [(10, 10), (50, 10)], (0, 0, 255, 255), 5))
    window.refresh()
    window.select_object(1)
    assert window.document.layers[0].image.getpixel((25, 10))[:3] == (0, 0, 255)
    window.object_panel.move_requested.emit(-1)
    assert window.document.layers[0].image.getpixel((25, 10))[:3] == (255, 0, 0)
    window.show()
    history = window.object_panel.history
    top = history.visualItemRect(history.item(0)).center()
    bottom = history.visualItemRect(history.item(1)).center()
    QTest.mousePress(history.viewport(), Qt.MouseButton.LeftButton, pos=top)
    QTest.mouseMove(history.viewport(), bottom, 100)
    QTest.mouseRelease(history.viewport(), Qt.MouseButton.LeftButton, pos=bottom)
    assert window.document.layers[0].image.getpixel((25, 10))[:3] == (0, 0, 255)
    window.set_tool("polygon")
    for point in (QPoint(20, 30), QPoint(50, 30), QPoint(40, 60)):
        QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=point)
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    assert window.document.layers[0].objects[-1].kind == "polygon"
    window.set_tool("arc_3point")
    for point in (QPoint(70, 60), QPoint(80, 45), QPoint(90, 60)):
        QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=point)
    assert window.document.layers[0].objects[-1].kind == "arc"
    window.dirty = False
    window.close()


def test_creation_mode_dropdowns_circle_oval_arrow_arc_and_polyline():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(160, 160, transparent=True))
    window.show()
    canvas = window.canvas
    assert [action.text().split(" · ")[0] for action in window.tool_buttons["line"].menu().actions()][:4] == [
        "Line", "Spline", "Polyline", "Arrow"]

    window.set_tool("circle")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    QTest.mouseMove(canvas, QPoint(70, 50))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(70, 50))
    circle = window.document.layers[0].objects[-1]
    assert circle.kind == "ellipse"
    assert circle.points == [(30.0, 30.0), (70.0, 70.0)]

    window.set_tool("ellipse_3point")
    for point in (QPoint(100, 50), QPoint(130, 50), QPoint(100, 65)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    oval = window.document.layers[0].objects[-1]
    assert oval.kind == "ellipse" and oval.points == [(70.0, 35.0), (130.0, 65.0)]

    window.set_tool("arrow_3point")
    for point in (QPoint(10, 100), QPoint(80, 100), QPoint(40, 110)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    arrow = window.document.layers[0].objects[-1]
    assert arrow.kind == "arrow" and arrow.arrow_width == 20

    window.set_tool("arc")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 90))
    QTest.mouseMove(canvas, QPoint(145, 140))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(145, 140))
    arc = window.document.layers[0].objects[-1]
    assert arc.kind == "arc" and arc.start_angle == 0 and arc.end_angle == 180

    window.set_tool("polyline")
    for point in (QPoint(10, 130), QPoint(40, 140), QPoint(70, 130)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    polyline = window.document.layers[0].objects[-1]
    assert polyline.kind == "polyline" and len(polyline.points) == 3
    assert window.document.layers[0].image.getpixel((40, 140))[3] == 255
    window.dirty = False
    window.close()


def test_eraser_and_text_history_survive_project_save(tmp_path):
    document = Document(60, 60)
    document.add_object(PaintObject("eraser", [(10, 10), (20, 10)], (0, 0, 0, 0), 7))
    document.add_object(PaintObject("text", [(5, 30)], (10, 30, 80, 200),
                                    text="Saved", font_size=14))
    path = tmp_path / "history.painter"
    document.save_project(path)
    loaded = Document.load_project(path)
    assert [obj.kind for obj in loaded.layers[0].objects] == ["eraser", "text"]
    assert loaded.layers[0].objects[1].text == "Saved"
    assert loaded.layers[0].image.getpixel((15, 10))[3] == 0
    loaded.layers[0].objects[0].size = 15
    loaded.rebuild_layer()
    assert loaded.layers[0].image.getpixel((15, 15))[3] == 0


def test_fill_mask_survives_save_and_can_be_recolored(tmp_path):
    document = Document(20, 20)
    assert document.flood_fill((5, 5), (255, 0, 0, 255))
    path = tmp_path / "fill.painter"
    document.save_project(path)
    loaded = Document.load_project(path)
    assert loaded.layers[0].objects[0].mask.getpixel((5, 5)) == 255
    loaded.layers[0].objects[0].color = (0, 0, 255, 128)
    loaded.rebuild_layer()
    assert loaded.layers[0].image.getpixel((5, 5)) == (0, 0, 255, 128)


def test_new_rectangle_and_oval_rotate_from_orientation_handle():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(130, 130, transparent=True))
    window.show()
    canvas = window.canvas
    for tool, left, top, right, bottom in (
        ("rectangle", 30, 40, 70, 70), ("ellipse", 70, 60, 110, 90)
    ):
        window.set_tool(tool)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(left, top))
        QTest.mouseMove(canvas, QPoint(right, bottom))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(right, bottom))
        rotate = canvas.shape.handles()["rotate"]
        center = canvas.shape.handles()["center"]
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(round(rotate[0]), round(rotate[1])))
        QTest.mouseMove(canvas, QPoint(round(center[0] + 30), round(center[1])))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=QPoint(round(center[0] + 30), round(center[1])))
        assert 75 < canvas.shape.angle < 105
        canvas.finalize_shape()
        assert 75 < window.document.layers[0].objects[-1].angle < 105
    window.dirty = False
    window.close()


def test_text_box_wraps_to_width_and_overflows_only_at_bottom_or_for_one_glyph():
    font = load_font("DejaVuSans.ttf", 18)
    width = max(font.getbbox(word)[2] for word in ("Hello", "world")) + 1
    assert wrapped_text_lines("Hello world", font, width) == ["Hello", "world"]
    assert wrapped_text_lines("WW", font, 1) == ["W", "W"]
    wide = PaintObject("text", [(5, 5), (5 + width, 14)], text="Hello world", font_size=18)
    mask = object_mask(wide, (120, 90))
    assert mask.getbbox()[2] <= 5 + width
    assert mask.getbbox()[3] > 14
    narrow = PaintObject("text", [(5, 5), (6, 50)], text="W", font_size=18)
    assert object_mask(narrow, (120, 90)).getbbox()[2] > 6


def test_text_drag_creates_editable_box_and_corner_resizes_it():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(220, 140, transparent=True))
    window.show()
    window.set_tool("text")
    canvas = window.canvas
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(canvas, QPoint(100, 55))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 55))
    assert canvas.text_draft.points == [(10, 10), (100, 55)]
    QTest.keyClicks(canvas.text_editor, "Hello world")
    QTest.keyClick(canvas.text_editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    obj = window.document.layers[0].objects[0]
    assert obj.kind == "text" and obj.points == [(10, 10), (100, 55)]
    assert all(key in obj.handles() for key in ("nw", "ne", "se", "sw", "center", "rotate"))
    window.set_tool("select")
    corner = obj.handles()["se"]
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(*map(round, corner)))
    QTest.mouseMove(canvas, QPoint(55, 40))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(55, 40))
    assert obj.points[1] == (55, 40)
    assert canvas.object_at((40, 30)) == 0
    window.dirty = False
    window.close()


def test_brush_stroke_keeps_same_width_on_horizontal_and_diagonal_segments():
    from math import sqrt
    from painter.objects import draw_round_stroke
    mask = Image.new("L", (120, 80))
    draw_round_stroke(mask, [(10, 20), (50, 20), (90, 60)], 5)
    horizontal = [mask.getpixel((30, 20 + step)) for step in range(-8, 9)]
    diagonal = [mask.getpixel((round(70 - step / sqrt(2)), round(40 + step / sqrt(2))))
                for step in range(-8, 9)]
    assert sum(value > 127 for value in horizontal) == sum(value > 127 for value in diagonal)
    assert mask.getpixel((50, 20)) == 255


def test_text_with_missing_font_still_renders():
    from painter.objects import PaintObject, object_mask
    text = PaintObject("text", [(4, 4), (90, 45)], text="Portable",
                       font_family="missing-font-file.ttf", font_name="Missing font", font_size=20)
    assert object_mask(text, (100, 50)).getbbox() is not None
