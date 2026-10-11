"""Editable drawing operations, rendered in their history order."""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from math import atan2, cos, degrees, radians, sin, hypot, floor, ceil

from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

from .gradient import gradient_canvas
from .fonts import load_font


Point = tuple[float, float]
RGBA = tuple[int, int, int, int]


@dataclass
class PaintObject:
    kind: str
    points: list[Point] = field(default_factory=list)
    color: RGBA = (0, 0, 0, 255)
    size: int = 5
    filled: bool = False
    angle: float = 0.0
    arrow_width: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 180.0
    tangents: list[tuple[float, float, float, float]] = field(default_factory=list)
    text: str = ""
    font_family: str = "DejaVuSans.ttf"
    font_size: int = 24
    font_name: str = "DejaVu Sans"
    mask: Image.Image | None = None
    fill_color: RGBA | None = None
    bitmap: Image.Image | None = None
    flip_horizontal: bool = False
    flip_vertical: bool = False
    inverted: bool = False
    color_ref: str | None = None
    fill_color_ref: str | None = None
    gradient: dict | None = None
    fill_gradient: dict | None = None
    children: list[PaintObject] = field(default_factory=list)
    template_name: str = ""
    template_id: str = ""
    native_size: tuple[int, int] = (1, 1)

    def copy(self) -> PaintObject:
        return PaintObject(
            kind=self.kind, points=self.points.copy(), color=self.color, size=self.size,
            filled=self.filled, angle=self.angle, arrow_width=self.arrow_width,
            start_angle=self.start_angle, end_angle=self.end_angle,
            tangents=self.tangents.copy(), text=self.text, font_family=self.font_family,
            font_size=self.font_size, font_name=self.font_name,
            mask=self.mask.copy() if self.mask is not None else None,
            fill_color=self.fill_color,
            bitmap=self.bitmap.copy() if self.bitmap is not None else None,
            flip_horizontal=self.flip_horizontal, flip_vertical=self.flip_vertical,
            inverted=self.inverted, color_ref=self.color_ref,
            fill_color_ref=self.fill_color_ref, gradient=deepcopy(self.gradient),
            fill_gradient=deepcopy(self.fill_gradient),
            children=[child.copy() for child in self.children],
            template_name=self.template_name, template_id=self.template_id,
            native_size=self.native_size)

    def center(self) -> Point:
        if not self.points:
            return 0.0, 0.0
        if self.kind == "text" and len(self.points) == 1:
            return self.points[0]
        xs, ys = zip(*self.points)
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    def translated(self, dx: float, dy: float) -> None:
        self.points = [(x + dx, y + dy) for x, y in self.points]
        if self.mask is not None and self.kind != "selection":
            shifted = Image.new("L", self.mask.size)
            shifted.paste(self.mask, (round(dx), round(dy)))
            self.mask = shifted

    def handles(self) -> dict[str, Point]:
        if not self.points:
            return {}
        center = self.center()
        def turned(point: Point) -> Point:
            return rotate_point(point, center, self.angle)
        if self.kind in ("rectangle", "ellipse", "arc") and len(self.points) >= 2:
            (x0, y0), (x1, y1) = self.points[:2]
            left, right = sorted((x0, x1))
            top, bottom = sorted((y0, y1))
            if self.kind == "rectangle":
                result = {"nw": turned((left, top)), "ne": turned((right, top)),
                          "se": turned((right, bottom)), "sw": turned((left, bottom))}
            else:
                result = {"left": turned((left, center[1])),
                          "right": turned((right, center[1])),
                          "top": turned((center[0], top)),
                          "bottom": turned((center[0], bottom))}
                if self.kind == "arc":
                    rx, ry = (right-left)/2, (bottom-top)/2
                    for name, angle in (("arc_start", self.start_angle), ("arc_end", self.end_angle)):
                        theta = radians(angle)
                        result[name] = turned((center[0] + rx*cos(theta), center[1] + ry*sin(theta)))
            result["center"] = center
            result["rotate"] = turned((center[0], top - 26))
            return result
        if self.kind in ("text", "image", "selection", "custom") and len(self.points) >= 2:
            (x0, y0), (x1, y1) = self.points[:2]
            left, right = sorted((x0, x1))
            top, bottom = sorted((y0, y1))
            return {"nw": turned((left, top)), "ne": turned((right, top)),
                    "se": turned((right, bottom)), "sw": turned((left, bottom)),
                    "center": center, "rotate": turned((center[0], top - 26))}
        if self.kind == "arrow" and len(self.points) >= 2:
            start, end = [turned(point) for point in self.points[:2]]
            dx, dy = end[0]-start[0], end[1]-start[1]
            length = max(1, hypot(dx, dy))
            nx, ny = -dy/length, dx/length
            return {"start": start, "end": end,
                    "width": (center[0] + nx*max(self.arrow_width/2, 12),
                              center[1] + ny*max(self.arrow_width/2, 12)),
                    "center": center,
                    "rotate": (center[0] - nx*max(self.arrow_width/2+26, 30),
                               center[1] - ny*max(self.arrow_width/2+26, 30))}
        if self.kind == "line" and len(self.points) >= 2:
            return {"start": turned(self.points[0]), "end": turned(self.points[1])}
        if self.kind in ("polyline", "spline", "polygon"):
            result = {f"p{i}": turned(point) for i, point in enumerate(self.points)}
            if self.kind == "spline" and len(self.tangents) == len(self.points):
                for i, (point, tangent) in enumerate(zip(self.points, self.tangents)):
                    result[f"in{i}"] = turned((point[0]+tangent[0], point[1]+tangent[1]))
                    result[f"out{i}"] = turned((point[0]+tangent[2], point[1]+tangent[3]))
            result["center"] = center
            result["rotate"] = turned((center[0], min(p[1] for p in self.points) - 26))
            return result
        return {"center": center}

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "points": self.points, "color": self.color,
            "size": self.size, "filled": self.filled, "angle": self.angle,
            "arrow_width": self.arrow_width, "start_angle": self.start_angle,
            "end_angle": self.end_angle, "tangents": self.tangents,
            "text": self.text, "font_family": self.font_family, "font_size": self.font_size,
            "font_name": self.font_name, "fill_color": self.fill_color,
            "flip_horizontal": self.flip_horizontal, "flip_vertical": self.flip_vertical,
            "inverted": self.inverted, "color_ref": self.color_ref,
            "fill_color_ref": self.fill_color_ref,
            "gradient": deepcopy(self.gradient), "fill_gradient": deepcopy(self.fill_gradient),
            "template_name": self.template_name, "template_id": self.template_id,
            "native_size": self.native_size,
        }

    @classmethod
    def from_dict(cls, data: dict, mask: Image.Image | None = None,
                  bitmap: Image.Image | None = None,
                  children: list[PaintObject] | None = None) -> PaintObject:
        return cls(
            kind=str(data["kind"]),
            points=[(float(x), float(y)) for x, y in data.get("points", [])],
            color=tuple(data.get("color", (0, 0, 0, 255))),
            size=int(data.get("size", 5)), filled=bool(data.get("filled", False)),
            angle=float(data.get("angle", 0)), arrow_width=float(data.get("arrow_width", 0)),
            start_angle=float(data.get("start_angle", 0)), end_angle=float(data.get("end_angle", 180)),
            tangents=[tuple(map(float, tangent)) for tangent in data.get("tangents", [])],
            text=str(data.get("text", "")), font_family=str(data.get("font_family", "DejaVuSans.ttf")),
            font_size=int(data.get("font_size", 24)), font_name=str(data.get("font_name", "DejaVu Sans")),
            mask=mask,
            fill_color=tuple(data["fill_color"]) if data.get("fill_color") is not None else None,
            bitmap=bitmap, flip_horizontal=bool(data.get("flip_horizontal", False)),
            flip_vertical=bool(data.get("flip_vertical", False)),
            inverted=bool(data.get("inverted", False)),
            color_ref=data.get("color_ref"), fill_color_ref=data.get("fill_color_ref"),
            gradient=deepcopy(data.get("gradient")), fill_gradient=deepcopy(data.get("fill_gradient")),
            children=children or [], template_name=str(data.get("template_name", "")),
            template_id=str(data.get("template_id", "")),
            native_size=tuple(data.get("native_size", (1, 1))),
        )


