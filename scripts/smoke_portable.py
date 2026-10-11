"""Launch a bundled Painter executable and verify its GUI initializes."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/smoke_portable.py PATH_TO_EXECUTABLE")
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise SystemExit(f"Missing executable: {executable}")
    with tempfile.TemporaryDirectory(prefix="painter-smoke-") as data_dir:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["XDG_DATA_HOME"] = data_dir
        environment["APPDATA"] = data_dir
        result = subprocess.run(
            [str(executable), "--smoke-test"], env=environment,
            capture_output=True, text=True, timeout=90, check=False)
    if result.returncode:
        raise SystemExit(
            f"Bundled Painter failed ({result.returncode})\n{result.stdout}\n{result.stderr}")
    print(f"Smoke test passed: {executable.name}")


if __name__ == "__main__":
    main()
