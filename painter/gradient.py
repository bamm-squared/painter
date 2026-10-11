"""Monotone RGBA gradients used by editable paint operations."""

from __future__ import annotations

from math import log

from PIL import Image


RGBA = tuple[int, int, int, int]


def default_gradient(start: RGBA) -> dict:
    return {"start": list(start), "stop": [255, 255, 255, start[3]],
            "midpoint": 0.5, "mode": "edge", "edge": "left",
            "point_x": 0.5, "point_y": 0.5, "snap_center": True}


def gradient_tile(size: tuple[int, int], spec: dict) -> Image.Image:
    """Render a gradient with its halfway color at the requested position."""
    width, height = size
    width, height = max(1, width), max(1, height)
    midpoint = max(0.001, min(0.999, float(spec.get("midpoint", 0.5))))
    power = log(0.5) / log(midpoint)
    if spec.get("mode") == "point":
        cx = (0.5 if spec.get("snap_center", True) else float(spec.get("point_x", 0.5))) * (width-1)
        cy = (0.5 if spec.get("snap_center", True) else float(spec.get("point_y", 0.5))) * (height-1)
        def ray_fraction(x: int, y: int) -> int:
            dx, dy = x-cx, y-cy
            x_limit = (width-1-cx) if dx >= 0 else cx
            y_limit = (height-1-cy) if dy >= 0 else cy
            fx = abs(dx)/x_limit if x_limit > 0 else (1 if dx else 0)
            fy = abs(dy)/y_limit if y_limit > 0 else (1 if dy else 0)
            return round(min(1, max(fx, fy))*255)
        values = bytes(ray_fraction(x, y) for y in range(height) for x in range(width))
    else:
        edge = spec.get("edge", "left")
        if edge in ("top", "bottom"):
            positions = [round((y / max(1, height-1) if edge == "top" else
                                (height-1-y)/max(1, height-1))*255) for y in range(height)]
            values = bytes(value for value in positions for _ in range(width))
        else:
            positions = [round((x / max(1, width-1) if edge == "left" else
                                (width-1-x)/max(1, width-1))*255) for x in range(width)]
            values = bytes(positions) * height
    position = Image.frombytes("L", (width, height), values)
    start = tuple(spec.get("start", (0, 0, 0, 255)))
    stop = tuple(spec.get("stop", (255, 255, 255, 255)))
    channels = [position.point([round(start[channel] + (stop[channel]-start[channel]) *
                                      (index/255)**power) for index in range(256)])
                for channel in range(4)]
    return Image.merge("RGBA", tuple(channels))


def gradient_canvas(dimensions: tuple[int, int], mask: Image.Image, spec: dict) -> Image.Image:
    result = Image.new("RGBA", dimensions)
    bounds = mask.getbbox()
    if bounds is not None:
        tile = gradient_tile((bounds[2]-bounds[0], bounds[3]-bounds[1]), spec)
        result.paste(tile, bounds[:2])
    return result