def rotate_point(point: Point, center: Point, angle: float) -> Point:
    theta = radians(angle)
    dx, dy = point[0] - center[0], point[1] - center[1]
    return center[0] + dx * cos(theta) - dy * sin(theta), center[1] + dx * sin(theta) + dy * cos(theta)


def automatic_tangents(points: list[Point]) -> list[tuple[float, float, float, float]]:
    result = []
    for index, (x, y) in enumerate(points):
        before = points[max(0, index - 1)]
        after = points[min(len(points) - 1, index + 1)]
        dx, dy = (after[0] - before[0]) / 6, (after[1] - before[1]) / 6
        result.append((-dx, -dy, dx, dy))
    return result


def three_point_shape(kind: str, points: list[Point], color: RGBA, size: int,
                      filled: bool = False, fill_color: RGBA | None = None) -> PaintObject:
    """Construct a shape from an edge/axis and a third size or sweep point."""
    first, second, third = points[:3]
    dx, dy = second[0]-first[0], second[1]-first[1]
    length = max(0.001, hypot(dx, dy))
    nx, ny = -dy/length, dx/length
    if kind == "rectangle_3point":
        height = (third[0]-first[0])*nx + (third[1]-first[1])*ny
        cx = (first[0]+second[0])/2 + nx*height/2
        cy = (first[1]+second[1])/2 + ny*height/2
        return PaintObject("rectangle", [(cx-length/2, cy-abs(height)/2),
                                         (cx+length/2, cy+abs(height)/2)],
                           color, size, filled, angle=degrees(atan2(dy, dx)), fill_color=fill_color)
    if kind == "ellipse_3point":
        minor = abs((third[0]-first[0])*nx + (third[1]-first[1])*ny)
        return PaintObject("ellipse", [(first[0]-length, first[1]-minor),
                                       (first[0]+length, first[1]+minor)],
                           color, size, filled, angle=degrees(atan2(dy, dx)), fill_color=fill_color)
    if kind == "arrow_3point":
        middle = ((first[0]+second[0])/2, (first[1]+second[1])/2)
        width = 2*abs((third[0]-middle[0])*nx + (third[1]-middle[1])*ny)
        return PaintObject("arrow", [first, second], color, size, filled,
                           arrow_width=width, fill_color=fill_color)
    if kind == "arc_3point":
        ax, ay = first
        bx, by = second
        cx, cy = third
        determinant = 2*(ax*(by-cy) + bx*(cy-ay) + cx*(ay-by))
        if abs(determinant) < .001:
            return PaintObject("arc", [(min(ax,bx,cx), min(ay,by,cy)),
                                       (max(ax,bx,cx), max(ay,by,cy))], color, size)
        a2, b2, c2 = ax*ax+ay*ay, bx*bx+by*by, cx*cx+cy*cy
        ux = (a2*(by-cy) + b2*(cy-ay) + c2*(ay-by))/determinant
        uy = (a2*(cx-bx) + b2*(ax-cx) + c2*(bx-ax))/determinant
        radius = hypot(ax-ux, ay-uy)
        start = degrees(atan2(ay-uy, ax-ux)) % 360
        middle = degrees(atan2(by-uy, bx-ux)) % 360
        end = degrees(atan2(cy-uy, cx-ux)) % 360
        if (middle-start) % 360 > (end-start) % 360:
            start, end = end, start
        return PaintObject("arc", [(ux-radius, uy-radius), (ux+radius, uy+radius)],
                           color, size, start_angle=start, end_angle=end)
    raise ValueError(f"Unsupported three-point shape: {kind}")


