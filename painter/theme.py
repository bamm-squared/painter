"""Complete light and dark palettes for both the editor and its dialogs."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


COLORS = {
    "dark": {
        "bg": "#171b24", "surface": "#222936", "input": "#1c2430",
        "raised": "#2b3545", "canvas": "#313a48", "text": "#edf1f8",
        "muted": "#aab5c9", "border": "#445064", "hover": "#354158",
        "active": "#33436b", "accent": "#8da0ff", "accent_border": "#748bed",
        "icon": "#c7d1e2", "selection_text": "#ffffff",
    },
    "light": {
        "bg": "#f5f7fb", "surface": "#ffffff", "input": "#ffffff",
        "raised": "#f0f3f9", "canvas": "#e9ecf2", "text": "#253146",
        "muted": "#63728a", "border": "#d7deea", "hover": "#e9edfa",
        "active": "#e7ebff", "accent": "#344cbd", "accent_border": "#9eacf5",
        "icon": "#566074", "selection_text": "#ffffff",
    },
}


def apply_theme(app: QApplication, theme: str) -> None:
    c = COLORS[theme]
    app.setProperty("painter_theme", theme)
    palette = QPalette()
    for role, value in (
        (QPalette.ColorRole.Window, c["bg"]),
        (QPalette.ColorRole.WindowText, c["text"]),
        (QPalette.ColorRole.Base, c["input"]),
        (QPalette.ColorRole.AlternateBase, c["raised"]),
        (QPalette.ColorRole.Text, c["text"]),
        (QPalette.ColorRole.Button, c["raised"]),
        (QPalette.ColorRole.ButtonText, c["text"]),
        (QPalette.ColorRole.Highlight, c["accent"]),
        (QPalette.ColorRole.HighlightedText, c["selection_text"]),
        (QPalette.ColorRole.ToolTipBase, c["surface"]),
        (QPalette.ColorRole.ToolTipText, c["text"]),
        (QPalette.ColorRole.PlaceholderText, c["muted"]),
    ):
        palette.setColor(role, QColor(value))
    app.setPalette(palette)
    style = """
QWidget { color: @TEXT@; }
QMainWindow, QDialog, QWidget#workspace { background-color: @BG@; }
QWidget#palette, QWidget#layerBar { background-color: @SURFACE@; }
QWidget#objectPanel { background-color: @SURFACE@; border-left: 1px solid @BORDER@; }
QScrollArea#objectDetailsScroll { background-color: @SURFACE@; }
QListWidget#objectHistory { color: @TEXT@; background: @INPUT@; border: 1px solid @BORDER@; border-radius: 6px; }
QWidget#palette { border-right: 1px solid @BORDER@; }
QWidget#layerBar { border-bottom: 1px solid @BORDER@; }
QLabel { color: @TEXT@; background: transparent; }
QLabel#sectionTitle { color: @MUTED@; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QMenuBar { background-color: @SURFACE@; color: @TEXT@; border-bottom: 1px solid @BORDER@; padding: 4px; }
QMenuBar::item { color: @TEXT@; padding: 5px 10px; border-radius: 5px; }
QMenuBar::item:selected { background-color: @HOVER@; }
QMenu { background-color: @SURFACE@; color: @TEXT@; border: 1px solid @BORDER@; padding: 5px; }
QMenu::item { color: @TEXT@; padding: 6px 24px; }
QMenu::item:selected { background-color: @ACTIVE@; color: @ACCENT@; }
QMenu::separator { height: 1px; background: @BORDER@; margin: 5px 8px; }
QToolButton { color: @TEXT@; }
QToolButton#toolButton { border: 1px solid transparent; border-radius: 9px; background: transparent; }
QToolButton#toolButton:hover { background: @HOVER@; border-color: @BORDER@; }
QToolButton#toolButton:checked { background: @ACTIVE@; border-color: @ACCENT_BORDER@; }
QToolButton#toolModeButton { color: @MUTED@; background: @RAISED@; border: 1px solid @BORDER@; border-radius: 5px; padding: 0; }
QToolButton#toolModeButton:hover { color: @TEXT@; background: @HOVER@; border-color: @ACCENT_BORDER@; }
QToolButton#swatchButton { border: 2px solid transparent; border-radius: 6px; background: transparent; padding: 2px; }
QToolButton#swatchButton:hover { border-color: @MUTED@; }
QToolButton#swatchButton[selected="true"] { border-color: @ACCENT@; }
QToolButton#currentColor { color: @TEXT@; background: @RAISED@; border: 1px solid @BORDER@; border-radius: 9px; padding: 7px; text-align: left; }
QToolButton#currentColor:hover { border-color: @ACCENT_BORDER@; }
QToolButton#smallButton { color: @TEXT@; border: 1px solid @BORDER@; border-radius: 7px; background: @SURFACE@; padding: 5px; }
QToolButton#smallButton:hover { background: @HOVER@; border-color: @ACCENT_BORDER@; }
QToolButton#templateMenu { color: @TEXT@; background: @SURFACE@; border: 1px solid @BORDER@; border-radius: 5px; padding: 0; }
QToolButton#templateMenu:hover { background: @HOVER@; border-color: @ACCENT_BORDER@; }
QTabBar::tab { background: @RAISED@; color: @MUTED@; border: 1px solid @BORDER@;
               border-bottom: none; padding: 8px 13px; margin-right: 5px; border-top-left-radius: 7px; border-top-right-radius: 7px; }
QTabBar::tab:selected { background: @ACTIVE@; color: @ACCENT@; border-color: @ACCENT_BORDER@; font-weight: 600; }
QTabBar::tab:hover:!selected { background: @HOVER@; color: @TEXT@; }
QSpinBox, QComboBox, QLineEdit, QTextEdit, QPlainTextEdit { color: @TEXT@; background: @INPUT@;
    border: 1px solid @BORDER@; border-radius: 6px; padding: 5px; selection-background-color: @ACCENT@; }
QComboBox QAbstractItemView { color: @TEXT@; background: @INPUT@; border: 1px solid @BORDER@; selection-background-color: @ACTIVE@; }
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button { background: @RAISED@; border: none; }
QPushButton { color: @TEXT@; background: @RAISED@; border: 1px solid @BORDER@; border-radius: 7px; padding: 7px 12px; }
QPushButton:hover { background: @HOVER@; border-color: @ACCENT_BORDER@; }
QPushButton:disabled { color: @MUTED@; }
QCheckBox { color: @TEXT@; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid @BORDER@; border-radius: 3px; background: @INPUT@; }
QCheckBox::indicator:checked { background: @ACCENT@; border-color: @ACCENT@; image: none; }
QSlider::groove:horizontal { height: 8px; border-radius: 4px; background: @RAISED@; }
QSlider::sub-page:horizontal { background: @ACCENT@; border-radius: 4px; }
QSlider::handle:horizontal { background: @TEXT@; border: 2px solid @BORDER@; width: 16px; margin: -5px 0; border-radius: 9px; }
QStatusBar { color: @MUTED@; background: @SURFACE@; border-top: 1px solid @BORDER@; }
QScrollArea { background: @CANVAS@; border: none; }
QToolTip { color: @TEXT@; background: @SURFACE@; border: 1px solid @BORDER@; padding: 4px; }
QListWidget#layerStrip { color: @TEXT@; background: @SURFACE@; border: none; outline: none; }
"""
    for key, value in c.items():
        style = style.replace("@" + key.upper() + "@", value)
    app.setStyleSheet(style)
