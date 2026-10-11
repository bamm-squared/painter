"""Regenerate the README screenshot with a disposable sample document."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from painter.app import MainWindow
from painter.document import Document
from painter.objects import PaintObject


def main() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="painter-screenshot-") as data_dir:
        os.environ["XDG_DATA_HOME"] = data_dir
        window = MainWindow()
        document = Document(900, 600)
        document.add_layer("Diagram", opaque=False)
        navy = (36, 48, 76, 255)
        blue = (78, 112, 214, 255)
        document.add_object(PaintObject("rectangle", [(68, 177), (824, 361)],
                                        (116, 137, 196, 180), size=2))
        document.add_object(PaintObject("text", [(52, 39), (780, 89)], navy, text="Architecture sketch", font_size=31))
        document.add_object(PaintObject("text", [(54, 93), (835, 120)], (91, 108, 137, 255),
                                        text="A small diagram built from reusable, editable objects", font_size=16))
        document.add_object(PaintObject("arrow", [(250, 287), (360, 287)], blue, size=4))
        document.add_object(PaintObject("arrow", [(525, 287), (640, 287)], blue, size=4))
        names = (("Service", 90, 244), ("Message Queue", 360, 244), ("Database", 640, 244))
        for name, x, y in names:
            template = next(item for item in window.custom_library.templates.values() if item.name == name)
            document.add_object(template.instantiate(x, y))
        document.add_object(PaintObject("text", [(93, 405), (820, 445)], navy,
                                        text="Strokes, text, geometry and render order stay editable.", font_size=19))
        window.replace_document(document)
        window.resize(1560, 960)
        window.show()
        window.select_object(0)
        app.processEvents()
        output = Path(__file__).resolve().parents[1] / "docs" / "screenshot.png"
        window.grab().save(str(output))
        window.dirty = False
        window.close()
        print(output)


if __name__ == "__main__":
    main()
