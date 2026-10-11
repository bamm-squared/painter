import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QWidget, QToolButton, QMessageBox, QInputDialog

from painter.app import MainWindow
from painter.color_dialog import ColorDialog, GradientDialog
from painter.custom_ui import CustomObjectGallery, TemplateButton
from painter.custom_objects import CustomLibrary, CustomTemplate, template_from_document
from painter.document import Document
from painter.gradient import default_gradient, gradient_tile
from painter.objects import PaintObject


def test_monotone_gradient_midpoint_and_edges():
    spec = default_gradient((0, 0, 0, 255))
    spec.update(stop=[200, 100, 50, 0], midpoint=.8)
    tile = gradient_tile((11, 3), spec)
    assert tile.getpixel((0, 1)) == (0, 0, 0, 255)
    assert tile.getpixel((10, 1)) == (200, 100, 50, 0)
    assert abs(tile.getpixel((8, 1))[0] - 100) <= 2
    assert all(tile.getpixel((x, 1))[0] <= tile.getpixel((x+1, 1))[0] for x in range(10))
    spec.update(mode="point", point_x=.2, point_y=.5, snap_center=False)
    radial = gradient_tile((11, 11), spec)
    assert radial.getpixel((2, 5)) == (0, 0, 0, 255)
    for point in ((0, 5), (10, 5), (5, 0), (5, 10), (0, 0), (10, 10)):
        assert radial.getpixel(point) == (200, 100, 50, 0)
    assert radial.getpixel((1, 5))[0] > radial.getpixel((3, 5))[0]


def test_gradient_is_editable_and_survives_project_roundtrip(tmp_path):
    document = Document(30, 20, transparent=True)
    gradient = default_gradient((255, 0, 0, 255))
    gradient.update(stop=[0, 0, 255, 100], midpoint=.5)
    document.add_object(PaintObject("rectangle", [(2, 2), (22, 12)], color=(0, 0, 0, 255),
                                    filled=True, fill_color=(255, 0, 0, 255), fill_gradient=gradient))
    layer = document.layers[0]
    assert layer.image.getpixel((8, 7))[0] > layer.image.getpixel((15, 7))[0]
    path = tmp_path / "gradient.painter"
    document.save_project(path)
    reopened = Document.load_project(path)
    assert reopened.layers[0].objects[0].fill_gradient == gradient
    assert reopened.layers[0].image.tobytes() == layer.image.tobytes()


def test_color_dialog_exposes_gradient_option():
    app = QApplication.instance() or QApplication([])
    dialog = ColorDialog((20, 40, 60, 200))
    assert dialog.gradient_spec() is None
    dialog.gradient_enabled.setChecked(True)
    assert dialog.gradient_spec()["mode"] == "edge"
    dialog.close()


def test_custom_template_trims_canvas_and_preserves_child_sizes(tmp_path):
    document = Document(300, 200, transparent=True)
    document.add_object(PaintObject("rectangle", [(100, 70), (180, 120)],
                                    (0, 0, 0, 255), size=4))
    document.add_object(PaintObject("text", [(110, 80), (170, 110)],
                                    (0, 0, 0, 255), text="Field", font_size=16))
    template = template_from_document(document, "My_object")
    assert template.name == "My_object"
    assert template.width < 100 and template.height < 70
    library = CustomLibrary(tmp_path)
    library.add(template)
    reopened = CustomLibrary(tmp_path).templates[template.template_id]
    assert len(reopened.children) == 2
    instance = reopened.instantiate(10, 10)
    instance.points[1] = (10 + reopened.width*2, 10 + reopened.height*2)
    target = Document(300, 200, transparent=True)
    target.add_object(instance)
    stored = target.layers[0].objects[0]
    assert stored.children[0].size == 4
    assert stored.children[1].font_size == 16
    path = tmp_path / "nested.painter"
    target.save_project(path)
    nested = Document.load_project(path).layers[0].objects[0]
    assert nested.template_name == "My_object"
    assert len(nested.children) == 2
    assert nested.children[1].text == "Field"
    assert nested.native_size == (reopened.width, reopened.height)


