"""Fail a release when its tag does not match the source version."""

import ast
from pathlib import Path
import sys
import tomllib


def source_version(root: Path) -> str:
    module = ast.parse((root / "painter" / "__init__.py").read_text())
    for statement in module.body:
        if (isinstance(statement, ast.Assign) and
                any(isinstance(target, ast.Name) and target.id == "__version__"
                    for target in statement.targets)):
            return ast.literal_eval(statement.value)
    raise ValueError("painter.__version__ is missing")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/check_release_tag.py vX.Y.Z")
    root = Path(__file__).resolve().parents[1]
    version = source_version(root)
    project = tomllib.loads((root / "pyproject.toml").read_text())
    if project["project"]["version"] != version:
        raise SystemExit("painter.__version__ and pyproject.toml disagree")
    expected = "v" + version
    if sys.argv[1] != expected:
        raise SystemExit(f"Tag {sys.argv[1]} must be {expected}")
    print(f"Release tag {expected} matches source")


if __name__ == "__main__":
    main()
