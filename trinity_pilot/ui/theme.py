"""
theme.py — Trinity Pilot design token system.

Single source of truth for all colors, spacing, and QSS strings.
Light-first; every token has a dark-mode pair.

Usage:
    from trinity_pilot.ui.theme import T, qss, apply_app_qss

    bg = T["surface"]          # light surface color
    bg_d = T["surface_dark"]   # dark surface color

    # Or resolve via helper:
    from trinity_pilot.ui.theme import tok
    bg = tok("surface", dark=False)
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Token table — every pair: ("light_value", "dark_value")
# ---------------------------------------------------------------------------
_TOKENS: dict[str, tuple[str, str]] = {
    # ── Backgrounds ──────────────────────────────────────────────────────
    "bg":              ("#F7F8FA", "#0D1117"),   # app background
    "surface":         ("#FFFFFF", "#161B22"),   # cards, panels
    "surface2":        ("#F2F3F5", "#21262D"),   # inset / input bg
    "surface3":        ("#E8EAED", "#30363D"),   # hover / subtle

    # ── Borders ──────────────────────────────────────────────────────────
    "border":          ("#E0E3E8", "#30363D"),
    "border_focus":    ("#FF6347", "#FF6347"),   # always brand orange

    # ── Text ─────────────────────────────────────────────────────────────
    "text":            ("#1C1C1E", "#E6EDF3"),
    "text_muted":      ("#6B7280", "#8B949E"),
    "text_dim":        ("#9CA3AF", "#6E7681"),

    # ── Brand / Accent ────────────────────────────────────────────────────
    "accent":          ("#FF6347", "#FF6347"),   # tomato — brand
    "accent_soft":     ("#FFF0ED", "#2D1510"),   # accent bg tint

    # ── State stripes (header top border) ────────────────────────────────
    "stripe_idle":     ("#E0E3E8", "#30363D"),   # subtle grey
    "stripe_planning": ("#FB923C", "#FB923C"),   # amber
    "stripe_clarify":  ("#34D399", "#34D399"),   # emerald
    "stripe_confirm":  ("#60A5FA", "#60A5FA"),   # sky blue
    "stripe_exec":     ("#A78BFA", "#A78BFA"),   # violet
    "stripe_done":     ("#4ADE80", "#4ADE80"),   # green
    "stripe_error":    ("#F87171", "#F87171"),   # red

    # ── Chat bubbles ─────────────────────────────────────────────────────
    "bubble_user_bg":  ("#FF6347", "#C0392B"),
    "bubble_user_fg":  ("#FFFFFF", "#FFFFFF"),
    "bubble_ai_bg":    ("#FFFFFF", "#21262D"),
    "bubble_ai_fg":    ("#1C1C1E", "#E6EDF3"),
    "bubble_sys_bg":   ("#F2F3F5", "#161B22"),
    "bubble_sys_fg":   ("#6B7280", "#8B949E"),

    # ── Input bar ────────────────────────────────────────────────────────
    "input_bg":        ("#FFFFFF", "#161B22"),
    "input_border":    ("#E0E3E8", "#30363D"),

    # State-colored input borders (same as stripes but lighter pair)
    "input_planning":  ("#FB923C", "#FB923C"),
    "input_clarify":   ("#34D399", "#34D399"),
    "input_confirm":   ("#60A5FA", "#60A5FA"),
    "input_exec":      ("#A78BFA", "#A78BFA"),
    "input_error":     ("#F87171", "#F87171"),

    # ── Chips ────────────────────────────────────────────────────────────
    "chip_pending_bg": ("#E8EAED", "#30363D"),
    "chip_pending_fg": ("#6B7280", "#8B949E"),
    "chip_run_bg":     ("#EFF6FF", "#1C2D40"),
    "chip_run_fg":     ("#1D4ED8", "#60A5FA"),
    "chip_run_border": ("#3B82F6", "#60A5FA"),
    "chip_done_bg":    ("#F0FDF4", "#162010"),
    "chip_done_fg":    ("#166534", "#4ADE80"),
    "chip_fail_bg":    ("#FFF1F2", "#2D1010"),
    "chip_fail_fg":    ("#991B1B", "#F87171"),

    # ── Confirm bar ──────────────────────────────────────────────────────
    "confirm_bg":      ("#EFF6FF", "#1C2D40"),
    "confirm_border":  ("#BFDBFE", "#1D4ED8"),

    # ── Buttons ──────────────────────────────────────────────────────────
    "btn_approve_bg":  ("#DCFCE7", "#14532D"),
    "btn_approve_fg":  ("#166534", "#4ADE80"),
    "btn_approve_brd": ("#86EFAC", "#16A34A"),
    "btn_reject_bg":   ("#FEF2F2", "#2D1010"),
    "btn_reject_fg":   ("#991B1B", "#F87171"),
    "btn_reject_brd":  ("#FECACA", "#DC2626"),
    "btn_edit_bg":     ("#F8FAFC", "#21262D"),
    "btn_edit_fg":     ("#374151", "#C9D1D9"),
    "btn_edit_brd":    ("#E0E3E8", "#30363D"),
    "btn_stop_bg":     ("#FEF2F2", "#2D1010"),
    "btn_stop_fg":     ("#991B1B", "#F87171"),
    "btn_stop_brd":    ("#FECACA", "#DC2626"),
}


def tok(name: str, dark: bool = False) -> str:
    """Resolve a token to its color string for the given mode."""
    pair = _TOKENS.get(name)
    if pair is None:
        raise KeyError(f"Unknown theme token: {name!r}")
    return pair[1] if dark else pair[0]


# ---------------------------------------------------------------------------
# Base application QSS  (applied once at startup, replaced on theme toggle)
# ---------------------------------------------------------------------------

def build_app_qss(dark: bool = False, scale: float = 1.0) -> str:
    t = lambda name: tok(name, dark)   # noqa: E731
    def px(n: int) -> str:             # noqa: E731
        return f"{max(8, round(n * scale))}px"
    return f"""
