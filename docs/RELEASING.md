# Releasing Painter

The release workflow builds each one-file executable on its target OS.
PyInstaller does not cross-compile Windows executables from Linux.

1. Update `version` in `pyproject.toml` and `__version__` in
   `painter/__init__.py` to the same `X.Y.Z` value. Update `CHANGELOG.md`.
2. Run `python -m pytest -q` and, on your current OS,
   `python scripts/build_portable.py` followed by
   `python scripts/smoke_portable.py dist/Painter-...`.
3. Run `python scripts/check_release_tag.py vX.Y.Z`.
4. Commit and push the source to `main`. Push the matching tag:

   ```bash
   git tag vX.Y.Z
   git push origin main
   git push origin vX.Y.Z
   ```

The tag run tests and builds on Ubuntu 22.04 and Windows 2022 runners. It
smoke tests each bundled app, uploads the two binaries as workflow artifacts,
then publishes a release with both files and `SHA256SUMS`. GitHub automatically
provides source ZIP and tar archives for the tag. Inspect the workflow and
release page before sharing the downloads.

The Linux binary may require standard Qt/XCB libraries on the target desktop.
The Windows executable is unsigned until code signing is configured.
