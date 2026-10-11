"""Build one executable for the current operating system."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import subprocess
import sys


def executable_name() -> str:
    system = {"Linux": "linux", "Windows": "windows"}.get(platform.system())
    if system is None:
        raise SystemExit("Portable builds are configured for Linux and Windows")
    architecture = platform.machine().lower()
    architecture = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(architecture, architecture)
    if architecture not in {"x86_64", "arm64"}:
        raise SystemExit(f"Unsupported architecture: {architecture}")
    return f"Painter-{system}-{architecture}"


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    icon = root / "painter" / "assets"
    name = executable_name()
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", name,
        "--distpath", str(root / "dist"),
        "--workpath", str(root / "build" / "pyinstaller"),
        "--specpath", str(root / "build" / "pyinstaller"),
        "--add-data", f"{icon / 'painter.png'}{os.pathsep}painter/assets",
    ]
    if sys.platform == "win32":
        command += ["--icon", str(icon / "painter.ico")]
    command.append(str(root / "main.py"))
    subprocess.run(command, cwd=root, check=True)
    binary = root / "dist" / (name + (".exe" if sys.platform == "win32" else ""))
    if not binary.is_file():
        raise SystemExit(f"Build did not produce {binary}")
    print(binary)


if __name__ == "__main__":
    main()
