"""Image and layer operations, independent of the user interface."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
from collections import deque
import zipfile

from PIL import Image

from .objects import PaintObject, apply_object, draw_round_stroke


@dataclass
class Layer:
    name: str
    image: Image.Image
    visible: bool = True
    opacity: int = 255
    base_image: Image.Image | None = None
    objects: list[PaintObject] | None = None

    def copy(self) -> Layer:
        return Layer(self.name, self.image.copy(), self.visible, self.opacity,
                     self.base_image.copy() if self.base_image is not None else None,
                     [obj.copy() for obj in self.objects] if self.objects is not None else None)


class Document:
    def __init__(self, width: int = 800, height: int = 600, transparent: bool = False):
        self.width = width
        self.height = height
        self.grid_spacing = 20
        background = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
        self.layers = [Layer("Background", Image.new("RGBA", (width, height), background))]
        self.active = 0

    def copy(self) -> Document:
        other = Document.__new__(Document)
        other.width, other.height = self.width, self.height
        other.grid_spacing = self.grid_spacing
        other.layers = [layer.copy() for layer in self.layers]
        other.active = self.active
        return other

    def add_layer(self, name: str | None = None, opaque: bool = True) -> None:
        """Every added layer is above every existing layer."""
        name = name or f"Layer {len(self.layers) + 1}"
        color = (255, 255, 255, 255) if opaque else (0, 0, 0, 0)
        self.layers.append(Layer(name, Image.new("RGBA", (self.width, self.height), color)))
        self.active = len(self.layers) - 1

    def reorder_layers(self, order: list[int]) -> None:
        """Apply a left-to-right, bottom-to-top order while keeping the same active layer."""
        if sorted(order) != list(range(len(self.layers))):
            raise ValueError("Invalid layer order")
        active_layer = self.layers[self.active]
        self.layers = [self.layers[index] for index in order]
        self.active = next(index for index, layer in enumerate(self.layers) if layer is active_layer)

    def delete_layer(self) -> None:
        if len(self.layers) == 1:
            self.layers[0].image = Image.new("RGBA", (self.width, self.height))
            self.layers[0].base_image = None
            self.layers[0].objects = None
            return
        self.layers.pop(self.active)
        self.active = min(self.active, len(self.layers) - 1)

    def move_layer(self, direction: int) -> bool:
        target = self.active + direction
        if not 0 <= target < len(self.layers):
            return False
        self.layers[self.active], self.layers[target] = self.layers[target], self.layers[self.active]
        self.active = target
        return True

    def add_object(self, obj: PaintObject, layer_index: int | None = None) -> None:
        layer = self.layers[self.active if layer_index is None else layer_index]
        if layer.base_image is None:
            layer.base_image = layer.image.copy()
            layer.objects = []
        layer.objects.append(obj.copy())
        layer.image = apply_object(layer.image, obj)

    def rebuild_layer(self, layer_index: int | None = None) -> None:
        layer = self.layers[self.active if layer_index is None else layer_index]
        if layer.objects is None:
            return
        image = layer.base_image.copy()
        for obj in layer.objects:
            image = apply_object(image, obj)
        layer.image = image

    def delete_object(self, index: int, layer_index: int | None = None) -> None:
        layer = self.layers[self.active if layer_index is None else layer_index]
        layer.objects.pop(index)
        self.rebuild_layer(layer_index)

    def move_object(self, index: int, target: int, layer_index: int | None = None) -> None:
        layer = self.layers[self.active if layer_index is None else layer_index]
        obj = layer.objects.pop(index)
        layer.objects.insert(target, obj)
        self.rebuild_layer(layer_index)

    def composite(self, preview: Image.Image | None = None, erase_mask: Image.Image | None = None,
                  through_index: int | None = None,
                  erase_color: tuple[int, int, int, int] = (0, 0, 0, 0)) -> Image.Image:
        result = Image.new("RGBA", (self.width, self.height))
        for index, layer in enumerate(self.layers):
            if through_index is not None and index > through_index:
                break
            if not layer.visible:
                continue
            pixels = layer.image
            if index == self.active and (preview is not None or erase_mask is not None):
                pixels = pixels.copy()
                if erase_mask is not None:
                    pixels.paste(erase_color, (0, 0), erase_mask)
                if preview is not None:
                    pixels = Image.alpha_composite(pixels, preview)
            if layer.opacity != 255:
                pixels = pixels.copy()
                pixels.putalpha(pixels.getchannel("A").point(lambda a: a * layer.opacity // 255))
            result = Image.alpha_composite(result, pixels)
        return result

    def flood_fill(self, point: tuple[int, int], color: tuple[int, int, int, int], tolerance: int = 0,
                   color_ref: str | None = None, gradient: dict | None = None) -> bool:
        x, y = point
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        image = self.layers[self.active].image
        source = image.getpixel((x, y))
        if source == color and gradient is None:
            return False
        # Compare against an unchanged copy so the fill never leaks through newly painted pixels.
        original = image.copy()
        source_pixels = original.load()
        mask = Image.new("L", image.size)
        mask_pixels = mask.load()
        visited = bytearray(self.width * self.height)
        queue = deque([(x, y)])
        changed = False
        while queue:
            px, py = queue.popleft()
            offset = py * self.width + px
            if visited[offset]:
                continue
            visited[offset] = 1
            if max(abs(source_pixels[px, py][i] - source[i]) for i in range(4)) > tolerance:
                continue
            mask_pixels[px, py] = 255
            changed = True
            if px > 0:
                queue.append((px - 1, py))
            if px + 1 < self.width:
                queue.append((px + 1, py))
            if py > 0:
                queue.append((px, py - 1))
            if py + 1 < self.height:
                queue.append((px, py + 1))
        if changed:
            self.add_object(PaintObject("fill", color=color, mask=mask,
                                        color_ref=color_ref, gradient=gradient))
        return changed

    def resize_canvas(self, width: int, height: int) -> None:
        for layer in self.layers:
            new_image = Image.new("RGBA", (width, height))
            new_image.paste(layer.image, (0, 0))
            layer.image = new_image
            if layer.base_image is not None:
                new_base = Image.new("RGBA", (width, height))
                new_base.paste(layer.base_image, (0, 0))
                layer.base_image = new_base
            for obj in layer.objects or []:
                if obj.mask is not None:
                    new_mask = Image.new("L", (width, height))
                    new_mask.paste(obj.mask, (0, 0))
                    obj.mask = new_mask
        self.width, self.height = width, height

    def scale_objects(self, factor: float) -> None:
        """Scale editable artwork around the canvas origin without resizing the canvas."""
        if factor <= 0:
            raise ValueError("Scale factor must be positive")
        dimensions = (self.width, self.height)
        for index, layer in enumerate(self.layers):
            for obj in layer.objects or []:
                obj.points = [(x * factor, y * factor) for x, y in obj.points]
                obj.size = max(1, round(obj.size * factor))
                obj.font_size = max(1, round(obj.font_size * factor))
                obj.arrow_width *= factor
                obj.tangents = [tuple(value * factor for value in tangent) for tangent in obj.tangents]
                if obj.mask is not None:
                    scaled = obj.mask.resize((max(1, round(self.width * factor)),
                                              max(1, round(self.height * factor))), Image.Resampling.NEAREST)
                    clipped = Image.new("L", dimensions)
                    clipped.paste(scaled, (0, 0))
                    obj.mask = clipped
            self.rebuild_layer(index)

    def crop(self, box: tuple[int, int, int, int]) -> None:
        left, top, right, bottom = box
        if not (0 <= left < right <= self.width and 0 <= top < bottom <= self.height):
            raise ValueError("Invalid crop rectangle")
        for layer in self.layers:
            layer.image = layer.image.crop(box)
            if layer.base_image is not None:
                layer.base_image = layer.base_image.crop(box)
            for obj in layer.objects or []:
                obj.points = [(x - left, y - top) for x, y in obj.points]
                if obj.mask is not None:
                    obj.mask = obj.mask.crop(box)
        self.width, self.height = right - left, bottom - top

    def save_project(self, path: str | Path) -> None:
        def encoded_png(image: Image.Image) -> bytes:
            data = BytesIO()
            image.save(data, format="PNG")
            return data.getvalue()

        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            def encode_object(obj: PaintObject, key: str) -> dict:
                entry = obj.as_dict()
                if obj.mask is not None:
                    entry["mask_file"] = f"masks/{key}.png"
                    archive.writestr(entry["mask_file"], encoded_png(obj.mask))
                if obj.bitmap is not None:
                    entry["bitmap_file"] = f"bitmaps/{key}.png"
                    archive.writestr(entry["bitmap_file"], encoded_png(obj.bitmap))
                entry["children"] = [encode_object(child, f"{key}_{index}")
                                     for index, child in enumerate(obj.children)]
                return entry

            layers = []
            for index, layer in enumerate(self.layers):
                entry = {"name": layer.name, "visible": layer.visible, "opacity": layer.opacity,
                         "file": f"layers/{index}.png",
                         "base_file": f"layers/{index}_base.png" if layer.base_image is not None else None,
                         "objects": [encode_object(obj, f"{index}_{j}")
                                     for j, obj in enumerate(layer.objects or [])]}
                layers.append(entry)
                archive.writestr(entry["file"], encoded_png(layer.image))
                if layer.base_image is not None:
                    archive.writestr(entry["base_file"], encoded_png(layer.base_image))
            metadata = {"format": "painter-project", "version": 4,
                        "width": self.width, "height": self.height,
                        "grid_spacing": self.grid_spacing, "active": self.active,
                        "layers": layers}
            archive.writestr("project.json", json.dumps(metadata, indent=2))

    @classmethod
    def load_project(cls, path: str | Path) -> Document:
        with zipfile.ZipFile(path) as archive:
            metadata = json.loads(archive.read("project.json"))
            if metadata.get("format") != "painter-project" or metadata.get("version") not in (1, 2, 3, 4):
                raise ValueError("Unsupported project format")
            width, height = int(metadata["width"]), int(metadata["height"])
            if not (1 <= width <= 10000 and 1 <= height <= 10000):
                raise ValueError("Invalid canvas dimensions")
            entries = metadata["layers"]
            if not entries or len(entries) > 1000:
                raise ValueError("Invalid layer list")
            document = cls(width, height, transparent=True)
            document.grid_spacing = max(2, min(512, int(metadata.get("grid_spacing", 20))))
            document.layers = []
            for entry in entries:
                with Image.open(BytesIO(archive.read(entry["file"]))) as source:
                    image = source.convert("RGBA")
                if image.size != (width, height):
                    raise ValueError("Layer size differs from canvas")
                base = None
                if entry.get("base_file"):
                    with Image.open(BytesIO(archive.read(entry["base_file"]))) as source:
                        base = source.convert("RGBA")
                    if base.size != (width, height):
                        raise ValueError("Layer base size differs from canvas")
                objects = None
                if "objects" in entry:
                    objects = []
                    def decode_object(item: dict, depth: int = 0) -> PaintObject:
                        if depth > 16:
                            raise ValueError("Custom object nesting is too deep")
                        mask = None
                        if item.get("mask_file"):
                            with Image.open(BytesIO(archive.read(item["mask_file"]))) as source:
                                mask = source.convert("L")
                            if mask.size != (width, height) and depth == 0:
                                raise ValueError("Object mask size differs from canvas")
                        bitmap = None
                        if item.get("bitmap_file"):
                            with Image.open(BytesIO(archive.read(item["bitmap_file"]))) as source:
                                bitmap = source.convert("RGBA")
                        children = [decode_object(child, depth+1) for child in item.get("children", [])]
                        return PaintObject.from_dict(item, mask, bitmap, children)
                    for item in entry["objects"]:
                        objects.append(decode_object(item))
                    if objects and base is None:
                        raise ValueError("Objects require a layer base image")
                    if not objects and base is None:
                        objects = None
                document.layers.append(Layer(str(entry["name"]), image, bool(entry["visible"]),
                                             max(0, min(255, int(entry["opacity"]))), base, objects))
            document.active = max(0, min(len(document.layers) - 1, int(metadata["active"])))
            return document

    @classmethod
    def from_image(cls, path: str | Path) -> Document:
        with Image.open(path) as source:
            image = source.convert("RGBA")
        document = cls(*image.size, transparent=True)
        document.layers[0] = Layer("Image", image)
        return document


def draw_stroke(mask: Image.Image, points: list[tuple[int, int]], size: int) -> None:
    """Draw a round, continuous stroke into an L or RGBA image."""
    draw_round_stroke(mask, points, size)
