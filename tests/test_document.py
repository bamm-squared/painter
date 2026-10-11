from PIL import Image

from painter.document import Document, draw_stroke


def test_new_layers_are_above_previous_layers_and_alpha_reveals_below():
    document = Document(3, 3, transparent=True)
    document.layers[0].image.putpixel((1, 1), (255, 0, 0, 255))
    document.add_layer()
    document.layers[1].image.putpixel((1, 1), (0, 0, 255, 128))

    assert document.active == 1
    assert document.composite().getpixel((1, 1)) == (127, 0, 128, 255)
    assert document.composite().getpixel((0, 0)) == (255, 255, 255, 255)
    document.layers[1].image.putpixel((1, 1), (0, 0, 0, 0))
    assert document.composite().getpixel((1, 1)) == (255, 0, 0, 255)


def test_reordering_layers_changes_stacking_and_keeps_active_layer():
    document = Document(2, 2)
    document.add_layer("Blue")
    document.layers[1].image.putpixel((0, 0), (0, 0, 255, 255))
    active = document.layers[1]
    assert document.composite().getpixel((0, 0)) == (0, 0, 255, 255)

    document.reorder_layers([1, 0])

    assert document.active == 0
    assert document.layers[0] is active
    assert document.composite().getpixel((0, 0)) == (255, 255, 255, 255)
    assert document.composite(through_index=0).getpixel((0, 0)) == (0, 0, 255, 255)


def test_fill_can_replace_semitransparent_pixels_with_transparency():
    document = Document(4, 4, transparent=True)
    document.layers[0].image.paste((10, 20, 30, 128), (0, 0, 4, 4))
    document.layers[0].image.putpixel((3, 3), (255, 0, 0, 255))

    assert document.flood_fill((0, 0), (0, 0, 0, 0))
    assert document.layers[0].image.getpixel((2, 2)) == (0, 0, 0, 0)
    assert document.layers[0].image.getpixel((3, 3)) == (255, 0, 0, 255)


def test_project_roundtrip_keeps_order_visibility_opacity_and_pixels(tmp_path):
    document = Document(2, 2)
    document.add_layer("Glass")
    document.layers[1].image.putpixel((0, 0), (3, 4, 5, 77))
    document.layers[1].opacity = 190
    document.layers[0].visible = False
    path = tmp_path / "example.painter"

    document.save_project(path)
    reopened = Document.load_project(path)

    assert reopened.active == 1
    assert [layer.name for layer in reopened.layers] == ["Background", "Glass"]
    assert reopened.layers[0].visible is False
    assert reopened.layers[1].opacity == 190
    assert reopened.layers[1].image.getpixel((0, 0)) == (3, 4, 5, 77)


def test_crop_preserves_each_layer_separately():
    document = Document(4, 4, transparent=True)
    document.layers[0].image.putpixel((2, 2), (1, 2, 3, 255))
    document.add_layer()
    document.layers[1].image.putpixel((2, 2), (4, 5, 6, 127))

    document.crop((1, 1, 3, 3))

    assert (document.width, document.height) == (2, 2)
    assert document.layers[0].image.getpixel((1, 1)) == (1, 2, 3, 255)
    assert document.layers[1].image.getpixel((1, 1)) == (4, 5, 6, 127)


def test_one_pixel_pencil_dot_is_one_pixel():
    mask = Image.new("L", (5, 5))
    draw_stroke(mask, [(2, 2)], 1)
    assert sum(mask.histogram()[1:]) == 1


def test_grid_scaling_keeps_canvas_and_raster_base_and_moves_editable_masks():
    from painter.objects import PaintObject
    document = Document(40, 30, transparent=True)
    document.layers[0].image.putpixel((20, 10), (255, 0, 0, 255))
    document.add_layer("Mask", opaque=False)
    mask = Image.new("L", (40, 30))
    mask.putpixel((20, 10), 255)
    document.add_object(PaintObject("fill", color=(0, 0, 255, 255), mask=mask))
    document.scale_objects(1.5)
    assert (document.width, document.height) == (40, 30)
    assert document.layers[0].image.getpixel((20, 10)) == (255, 0, 0, 255)
    assert document.layers[1].objects[0].mask.size == (40, 30)
    assert document.layers[1].image.getpixel((30, 15)) == (0, 0, 255, 255)


def test_moved_selection_replays_earlier_history_and_roundtrips(tmp_path):
    from PIL import ImageDraw
    from painter.objects import PaintObject
    document = Document(30, 20, transparent=True)
    document.add_object(PaintObject("pencil", [(5, 5)], (255, 0, 0, 255), 1))
    mask = Image.new("L", (30, 20))
    ImageDraw.Draw(mask).rectangle((4, 4, 6, 6), fill=255)
    document.add_object(PaintObject("selection", points=[(13, 4), (16, 7)], mask=mask))
    assert document.layers[0].image.getpixel((5, 5))[3] == 0
    assert document.layers[0].image.getpixel((14, 5)) == (255, 0, 0, 255)
    document.layers[0].objects[0].color = (0, 0, 255, 255)
    document.rebuild_layer()
    assert document.layers[0].image.getpixel((14, 5)) == (0, 0, 255, 255)
    path = tmp_path / "selection.painter"
    document.save_project(path)
    reopened = Document.load_project(path)
    assert reopened.layers[0].image.getpixel((14, 5)) == (0, 0, 255, 255)
    reopened.layers[0].objects[0].points = [(6, 5)]
    reopened.rebuild_layer()
    assert reopened.layers[0].image.getpixel((15, 5)) == (0, 0, 255, 255)
