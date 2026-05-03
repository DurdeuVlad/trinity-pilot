"""Shared dark theme tokens and widget styles for unified-app."""
from __future__ import annotations

BG = "#0d1117"
APP_BG = BG
SURFACE = "#161b22"
SURFACE_ALT = "#1f2630"
SURFACE_SUBTLE = "#11161d"
USER_SURFACE = "#1b232d"
ASSISTANT_SURFACE = "#142326"
BORDER = "#30363d"
BORDER_STRONG = "#3b4654"
TEXT = "#cdd9e5"
TEXT_STRONG = "#f0f6fc"
TEXT_WEAK = "#8b949e"
MUTED = TEXT_WEAK
PLACEHOLDER = "#6e7681"
PRIMARY = "#58a6ff"
PRIMARY_HOVER = "#79b8ff"
SUCCESS = "#3fb950"
SUCCESS_FAINT = "#0f2a1a"
WARNING = "#d29922"
WARNING_FAINT = "#2a1e0a"
ERROR = "#f85149"
DANGER = ERROR
ERROR_FAINT = "#2a0f0f"
USER_ACCENT = "#ff9b5e"
ASSISTANT_ACCENT = "#56d4c0"


def primary_button_style() -> str:
    return (
        f"QPushButton {{"
        f"  background-color: {PRIMARY};"
        f"  color: #08131f;"
        f"  border: 1px solid {PRIMARY};"
        f"  border-radius: 8px;"
        f"  padding: 8px 16px;"
        f"  font-size: 12px;"
        f"  font-weight: 600;"
        f"}}"
        f"QPushButton:hover {{ background-color: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}"
        f"QPushButton:disabled {{ background-color: {BORDER}; color: {MUTED}; border-color: {BORDER}; }}"
    )


def primary_button_qss(color: str = PRIMARY, hover: str = PRIMARY_HOVER) -> str:
    return (
        f"QPushButton {{"
        f"  background-color: {color};"
        f"  color: #08131f;"
        f"  border: 1px solid {color};"
        f"  border-radius: 8px;"
        f"  padding: 8px 16px;"
        f"  font-size: 12px;"
        f"  font-weight: 600;"
        f"}}"
        f"QPushButton:hover {{ background-color: {hover}; border-color: {hover}; }}"
        f"QPushButton:disabled {{ background-color: {BORDER}; color: {MUTED}; border-color: {BORDER}; }}"
    )


def secondary_button_style() -> str:
    return (
        f"QPushButton {{"
        f"  background-color: {SURFACE_ALT};"
        f"  color: {TEXT};"
        f"  border: 1px solid {BORDER};"
        f"  border-radius: 8px;"
        f"  padding: 8px 14px;"
        f"  font-size: 12px;"
        f"}}"
        f"QPushButton:hover {{ border-color: {PRIMARY}; color: {TEXT_STRONG}; }}"
        f"QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background-color: {SURFACE}; }}"
    )


def secondary_button_qss() -> str:
    return secondary_button_style()


def chip_button_style() -> str:
    return (
        f"QPushButton {{"
        f"  background-color: {SURFACE};"
        f"  color: {TEXT};"
        f"  border: 1px solid {BORDER};"
        f"  border-radius: 14px;"
        f"  padding: 6px 10px;"
        f"  font-size: 11px;"
        f"}}"
        f"QPushButton:hover {{ border-color: {PRIMARY}; color: {TEXT_STRONG}; }}"
        f"QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}"
    )


def title_style(size: int = 16) -> str:
    return f"font-size: {size}px; font-weight: 700; color: {TEXT_STRONG};"


def section_style(size: int = 14) -> str:
    return f"font-size: {size}px; font-weight: 600; color: {TEXT};"


def muted_style(size: int = 12) -> str:
    return f"color: {MUTED}; font-size: {size}px;"


