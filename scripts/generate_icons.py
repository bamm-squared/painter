"""Regenerate the PNG and Windows ICO from the source SVG."""

from pathlib import Path
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main() -> None:
    QGuiApplication.instance() or QGuiApplication([])
    asset_dir = Path(__file__).resolve().parents[1] / "painter" / "assets"
    renderer = QSvgRenderer(str(asset_dir / "painter.svg"))
    if not renderer.isValid():
        raise ValueError("Invalid Painter SVG icon")
    image = QImage(512, 512, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, 512, 512))
    painter.end()
    image.save(str(asset_dir / "painter.png"))
    with Image.open(asset_dir / "painter.png") as icon:
        icon.save(asset_dir / "painter.ico", sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])


if __name__ == "__main__":
    main()