def test_custom_library_ranked_rail_and_gallery(tmp_path):
    library = CustomLibrary(tmp_path)
    assert {"Service", "Database", "Sensor", "Requirement"}.issubset(
        {item.name for item in library.templates.values()})
    sensor = next(item for item in library.templates.values() if item.name == "Sensor")
    library.record_use(sensor.template_id)
    assert library.ranked()[0].name == "Sensor"
    popular, remainder = library.gallery()
    assert popular[0].name == "Sensor"
    assert [item.name for item in remainder] == sorted(item.name for item in remainder)
    assert CustomLibrary(tmp_path).templates[sensor.template_id].uses == 1


def test_custom_swatch_edit_recolors_linked_objects_and_undo(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(40, 30, transparent=True))
    old, new = (25, 50, 75, 255), (100, 150, 200, 255)
    window.add_custom_color(old)
    window.select_custom_color(0)
    window.add_object(PaintObject("brush", [(5, 5)], old, 3))
    window.set_background_color(old, window.custom_color_ids[0])
    window.add_object(PaintObject("rectangle", [(8, 8), (20, 20)], (0, 0, 0, 255), 2,
                                  True, fill_color=old))
    assert window.document.layers[0].objects[0].color_ref == window.custom_color_ids[0]
    assert window.document.layers[0].objects[1].fill_color_ref == window.custom_color_ids[0]

    class AcceptedDialog:
        def __init__(self, *args, **kwargs):
            pass
        def exec(self):
            return QDialog.DialogCode.Accepted
        def rgba(self):
            return new

    monkeypatch.setattr("painter.app.ColorDialog", AcceptedDialog)
    window.edit_custom_color(0)
    assert window.custom_colors[0] == new
    assert window.document.layers[0].objects[0].color == new
    assert window.document.layers[0].objects[1].fill_color == new
    window.undo()
    assert window.custom_colors[0] == old
    assert window.document.layers[0].objects[0].color == old
    window.redo()
    assert window.custom_colors[0] == new
    window.dirty = False
    window.close()