def text_input_style() -> str:
    return (
        f"QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{"
        f"  background-color: {SURFACE_SUBTLE};"
        f"  color: {TEXT};"
        f"  border: 1px solid {BORDER};"
        f"  border-radius: 10px;"
        f"  padding: 8px 10px;"
        f"  selection-background-color: {PRIMARY};"
        f"  selection-color: #08131f;"
        f"}}"
        f"QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{"
        f"  border-color: {PRIMARY};"
        f"}}"
        f"QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{"
        f"  color: {MUTED};"
        f"  background-color: {SURFACE};"
        f"}}"
    )


def surface_qss(
    object_name: str,
    *,
    surface: str = SURFACE,
    elevated: bool = False,
    border_top: bool = False,
    border_bottom: bool = False,
) -> str:
    radius = 12 if elevated else 10
    pieces = [
        f"QFrame#{object_name} {{",
        f"  background-color: {SURFACE_ALT if elevated else surface};",
        f"  border: 1px solid {BORDER};",
        f"  border-radius: {radius}px;",
    ]
    if border_top:
        pieces.append(f"  border-top: 1px solid {BORDER_STRONG};")
    if border_bottom:
        pieces.append(f"  border-bottom: 1px solid {BORDER_STRONG};")
    pieces.append("}")
    return "".join(pieces)


def card_qss(object_name: str, accent: str, surface: str) -> str:
    return (
        f"QFrame#{object_name} {{"
        f"  background-color: {surface};"
        f"  border: 1px solid {BORDER};"
        f"  border-left: 3px solid {accent};"
        f"  border-radius: 10px;"
        f"}}"
    )


def table_style() -> str:
    return (
        f"QTableWidget {{"
        f"  background-color: {SURFACE_SUBTLE};"
        f"  alternate-background-color: {SURFACE};"
        f"  color: {TEXT};"
        f"  border: 1px solid {BORDER};"
        f"  border-radius: 10px;"
        f"  gridline-color: {BORDER};"
        f"  selection-background-color: {SURFACE_ALT};"
        f"  selection-color: {TEXT_STRONG};"
        f"}}"
        f"QHeaderView::section {{"
        f"  background-color: {SURFACE_ALT};"
        f"  color: {TEXT_STRONG};"
        f"  border: none;"
        f"  border-right: 1px solid {BORDER};"
        f"  border-bottom: 1px solid {BORDER};"
        f"  padding: 8px;"
        f"  font-weight: 600;"
        f"}}"
        f"QTableCornerButton::section {{ background-color: {SURFACE_ALT}; border: none; }}"
    )


def dark_stylesheet() -> str:
    return app_stylesheet() + text_input_style() + primary_button_qss() + secondary_button_qss() + table_style()


def app_stylesheet() -> str:
    return (
        f"QWidget {{ background-color: {BG}; color: {TEXT}; font-family: 'Segoe UI', Arial, sans-serif; }}"
        f"QLabel {{ color: {TEXT}; }}"
        f"QTabWidget::pane {{ border: 1px solid {BORDER}; background: {BG}; }}"
        f"QTabBar::tab {{"
        f"  background: {SURFACE};"
        f"  color: {MUTED};"
        f"  border: 1px solid {BORDER};"
        f"  border-bottom: none;"
        f"  padding: 8px 14px;"
        f"  margin-right: 4px;"
        f"  border-top-left-radius: 8px;"
        f"  border-top-right-radius: 8px;"
        f"}}"
        f"QTabBar::tab:selected {{ background: {SURFACE_ALT}; color: {TEXT_STRONG}; }}"
        f"QTabBar::tab:hover:!selected {{ color: {TEXT}; }}"
        f"QSplitter::handle {{ background: {BORDER}; }}"
        f"QScrollBar:vertical {{ background: {SURFACE}; width: 10px; border-radius: 5px; }}"
        f"QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; min-height: 24px; border-radius: 5px; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}"
        f"QScrollBar:horizontal {{ background: {SURFACE}; height: 10px; border-radius: 5px; }}"
        f"QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; min-width: 24px; border-radius: 5px; }}"
        f"QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}"
    )
