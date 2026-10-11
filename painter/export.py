"""Image export formats available from the installed Pillow build."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image


PREFERRED_EXTENSIONS = {
    "PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "TIFF": ".tiff",
    "BMP": ".bmp", "GIF": ".gif", "AVIF": ".avif", "TGA": ".tga",
    "QOI": ".qoi", "JPEG2000": ".jp2", "ICO": ".ico", "PDF": ".pdf",
}
PREFERRED_ORDER = tuple(PREFERRED_EXTENSIONS)

# Formats outside this set receive a white backdrop before saving. Many encoders
# reject RGBA outright, while others silently drop its alpha channel.
ALPHA_FORMATS = {
    "PNG", "WEBP", "TIFF", "GIF", "AVIF", "TGA", "QOI", "JPEG2000",
    "ICO", "ICNS", "DDS",
}


def supported_formats() -> dict[str, tuple[str, ...]]:
    """Return formats that can save a regular RGBA or RGB painting here."""
    Image.init()
    extensions: dict[str, set[str]] = {}
    for extension, format_name in Image.registered_extensions().items():
        if format_name in Image.SAVE:
            extensions.setdefault(format_name, set()).add(extension)

    rgba = Image.new("RGBA", (32, 32), (100, 150, 200, 128))
    rgb = Image.new("RGB", (32, 32), (100, 150, 200))
    usable = {}
    for format_name, suffixes in extensions.items():
        sample = rgba if format_name in ALPHA_FORMATS else rgb
        try:
            sample.save(BytesIO(), format=format_name)
        except (OSError, ValueError, TypeError):
            continue
        usable[format_name] = tuple(sorted(suffixes))
    return usable


def export_filters(formats: dict[str, tuple[str, ...]]) -> tuple[str, dict[str, str]]:
    """Build the file dialog filters and their Pillow format names."""
    ordered = [name for name in PREFERRED_ORDER if name in formats]
    ordered.extend(sorted(name for name in formats if name not in PREFERRED_ORDER))
    filter_formats = {}
    for name in ordered:
        patterns = " ".join(f"*{extension}" for extension in formats[name])
        label = f"{name} image ({patterns})"
        filter_formats[label] = name
    return ";;".join(filter_formats), filter_formats


def export_target(filename: str, selected_filter: str,
                  formats: dict[str, tuple[str, ...]], filter_formats: dict[str, str]) -> tuple[Path, str]:
    """Resolve the selected format while honoring typed suffixes in the default PNG filter."""
    path = Path(filename)
    by_extension = {extension: name for name, extensions in formats.items() for extension in extensions}
    selected_format = filter_formats.get(selected_filter, "PNG")
    if path.suffix:
        format_name = by_extension.get(path.suffix.lower())
        if format_name is None:
            raise ValueError(f"No image exporter is available for {path.suffix} files")
        if selected_format != "PNG" and format_name != selected_format:
            extension = PREFERRED_EXTENSIONS.get(selected_format, formats[selected_format][0])
            return path.with_suffix(extension), selected_format
        return path, format_name
    extension = PREFERRED_EXTENSIONS.get(selected_format, formats[selected_format][0])
    return path.with_suffix(extension), selected_format


def save_image(image: Image.Image, path: Path, format_name: str) -> None:
    if format_name not in ALPHA_FORMATS:
        flattened = Image.new("RGB", image.size, "white")
        flattened.paste(image, mask=image.getchannel("A"))
        image = flattened
    image.save(path, format=format_name)