def bezier_points(points: list[Point], tangents: list[tuple[float, float, float, float]]) -> list[Point]:
    if len(points) < 2:
        return points.copy()
    if len(tangents) != len(points):
        tangents = automatic_tangents(points)
    result: list[Point] = [points[0]]
    for index in range(len(points) - 1):
        p0, p3 = points[index], points[index + 1]
        outgoing = tangents[index]
        incoming = tangents[index + 1]
        p1 = p0[0] + outgoing[2], p0[1] + outgoing[3]
        p2 = p3[0] + incoming[0], p3[1] + incoming[1]
        steps = max(12, min(80, int(hypot(p3[0] - p0[0], p3[1] - p0[1]) / 3)))
        for step in range(1, steps + 1):
            t = step / steps
            u = 1 - t
            result.append((u**3 * p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0],
                           u**3 * p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]))
    return result


def wrapped_text_lines(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """Wrap at words when possible, otherwise at characters; never clip vertically."""
    lines = []
    def fits(candidate: str) -> bool:
        return font.getlength(candidate) <= width and font.getbbox(candidate)[2] <= width

    for paragraph in text.expandtabs(4).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        remaining = paragraph
        while remaining:
            if fits(remaining):
                lines.append(remaining)
                break
            fitting = 0
            for index in range(1, len(remaining) + 1):
                if not fits(remaining[:index]):
                    break
                fitting = index
            if fitting == 0:
                lines.append(remaining[0])
                remaining = remaining[1:]
                continue
            break_at = remaining.rfind(" ", 0, fitting + 1)
            if break_at > 0:
                lines.append(remaining[:break_at].rstrip())
                remaining = remaining[break_at:].lstrip(" ")
            else:
                lines.append(remaining[:fitting])
                remaining = remaining[fitting:]
    return lines


def draw_round_stroke(mask: Image.Image, points: list[Point], size: int) -> None:
    """Rasterize strokes at four times resolution for even width at any angle."""
    if not points:
        return
    if mask.mode != "L" or size <= 1:
        draw = ImageDraw.Draw(mask)
        ink = 255 if mask.mode == "L" else (255, 255, 255, 255)
        if len(points) > 1:
            draw.line(points, fill=ink, width=max(1, size), joint="curve")
        for x, y in points:
            draw.point((round(x), round(y)), fill=ink)
        return
    margin = size / 2 + 2
    left = max(0, floor(min(x for x, _ in points) - margin))
    top = max(0, floor(min(y for _, y in points) - margin))
    right = min(mask.width, ceil(max(x for x, _ in points) + margin + 1))
    bottom = min(mask.height, ceil(max(y for _, y in points) + margin + 1))
    if right <= left or bottom <= top:
        return
    scale = 4
    tile = Image.new("L", ((right - left) * scale, (bottom - top) * scale))
    draw = ImageDraw.Draw(tile)
    centers = [(round((x - left + .5) * scale), round((y - top + .5) * scale)) for x, y in points]
    if len(centers) > 1:
        draw.line(centers, fill=255, width=round(size * scale), joint="curve")
    radius = size * scale / 2
    for x, y in centers:
        draw.ellipse((round(x-radius), round(y-radius), round(x+radius), round(y+radius)), fill=255)
    smooth = tile.resize((right - left, bottom - top), Image.Resampling.LANCZOS)
    bounds = (left, top, right, bottom)
    mask.paste(ImageChops.lighter(mask.crop(bounds), smooth), (left, top))
    # Keep the solid center opaque; resampling can otherwise leave 254-alpha seams.
    core = ImageDraw.Draw(mask)
    if len(points) > 1:
        core.line(points, fill=255, width=max(1, size - 2), joint="curve")
    for x, y in points:
        core.point((round(x), round(y)), fill=255)


def image_overlay(obj: PaintObject, dimensions: tuple[int, int]) -> Image.Image:
    """Place a selected pixel region in its editable bounds, then rotate it."""
    overlay = Image.new("RGBA", dimensions)
    if obj.bitmap is None or len(obj.points) < 2:
        return overlay
    (x0, y0), (x1, y1) = obj.points[:2]
    left, top = round(min(x0, x1)), round(min(y0, y1))
    width, height = max(1, round(abs(x1-x0))), max(1, round(abs(y1-y0)))
    pixels = obj.bitmap.resize((width, height), Image.Resampling.BICUBIC)
    if obj.flip_horizontal:
        pixels = ImageOps.mirror(pixels)
    if obj.flip_vertical:
        pixels = ImageOps.flip(pixels)
    if obj.inverted:
        red, green, blue, alpha = pixels.split()
        pixels = Image.merge("RGBA", (ImageOps.invert(red), ImageOps.invert(green),
                                      ImageOps.invert(blue), alpha))
    overlay.paste(pixels, (left, top))
    if obj.angle:
        overlay = overlay.rotate(-obj.angle, resample=Image.Resampling.BICUBIC, center=obj.center())
    return overlay


def custom_overlay(obj: PaintObject, dimensions: tuple[int, int]) -> Image.Image:
    """Render children in parent bounds while retaining pen widths and font sizes."""
    overlay = Image.new("RGBA", dimensions)
    if len(obj.points) < 2:
        return overlay
    (x0, y0), (x1, y1) = obj.points[:2]
    left, top = min(x0, x1), min(y0, y1)
    sx = abs(x1-x0) / max(1, obj.native_size[0])
    sy = abs(y1-y0) / max(1, obj.native_size[1])
    for original in obj.children:
        child = original.copy()
        child.points = [(left+x*sx, top+y*sy) for x, y in child.points]
        child.tangents = [(a*sx, b*sy, c*sx, d*sy) for a, b, c, d in child.tangents]
        child.arrow_width *= (sx+sy)/2
        if child.mask is not None:
            scaled = child.mask.resize((max(1, round(obj.native_size[0]*sx)),
                                        max(1, round(obj.native_size[1]*sy))), Image.Resampling.NEAREST)
            mask = Image.new("L", dimensions)
            mask.paste(scaled, (round(left), round(top)))
            child.mask = mask
        overlay = apply_object(overlay, child)
    center = obj.center()
    if obj.flip_horizontal:
        overlay = overlay.transform(dimensions, Image.Transform.AFFINE,
                                    (-1, 0, 2*center[0], 0, 1, 0), resample=Image.Resampling.BICUBIC)
    if obj.flip_vertical:
        overlay = overlay.transform(dimensions, Image.Transform.AFFINE,
                                    (1, 0, 0, 0, -1, 2*center[1]), resample=Image.Resampling.BICUBIC)
    if obj.angle:
        overlay = overlay.rotate(-obj.angle, resample=Image.Resampling.BICUBIC, center=center)
    if obj.inverted:
        red, green, blue, alpha = overlay.split()
        overlay = Image.merge("RGBA", (ImageOps.invert(red), ImageOps.invert(green),
                                       ImageOps.invert(blue), alpha))
    return overlay


def object_mask(obj: PaintObject, dimensions: tuple[int, int], outline_only: bool = False) -> Image.Image:
    if obj.kind == "custom" and len(obj.points) >= 2:
        mask = Image.new("L", dimensions)
        (x0, y0), (x1, y1) = obj.points[:2]
        ImageDraw.Draw(mask).rectangle((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), fill=255)
        if obj.angle:
            mask = mask.rotate(-obj.angle, resample=Image.Resampling.BICUBIC, center=obj.center())
        return mask
    if obj.kind == "selection" and len(obj.points) >= 2:
        mask = Image.new("L", dimensions)
        (x0, y0), (x1, y1) = obj.points[:2]
        ImageDraw.Draw(mask).rectangle((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), fill=255)
        if obj.angle:
            mask = mask.rotate(-obj.angle, resample=Image.Resampling.BICUBIC, center=obj.center())
        return mask
    if obj.mask is not None:
        return obj.mask.copy()
    if obj.kind == "image":
        return image_overlay(obj, dimensions).getchannel("A")
    mask = Image.new("L", dimensions)
    draw = ImageDraw.Draw(mask)
    if not obj.points:
        return mask
    center = obj.center()
    points = [rotate_point(point, center, obj.angle) for point in obj.points]
    rounded = [(round(x), round(y)) for x, y in points]
    width = max(1, obj.size)
    if obj.kind in ("brush", "pencil", "eraser", "line", "polyline", "spline"):
        if obj.kind == "spline":
            points = bezier_points(obj.points, obj.tangents)
            rounded = [(round(x), round(y)) for x, y in (rotate_point(p, center, obj.angle) for p in points)]
        draw_round_stroke(mask, rounded, width)
    elif obj.kind in ("rectangle", "ellipse", "arc") and len(obj.points) >= 2:
        (x0, y0), (x1, y1) = obj.points[:2]
        box = (round(min(x0, x1)), round(min(y0, y1)), round(max(x0, x1)), round(max(y0, y1)))
        fill = 255 if obj.filled and obj.kind != "arc" and not outline_only else None
        if obj.kind == "rectangle":
            draw.rectangle(box, outline=255, fill=fill, width=width)
        elif obj.kind == "ellipse":
            draw.ellipse(box, outline=255, fill=fill, width=width)
        else:
            draw.arc(box, start=obj.start_angle, end=obj.end_angle, fill=255, width=width)
        if obj.angle:
            mask = mask.rotate(-obj.angle, resample=Image.Resampling.BICUBIC, center=center)
    elif obj.kind == "polygon" and len(rounded) >= 2:
        draw.polygon(rounded, fill=255 if obj.filled and not outline_only else None,
                     outline=255, width=width)
    elif obj.kind == "arrow" and len(points) >= 2:
        (sx, sy), (ex, ey) = points[:2]
        length = hypot(ex-sx, ey-sy)
        if length:
            ux, uy = (ex-sx)/length, (ey-sy)/length
            nx, ny = -uy, ux
            head_length = min(length * .5, max(width * 3, obj.arrow_width * 1.6, 10))
            head_half = max(width * 1.5, obj.arrow_width * 1.15, 5)
            base_x, base_y = ex - ux * head_length, ey - uy * head_length
            if obj.arrow_width <= 0:
                draw.line(((sx, sy), (ex, ey)), fill=255, width=width)
                draw.line(((base_x + nx*head_half, base_y + ny*head_half), (ex, ey),
                           (base_x - nx*head_half, base_y - ny*head_half)), fill=255, width=width)
            else:
                half = obj.arrow_width / 2
                polygon = [(sx+nx*half, sy+ny*half), (base_x+nx*half, base_y+ny*half),
                           (base_x+nx*head_half, base_y+ny*head_half), (ex, ey),
                           (base_x-nx*head_half, base_y-ny*head_half),
                           (base_x-nx*half, base_y-ny*half), (sx-nx*half, sy-ny*half)]
                if outline_only:
                    draw.line(polygon + [polygon[0]], fill=255, width=width, joint="curve")
                else:
                    draw.polygon(polygon, fill=255)
    elif obj.kind == "text":
        font = load_font(obj.font_family, obj.font_size, obj.font_name)
        if len(obj.points) >= 2:
            (x0, y0), (x1, y1) = obj.points[:2]
            left, top = round(min(x0, x1)), round(min(y0, y1))
            lines = wrapped_text_lines(obj.text, font, abs(x1 - x0))
            draw.multiline_text((left, top), "\n".join(lines), fill=255, font=font, spacing=4)
        else:
            draw.multiline_text(rounded[0], obj.text, fill=255, font=font, spacing=4)
        if obj.angle:
            mask = mask.rotate(-obj.angle, resample=Image.Resampling.BICUBIC, center=center)
    if obj.kind == "text" and (obj.flip_horizontal or obj.flip_vertical):
        cx, cy = obj.center()
        if obj.flip_horizontal:
            mask = mask.transform(dimensions, Image.Transform.AFFINE,
                                  (-1, 0, 2*cx, 0, 1, 0), resample=Image.Resampling.BICUBIC)
        if obj.flip_vertical:
            mask = mask.transform(dimensions, Image.Transform.AFFINE,
                                  (1, 0, 0, 0, -1, 2*cy), resample=Image.Resampling.BICUBIC)
    return mask


def apply_object(image: Image.Image, obj: PaintObject) -> Image.Image:
    if obj.kind == "custom":
        return Image.alpha_composite(image, custom_overlay(obj, image.size))
    if obj.kind == "selection" and obj.mask is not None:
        box = obj.mask.getbbox()
        if box is None:
            return image
        pixels = image.crop(box)
        pixels.putalpha(ImageChops.multiply(pixels.getchannel("A"), obj.mask.crop(box)))
        image.paste((0, 0, 0, 0), (0, 0), obj.mask)
        floating = PaintObject("image", points=obj.points, bitmap=pixels, angle=obj.angle,
                               flip_horizontal=obj.flip_horizontal, flip_vertical=obj.flip_vertical,
                               inverted=obj.inverted)
        return Image.alpha_composite(image, image_overlay(floating, image.size))
    if obj.kind == "image":
        return Image.alpha_composite(image, image_overlay(obj, image.size))
    mask = object_mask(obj, image.size)
    if obj.kind in ("eraser", "fill", "cut"):
        if obj.kind == "cut":
            image.paste((0, 0, 0, 0), (0, 0), mask)
        elif obj.gradient is not None:
            image.paste(gradient_canvas(image.size, mask, obj.gradient), (0, 0), mask)
        else:
            image.paste(obj.color, (0, 0), mask)
        return image
    if obj.filled and obj.fill_color is not None and obj.kind in ("rectangle", "ellipse", "polygon", "arrow"):
        fill = obj.fill_color
        if obj.inverted:
            fill = tuple(255-value for value in fill[:3]) + (fill[3],)
        if obj.fill_gradient is not None:
            image.paste(gradient_canvas(image.size, mask, obj.fill_gradient), (0, 0), mask)
        else:
            image.paste(fill, (0, 0), mask)
        mask = object_mask(obj, image.size, outline_only=True)
    rgb = tuple(255 - value for value in obj.color[:3]) if obj.inverted else obj.color[:3]
    if obj.gradient is not None:
        overlay = gradient_canvas(image.size, mask, obj.gradient)
        overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), mask))
    else:
        overlay = Image.new("RGBA", image.size, rgb + (0,))
        overlay.putalpha(mask.point(lambda value: value * obj.color[3] // 255))
    return Image.alpha_composite(image, overlay)


def object_label(obj: PaintObject) -> str:
    names = {"brush": "Brush stroke", "pencil": "Pencil stroke", "eraser": "Erasure",
             "fill": "Fill", "cut": "Cut", "rectangle": "Rectangle", "ellipse": "Oval",
             "polyline": "Polyline", "spline": "Spline", "polygon": "Polygon",
             "arrow": "Arrow", "arc": "Arc", "line": "Line", "text": "Text", "image": "Pasted pixels", "selection": "Moved selection"}
    suffix = f" · {obj.text[:18]}" if obj.kind == "text" and obj.text else ""
    if obj.kind == "custom":
        return obj.template_name or "Custom object"
    return names.get(obj.kind, obj.kind.capitalize()) + suffix
