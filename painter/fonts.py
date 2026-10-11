"""Resolve editable text fonts on Linux and Windows, with a bundled fallback."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import subprocess
import sys

from PIL import ImageFont


@lru_cache(maxsize=128)
def font_file_for_family(family: str, style: str = "Regular") -> str:
    if sys.platform == "win32":
        import winreg

        choices: list[tuple[int, str]] = []
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            with key:
                index = 0
                while True:
                    try:
                        label, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    name = label.split(" (")[0].casefold()
                    wanted = family.casefold()
                    if not (name == wanted or name.startswith(wanted + " ")) or not isinstance(value, str):
                        continue
                    path = Path(value)
                    if not path.is_absolute():
                        path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / path
                    if not path.is_file():
                        continue
                    desired_bold = "bold" in style.casefold()
                    desired_italic = "italic" in style.casefold() or "oblique" in style.casefold()
                    score = (name == wanted) * 4
                    score += ("bold" in name) == desired_bold
                    score += ("italic" in name or "oblique" in name) == desired_italic
                    choices.append((score, str(path)))
        return max(choices)[1] if choices else family
    if sys.platform.startswith("linux"):
        try:
            result = subprocess.run(
                ["fc-match", "-f", "%{file}", f"{family}:style={style}"],
                capture_output=True, text=True, check=True, timeout=5)
            if result.stdout.strip():
                return result.stdout.strip()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    return family


def load_font(path: str, size: int, family: str = "") -> ImageFont.FreeTypeFont:
    for candidate in (path, font_file_for_family(family) if family else "",
                      "DejaVuSans.ttf", "arial.ttf"):
        if candidate:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                pass
    return ImageFont.load_default(size=size)
