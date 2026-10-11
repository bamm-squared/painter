"""Canvas grid snapping and optional raster export overlay."""

from PIL import Image, ImageDraw


def snap_point(point: tuple[int, int], spacing: int,
               dimensions: tuple[int, int]) -> tuple[int, int]:
    return tuple(min(limit - 1, max(0, (coordinate + spacing // 2) // spacing * spacing))
                 for coordinate, limit in zip(point, dimensions))


def add_grid(image: Image.Image, spacing: int) -> Image.Image:
    overlay = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(overlay)
    ink = (80, 91, 110, 112)
    for x in range(0, image.width, spacing):
        draw.line((x, 0, x, image.height - 1), fill=ink)
    for y in range(0, image.height, spacing):
        draw.line((0, y, image.width - 1, y), fill=ink)
    return Image.alpha_composite(image.convert("RGBA"), overlay)