/* ── Base ─────────────────────────────────────────────── */
QWidget {{
    font-family: "Inter", "Segoe UI", system-ui, sans-serif;
    font-size: {px(13)};
    color: {t("text")};
    background: {t("bg")};
}}

/* ── Scroll bars ─────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t("border")};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t("text_muted")};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: {t("border")};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Text selection ──────────────────────────────────── */
QTextBrowser, QTextEdit, QLineEdit {{
    selection-background-color: {t("accent")};
    selection-color: #FFFFFF;
}}

/* ── Tool buttons ────────────────────────────────────── */
QToolButton {{
    border: none;
    background: transparent;
    border-radius: 6px;
    padding: 4px 6px;
    color: {t("text_muted")};
}}
QToolButton:hover {{
    background: {t("surface3")};
    color: {t("text")};
}}
QToolButton:checked {{
    background: {t("accent_soft")};
    color: {t("accent")};
}}

/* ── Message box ─────────────────────────────────────── */
QMessageBox {{
    background: {t("surface")};
}}
"""


def apply_app_qss(app: QApplication, dark: bool = False, scale: float = 1.0) -> None:
    """Apply base QSS and scaled font to the entire application."""
    from PySide6.QtGui import QFont
    font = QFont("Inter")
    font.setPixelSize(max(8, round(13 * scale)))
    app.setFont(font)
    app.setStyleSheet(build_app_qss(dark, scale))


# ---------------------------------------------------------------------------
# Per-state stripe/input color helpers
# ---------------------------------------------------------------------------

# Map ChatState.name → stripe token name
STATE_STRIPE: dict[str, str] = {
    "IDLE":                   "stripe_idle",
    "PLANNING":               "stripe_planning",
    "AWAITING_CLARIFICATION": "stripe_clarify",
    "AWAITING_CONFIRM":       "stripe_confirm",
    "EXECUTING":              "stripe_exec",
    "DONE":                   "stripe_done",
    "ERROR":                  "stripe_error",
}

STATE_INPUT_BORDER: dict[str, str] = {
    "IDLE":                   "input_border",
    "PLANNING":               "input_planning",
    "AWAITING_CLARIFICATION": "input_clarify",
    "AWAITING_CONFIRM":       "input_confirm",
    "EXECUTING":              "input_exec",
    "DONE":                   "input_border",
    "ERROR":                  "input_error",
}

STATE_PLACEHOLDER: dict[str, str] = {
    "IDLE":                   "Describe your task…",
    "PLANNING":               "Planning…",
    "AWAITING_CLARIFICATION": "Answer to clarify…",
    "AWAITING_CONFIRM":       "Type an amendment, or approve below…",
    "EXECUTING":              "Executing…",
    "DONE":                   "Describe your next task…",
    "ERROR":                  "Describe your task…",
}
