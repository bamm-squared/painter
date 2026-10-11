"""Independent, movable dialogs for desktop window managers."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QDialog, QWidget


class IndependentDialog(QDialog):
    """Keep the visual owner without making the dialog an attached transient window."""

    def __init__(self, owner: QWidget | None = None):
        # A Qt parent sets WM_TRANSIENT_FOR. GNOME attaches modal transient
        # windows to their parent, so dragging their title bar moves Painter.
        super().__init__(None)
        self._owner_window = owner.window() if owner is not None else None
        self._positioned = False
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setSizeGripEnabled(True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._positioned or self._owner_window is None:
            return
        self._positioned = True
        center = self._owner_window.frameGeometry().center()
        frame = self.frameGeometry()
        self.move(QPoint(center.x() - frame.width() // 2,
                         center.y() - frame.height() // 2))
