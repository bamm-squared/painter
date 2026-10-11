"""Reusable, editable groups of Painter operations."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from PIL import Image

from .document import Document
from .objects import PaintObject, object_mask


@dataclass
class CustomTemplate:
    template_id: str
    name: str
    width: int
    height: int
    children: list[PaintObject]
    uses: int = 0
    built_in: bool = False

    def instantiate(self, x: float, y: float) -> PaintObject:
        return PaintObject("custom", points=[(x, y), (x+self.width, y+self.height)],
                           children=[child.copy() for child in self.children],
                           template_name=self.name, template_id=self.template_id,
                           native_size=(self.width, self.height))

    def preview(self, size: tuple[int, int] = (96, 72)) -> Image.Image:
        from .objects import apply_object
        image = Image.new("RGBA", (self.width, self.height))
        for child in self.children:
            image = apply_object(image, child)
        image.thumbnail(size, Image.Resampling.LANCZOS)
        return image


def template_from_document(document: Document, name: str) -> CustomTemplate:
    """Collect visible layer histories and trim unused canvas space."""
    dimensions = (document.width, document.height)
    operations: list[PaintObject] = []
    bounds: tuple[int, int, int, int] | None = None

    def include(box: tuple[int, int, int, int] | None) -> None:
        nonlocal bounds
        if box is not None:
            bounds = box if bounds is None else (min(bounds[0], box[0]), min(bounds[1], box[1]),
                                                  max(bounds[2], box[2]), max(bounds[3], box[3]))

    for layer in document.layers:
        if not layer.visible:
            continue
        base = layer.base_image if layer.base_image is not None else (layer.image if layer.objects is None else None)
        if base is not None:
            extrema = base.getextrema()
            uniform_white = all(channel == (255, 255) for channel in extrema)
            if not uniform_white:
                box = base.getchannel("A").getbbox()
                if box is not None:
                    operations.append(PaintObject("image", points=[(0, 0), dimensions], bitmap=base.copy()))
                    include(box)
        for obj in layer.objects or []:
            if obj.kind != "cut":
                include(object_mask(obj, dimensions).getbbox())
            operations.append(obj.copy())
    if bounds is None:
        raise ValueError("Draw something before saving a custom object")
    left, top, right, bottom = bounds
    for obj in operations:
        obj.points = [(x-left, y-top) for x, y in obj.points]
        if obj.mask is not None:
            obj.mask = obj.mask.crop(bounds)
        if obj.kind == "image" and obj.bitmap is not None and obj.points[:2] == [(-left, -top),
                                                                                   (document.width-left, document.height-top)]:
            obj.bitmap = obj.bitmap.crop(bounds)
            obj.points = [(0, 0), (right-left, bottom-top)]
    return CustomTemplate(uuid4().hex, name.strip(), right-left, bottom-top, operations)


def _builtins() -> list[CustomTemplate]:
    outline = (88, 112, 153, 255)
    blue = (70, 111, 215, 255)
    green = (55, 150, 113, 255)
    orange = (194, 127, 52, 255)
    violet = (125, 93, 177, 255)
    text_color = (25, 38, 61, 255)

    def rectangle(name: str, width: int, height: int, border, fill, label: str) -> CustomTemplate:
        children = [PaintObject("rectangle", [(2, 2), (width-3, height-3)], border, 3,
                                True, fill_color=fill),
                    PaintObject("text", [(12, height/2-16), (width-12, height-8)],
                                text_color, text=label, font_size=17)]
        return CustomTemplate(f"builtin:{name.lower().replace(' ', '-')}", name,
                              width, height, children, built_in=True)

    service = rectangle("Service", 150, 82, blue, (228, 237, 255, 255), "Service")
    boundary = rectangle("System Boundary", 210, 135, outline, (245, 247, 251, 120), "System")
    requirement = rectangle("Requirement", 185, 92, orange, (255, 246, 228, 255), "REQ-001\nRequirement")
    controller = rectangle("Controller", 165, 88, violet, (242, 234, 255, 255), "Controller")
    external = rectangle("External System", 175, 88, outline, (236, 239, 245, 255), "External system")
    database = CustomTemplate("builtin:database", "Database", 150, 106, [
        PaintObject("rectangle", [(8, 20), (142, 88)], blue, 3, True, fill_color=(230, 240, 255, 255)),
        PaintObject("ellipse", [(8, 7), (142, 42)], blue, 3, True, fill_color=(230, 240, 255, 255)),
        PaintObject("arc", [(8, 70), (142, 105)], blue, 3, start_angle=0, end_angle=180),
        PaintObject("text", [(35, 44), (132, 80)], text_color, text="Database", font_size=16),
    ], built_in=True)
    queue = rectangle("Message Queue", 175, 88, green, (226, 247, 237, 255), "Message queue")
    sensor = CustomTemplate("builtin:sensor", "Sensor", 150, 95, [
        PaintObject("polygon", [(7, 82), (75, 4), (143, 82)], green, 3, True,
                    fill_color=(230, 250, 239, 255)),
        PaintObject("text", [(47, 52), (125, 86)], text_color, text="Sensor", font_size=16),
    ], built_in=True)
    actuator = rectangle("Actuator", 155, 86, green, (230, 250, 239, 255), "Actuator")
    interface = rectangle("Interface", 155, 72, orange, (255, 245, 226, 255), "Interface")
    return [service, database, queue, external, boundary, requirement, controller, sensor, actuator, interface]


class CustomLibrary:
    def __init__(self, root: Path | None = None):
        if root is not None:
            self.root = root
        elif sys.platform == "win32":
            data_home = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            self.root = data_home / "Painter" / "custom-objects"
            self._migrate_old_library(data_home / "AlphaPainter" / "custom-objects")
        else:
            data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            self.root = data_home / "painter" / "custom-objects"
            self._migrate_old_library(data_home / "alpha-painter" / "custom-objects")
        self.templates = {template.template_id: template for template in _builtins()}
        self.deleted_builtin_ids: set[str] = set()
        self._load()

    def _migrate_old_library(self, old_root: Path) -> None:
        if self.root.exists() or not old_root.is_dir():
            return
        try:
            shutil.copytree(old_root, self.root)
        except OSError:
            # A failed migration must not prevent the app from starting.
            pass

    def _load(self) -> None:
        index = self.root / "index.json"
        if not index.exists():
            return
        try:
            entries = json.loads(index.read_text())
            for item in entries:
                template_id = str(item["id"])
                if item.get("deleted"):
                    if template_id.startswith("builtin:"):
                        self.deleted_builtin_ids.add(template_id)
                        self.templates.pop(template_id, None)
                    continue
                existing = self.templates.get(template_id)
                if existing is None and (len(template_id) != 32 or
                                         any(character not in "0123456789abcdef" for character in template_id)):
                    continue
                uses = max(0, int(item.get("uses", 0)))
                path = self.root / f"{template_id}.painter"
                if path.exists():
                    document = Document.load_project(path)
                    children = document.layers[0].objects or []
                    self.templates[template_id] = CustomTemplate(
                        template_id, str(item["name"]), document.width, document.height,
                        [child.copy() for child in children], uses,
                        built_in=existing.built_in if existing is not None else False)
                elif existing is not None:
                    existing.uses = uses
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _write_index(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        entries = [{"id": item.template_id, "name": item.name, "uses": item.uses}
                   for item in self.templates.values()]
        entries.extend({"id": template_id, "deleted": True}
                       for template_id in sorted(self.deleted_builtin_ids))
        (self.root / "index.json").write_text(json.dumps(entries, indent=2))

    def add(self, template: CustomTemplate) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        document = Document(template.width, template.height, transparent=True)
        for child in template.children:
            document.add_object(child)
        document.save_project(self.root / f"{template.template_id}.painter")
        self.templates[template.template_id] = template
        self._write_index()

    def replace(self, template_id: str, updated: CustomTemplate) -> None:
        previous = self.templates[template_id]
        updated.template_id = template_id
        updated.uses = previous.uses
        updated.built_in = previous.built_in
        self.deleted_builtin_ids.discard(template_id)
        self.add(updated)

    def delete(self, template_id: str) -> None:
        template = self.templates.pop(template_id)
        if template.built_in:
            self.deleted_builtin_ids.add(template_id)
        try:
            self._write_index()
            (self.root / f"{template_id}.painter").unlink(missing_ok=True)
        except OSError:
            self.templates[template_id] = template
            self.deleted_builtin_ids.discard(template_id)
            raise

    def record_use(self, template_id: str) -> None:
        self.templates[template_id].uses += 1
        try:
            self._write_index()
        except OSError:
            # Keep the placement usable if the data directory is temporarily read-only.
            pass

    def ranked(self) -> list[CustomTemplate]:
        return sorted(self.templates.values(), key=lambda item: (-item.uses, item.name.casefold()))

    def gallery(self) -> tuple[list[CustomTemplate], list[CustomTemplate]]:
        popular = sorted(self.templates.values(), key=lambda item: (-item.uses, item.name.casefold()))[:4]
        remainder = sorted((item for item in self.templates.values() if item not in popular),
                           key=lambda item: item.name.casefold())
        return popular, remainder
