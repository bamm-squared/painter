# Contributing

Painter uses Python 3.10+, PySide6, and Pillow. Install the project with
`python -m pip install -e .`, then run `python -m pytest -q` before a pull
request. GUI tests use Qt's offscreen platform and do not need a desktop.

Keep drawing operations in `painter/objects.py` and document state in
`painter/document.py`. The Qt interface lives in `painter/app.py` and the
smaller `*_ui.py` modules. Add a focused test when changing project file
round trips, render order, or editable object behavior.

For packaging changes, build on the target OS with
`python scripts/build_portable.py` and run
`python scripts/smoke_portable.py PATH_TO_BINARY`. Windows and Linux
release binaries are built separately by GitHub Actions.