def test_custom_history_child_can_edit_text(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.custom_library = CustomLibrary(tmp_path)
    window.refresh_custom_objects()
    window.replace_document(Document(180, 120, transparent=True))
    template = next(item for item in window.custom_library.templates.values() if item.name == "Service")
    window.arm_custom_template(template.template_id)
    window.place_custom_template((10, 10))
    assert window.document.layers[0].objects[0].kind == "custom"
    assert window.object_panel.history.count() == 3
    window.select_object((0, 1))
    assert window.selected_object().kind == "text"
    window.object_panel.text_edit.setPlainText("Gateway")
    assert window.document.layers[0].objects[0].children[1].text == "Gateway"
    assert window.selected_canvas_object().kind == "custom"
    window.dirty = False
    window.close()


def test_nested_custom_history_reaches_inner_text(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(160, 120, transparent=True))
    inner = PaintObject("custom", points=[(5, 5), (80, 45)], native_size=(75, 40),
                        template_name="Inner", children=[PaintObject(
                            "text", [(4, 4), (70, 35)], (0, 0, 0, 255), text="Inner text", font_size=14)])
    outer = PaintObject("custom", points=[(10, 10), (110, 90)], native_size=(100, 80),
                        template_name="Outer", children=[inner])
    window.document.add_object(outer)
    window.refresh()
    assert window.object_panel.history.count() == 3
    window.select_object((0, 0, 0))
    assert window.selected_object().text == "Inner text"
    window.object_panel.text_edit.setPlainText("Changed")
    assert window.document.layers[0].objects[0].children[0].children[0].text == "Changed"
    window.object_panel.toggle_custom((0, 0))
    assert window.object_panel.history.count() == 2
    window.object_panel.toggle_custom((0, 0))
    assert window.object_panel.history.count() == 3
    window.dirty = False
    window.close()


def test_custom_editor_saves_trimmed_history_to_library(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QInputDialog
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.custom_library = CustomLibrary(tmp_path)
    window.refresh_custom_objects()
    window.create_custom_object()
    editor = window.custom_editor
    assert editor.document.layers[0].image.getpixel((0, 0))[3] == 0
    editor.document.add_object(PaintObject("rectangle", [(200, 120), (300, 200)],
                                           (0, 0, 0, 255), 3))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args: ("My_object", True))
    window.save_custom_editor(editor)
    assert window.pending_custom_template_id is not None
    template = window.custom_library.templates[window.pending_custom_template_id]
    assert template.name == "My_object"
    assert template.width < 120 and template.height < 100
    assert len(template.children) == 1
    assert (tmp_path / f"{template.template_id}.painter").exists()
    window.dirty = False
    window.close()


def test_double_click_custom_swatch_opens_editor_and_recolors(monkeypatch):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.add_custom_color((10, 20, 30, 255))
    window.show()
    app.processEvents()

    class AcceptedDialog:
        def __init__(self, *args, **kwargs):
            pass
        def exec(self):
            return QDialog.DialogCode.Accepted
        def rgba(self):
            return (40, 50, 60, 255)

    monkeypatch.setattr("painter.app.ColorDialog", AcceptedDialog)
    QTest.mouseDClick(window.custom_swatch_buttons[0], Qt.MouseButton.LeftButton)
    assert window.custom_colors[0] == (40, 50, 60, 255)
    window.dirty = False
    window.close()


def test_custom_swatch_updates_linked_gradient_endpoint(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.replace_document(Document(30, 20, transparent=True))
    old, new = (200, 10, 10, 255), (10, 200, 10, 255)
    window.add_custom_color(old)
    spec = default_gradient(old)
    spec["start_ref"] = window.custom_color_ids[0]
    window.document.add_object(PaintObject("rectangle", [(1, 1), (21, 15)], (0, 0, 0, 255),
                                           filled=True, fill_color=old, fill_gradient=spec))

    class AcceptedDialog:
        def __init__(self, *args, **kwargs):
            pass
        def exec(self):
            return QDialog.DialogCode.Accepted
        def rgba(self):
            return new

    monkeypatch.setattr("painter.app.ColorDialog", AcceptedDialog)
    window.edit_custom_color(0)
    obj = window.document.layers[0].objects[0]
    assert obj.fill_gradient["start"] == list(new)
    window.dirty = False
    window.close()


def test_custom_gallery_tiles_align_and_dialogs_can_resize(tmp_path):
    app = QApplication.instance() or QApplication([])
    library = CustomLibrary(tmp_path)
    owner = QWidget()
    owner.resize(900, 700)
    owner.show()
    gallery = CustomObjectGallery(library, owner)
    gallery.show()
    app.processEvents()
    cards = gallery.findChildren(TemplateButton)
    assert len(cards) >= 8
    first_row = [card for card in cards if card.mapTo(gallery, card.rect().topLeft()).y() ==
                 cards[0].mapTo(gallery, cards[0].rect().topLeft()).y()]
    assert len(first_row) == 4
    first_of_second_section = cards[4]
    assert cards[0].mapTo(gallery, cards[0].rect().topLeft()).x() == \
           first_of_second_section.mapTo(gallery, first_of_second_section.rect().topLeft()).x()
    label_bottoms = [card.findChild(QLabel, "templateCaption").geometry().bottom()
                     for card in first_row]
    assert len(set(label_bottoms)) == 1
    dialogs = [gallery, ColorDialog((10, 20, 30, 255), owner),
               GradientDialog(default_gradient((10, 20, 30, 255)), owner)]
    for dialog in dialogs:
        dialog.show()
        app.processEvents()
        assert dialog.isSizeGripEnabled()
        assert dialog.parent() is None
        assert dialog.windowHandle().transientParent() is None
        assert dialog.windowFlags() & Qt.WindowType.WindowTitleHint
        assert dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
        initial = dialog.size()
        dialog.resize(initial.width() + 80, initial.height() + 50)
        dialog.move(100, 100)
        app.processEvents()
        assert dialog.width() > initial.width()
        assert dialog.height() > initial.height()
        assert dialog.pos().x() == 100
        assert dialog.pos().y() == 100
        dialog.close()
    owner.close()


def test_custom_library_edit_and_delete_survive_reload(tmp_path):
    library = CustomLibrary(tmp_path)
    original = next(item for item in library.templates.values() if item.name == "Service")
    library.record_use(original.template_id)
    revised = CustomTemplate("temporary", "Renamed service", 80, 45,
                             [PaintObject("rectangle", [(0, 0), (70, 35)], (10, 20, 30, 255))])
    library.replace(original.template_id, revised)
    restored = CustomLibrary(tmp_path).templates[original.template_id]
    assert (restored.name, restored.width, restored.height, restored.uses, restored.built_in) == \
           ("Renamed service", 80, 45, 1, True)
    assert restored.children[0].color == (10, 20, 30, 255)
    library.delete(original.template_id)
    assert original.template_id not in CustomLibrary(tmp_path).templates
    assert not (tmp_path / f"{original.template_id}.painter").exists()

    document = Document(100, 100, transparent=True)
    document.add_object(PaintObject("rectangle", [(10, 10), (50, 50)], (0, 0, 0, 255)))
    custom = template_from_document(document, "Own shape")
    library.add(custom)
    assert custom.template_id in CustomLibrary(tmp_path).templates
    library.delete(custom.template_id)
    assert custom.template_id not in CustomLibrary(tmp_path).templates
    assert not (tmp_path / f"{custom.template_id}.painter").exists()


def test_custom_gallery_menu_edits_and_deletes(monkeypatch, tmp_path):
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    library = CustomLibrary(tmp_path)
    template = next(item for item in library.templates.values() if item.name == "Service")
    gallery = CustomObjectGallery(library)
    gallery.show()
    app.processEvents()
    tile = next(item for item in gallery.findChildren(TemplateButton)
                if item.template_id == template.template_id)
    more = tile.findChild(QToolButton, "templateMenu")
    assert more is not None
    QTest.mouseClick(more, Qt.MouseButton.LeftButton)
    app.processEvents()
    gallery._tile_menu.actions()[0].trigger()
    assert gallery.result() == QDialog.DialogCode.Accepted
    assert (gallery.action, gallery.selected_id) == ("edit", template.template_id)

    gallery = CustomObjectGallery(library)
    gallery.show()
    app.processEvents()
    changed = []
    gallery.library_changed.connect(lambda: changed.append(True))
    tile = next(item for item in gallery.findChildren(TemplateButton)
                if item.template_id == template.template_id)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    QTest.mouseClick(tile.findChild(QToolButton, "templateMenu"), Qt.MouseButton.LeftButton)
    app.processEvents()
    gallery._tile_menu.actions()[1].trigger()
    assert changed == [True]
    assert template.template_id not in library.templates
    assert gallery.action is None
    gallery.close()


def test_edit_custom_object_loads_history_and_saves_same_definition(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.custom_library = CustomLibrary(tmp_path)
    window.refresh_custom_objects()
    template = next(item for item in window.custom_library.templates.values()
                    if item.name == "Database")
    old_count = len(template.children)
    window.edit_custom_object(template.template_id)
    editor = window.custom_editor
    assert len(editor.document.layers[0].objects) == old_count
    editor.document.add_object(PaintObject("line", [(5, 5), (25, 25)], (255, 0, 0, 255), 2))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Database edited", True))
    window.save_custom_editor(editor, template.template_id)
    saved = CustomLibrary(tmp_path).templates[template.template_id]
    assert saved.name == "Database edited"
    assert len(saved.children) == old_count + 1
    assert window.pending_custom_template_id == template.template_id
    window.dirty = False
    window.close()


def test_deleting_armed_custom_object_clears_pending_placement(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.custom_library = CustomLibrary(tmp_path)
    window.refresh_custom_objects()
    template = next(item for item in window.custom_library.templates.values()
                    if item.name == "Sensor")
    window.arm_custom_template(template.template_id)
    gallery = CustomObjectGallery(window.custom_library, window)
    gallery.library_changed.connect(window.refresh_after_custom_library_change)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    gallery.delete_template(template.template_id)
    assert window.pending_custom_template_id is None
    assert window.tool == "select"
    gallery.close()
    window.dirty = False
    window.close()


def test_custom_library_migrates_previous_app_name(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    previous_name = "AlphaPainter" if sys.platform == "win32" else "alpha-painter"
    legacy = tmp_path / previous_name / "custom-objects"
    previous = CustomLibrary(legacy)
    template = CustomTemplate("a" * 32, "Legacy symbol", 20, 20, [
        PaintObject("rectangle", [(2, 2), (18, 18)], (0, 0, 0, 255))])
    previous.add(template)
    current = CustomLibrary()
    current_name = "Painter" if sys.platform == "win32" else "painter"
    assert current.root == tmp_path / current_name / "custom-objects"
    assert current.templates[template.template_id].name == "Legacy symbol"
    assert (legacy / "index.json").exists()
