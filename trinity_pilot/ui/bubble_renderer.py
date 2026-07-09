from __future__ import annotations

import html

# Light mode domain badge colors  (bg, fg)
_DOMAIN_COLORS: dict[str, tuple[str, str]] = {
    "cli": ("#E3F2FD", "#1565C0"),
    "browser": ("#E8F5E9", "#2E7D32"),
    "desktop": ("#FCE4EC", "#C62828"),
}
_DOMAIN_DEFAULT = ("#F3E5F5", "#6A1B9A")

# Dark mode domain badge colors  (bg, fg)
_DOMAIN_COLORS_DARK: dict[str, tuple[str, str]] = {
    "cli": ("#1A2C3D", "#64B5F6"),
    "browser": ("#1A2E1A", "#81C784"),
    "desktop": ("#3D1A1A", "#EF9A9A"),
}
_DOMAIN_DEFAULT_DARK = ("#2A1A3D", "#CE93D8")

# ---------------------------------------------------------------------------
# Theme color tables — all HTML hex tokens live here, NOT in function bodies
# ---------------------------------------------------------------------------

_LIGHT: dict[str, str] = {
    # user bubble
    "user_bg": "#FF6347",
    "user_fg": "#FFFFFF",
    # ai bubble
    "ai_bg": "#F5F5F5",
    "ai_fg": "#212121",
    "ai_accent": "#FF6347",
    # objectives card
    "card_bg": "#FFFDE7",
    "card_border": "#FFC107",
    "header_fg": "#E65100",
    "divider": "#EEEEEE",
    "desc_fg": "#555555",
    "obj_fg": "#212121",
    # summary bubble
    "summary_ok_bg": "#E8F5E9",
    "summary_cancel_bg": "#FFF3E0",
    "summary_fail_bg": "#FFEBEE",
    "summary_fg": "#212121",
    # summary borders (status-semantic, same in light/dark)
    "summary_ok_border": "#4CAF50",
    "summary_cancel_border": "#FF9800",
    "summary_fail_border": "#F44336",
    # system note
    "system_fg": "#9E9E9E",
    # execution row
    "exec_running_bg": "#E3F2FD",
    "exec_running_fg": "#1565C0",
    "exec_done_fg": "#2E7D32",
    "exec_failed_fg": "#C62828",
    "exec_pending_fg": "#757575",
}

_DARK: dict[str, str] = {
    # user bubble
    "user_bg": "#D84315",
    "user_fg": "#FFFFFF",
    # ai bubble
    "ai_bg": "#2A2A2A",
    "ai_fg": "#E0E0E0",
    "ai_accent": "#FF6347",
    # objectives card
    "card_bg": "#1E1A00",
    "card_border": "#7A5C00",
    "header_fg": "#FFD54F",
    "divider": "#333333",
    "desc_fg": "#AAAAAA",
    "obj_fg": "#E0E0E0",
    # summary bubble
    "summary_ok_bg": "#0D2010",
    "summary_cancel_bg": "#1E1500",
    "summary_fail_bg": "#2D0A0A",
    "summary_fg": "#E0E0E0",
    # summary borders (status-semantic, same in light/dark)
    "summary_ok_border": "#4CAF50",
    "summary_cancel_border": "#FF9800",
    "summary_fail_border": "#F44336",
    # system note
    "system_fg": "#757575",
    # execution row
    "exec_running_bg": "#1A2C3D",
    "exec_running_fg": "#64B5F6",
    "exec_done_fg": "#81C784",
    "exec_failed_fg": "#EF9A9A",
    "exec_pending_fg": "#9E9E9E",
}


def _esc(text: str) -> str:
    return html.escape(str(text))


def _px(n: int, scale: float) -> str:
    """Scale a pixel value and clamp to a readable minimum."""
    return f"{max(8, round(n * scale))}px"


def user_bubble(text: str, dark: bool = False, scale: float = 1.0) -> str:
    """Right-aligned user message bubble."""
    c = _DARK if dark else _LIGHT
    return (
        "<div style='"
        "text-align:right;"
        "margin:6px 4px 6px 60px;"
        "'>"
        "<span style='"
        "display:inline-block;"
        "max-width:88%;"
        "word-wrap:break-word;"
        "overflow-wrap:break-word;"
        "white-space:pre-wrap;"
        f"background:{c['user_bg']};"
        f"color:{c['user_fg']};"
        "padding:8px 14px;"
        "border-radius:16px 16px 4px 16px;"
        f"font-size:{_px(13, scale)};"
        "line-height:1.4;"
        f"'>{_esc(text)}</span>"
        "</div>"
    )


def ai_bubble(text: str, dark: bool = False, scale: float = 1.0) -> str:
    """Left-aligned AI message bubble."""
    c = _DARK if dark else _LIGHT
    return (
        "<div style='"
        "text-align:left;"
        "margin:6px 60px 2px 4px;"
        "'>"
        "<span style='"
        "display:inline-block;"
        "max-width:88%;"
        "word-wrap:break-word;"
        "overflow-wrap:break-word;"
        "white-space:pre-wrap;"
        f"background:{c['ai_bg']};"
        f"color:{c['ai_fg']};"
        "padding:8px 14px;"
        "border-radius:16px 16px 16px 4px;"
        f"border-left:3px solid {c['ai_accent']};"
        f"font-size:{_px(13, scale)};"
        "line-height:1.4;"
        f"'>{_esc(text)}</span>"
        "</div>"
    )


def objectives_card(specs: list[dict], dark: bool = False, scale: float = 1.0) -> str:
    """Numbered objectives list formatted as a card."""
    c = _DARK if dark else _LIGHT
    domain_map = _DOMAIN_COLORS_DARK if dark else _DOMAIN_COLORS
    domain_default = _DOMAIN_DEFAULT_DARK if dark else _DOMAIN_DEFAULT

    rows = ""
    for i, spec in enumerate(specs, 1):
        domain = spec.get("domain", "cli")
        obj_id = _esc(spec.get("objective_id", f"objective_{i}"))
        description = _esc(spec.get("goal", spec.get("description", spec.get("objective_id", ""))))
        bg, fg = domain_map.get(domain, domain_default)
        badge = (
            f"<span style='background:{bg};color:{fg};"
            f"padding:1px 7px;border-radius:10px;font-size:{_px(11, scale)};"
            f"font-weight:600;margin-right:6px;'>{_esc(domain)}</span>"
        )
        rows += (
            f"<div style='padding:5px 0;border-bottom:1px solid {c['divider']};'>"
            f"<b style='color:{c['ai_accent']};'>{i}.</b>&nbsp;{badge}&nbsp;"
            f"<b style='color:{c['obj_fg']};'>{obj_id}</b><br/>"
            f"<span style='color:{c['desc_fg']};font-size:{_px(12, scale)};margin-left:18px;'>{description}</span>"
            f"</div>"
        )

    return (
        "<div style='"
        "margin:8px 4px;"
        f"background:{c['card_bg']};"
        f"border:1px solid {c['card_border']};"
        "border-radius:8px;"
        "padding:10px 14px;"
        "'>"
        f"<div style='font-weight:700;color:{c['header_fg']};margin-bottom:6px;font-size:{_px(13, scale)};'>"
        "📋 Planned Objectives"
        "</div>"
        f"{rows}"
        "</div>"
    )



def summary_bubble(elapsed_s: float, status: str, results: dict, dark: bool = False, scale: float = 1.0) -> str:
    """Completion summary bubble."""
    c = _DARK if dark else _LIGHT
    total = len(results)
    passed = sum(1 for v in results.values() if v.get("status") == "passed")
    failed = sum(1 for v in results.values() if v.get("status") == "failed")
    not_run = sum(1 for v in results.values() if v.get("status") == "not_run")

    if status == "completed":
        color = c["summary_ok_bg"]
        border = c["summary_ok_border"]
        icon = "✅"
        msg = f"All {total} objective{'s' if total != 1 else ''} completed successfully in {elapsed_s:.1f}s."
    elif status == "cancelled":
        color = c["summary_cancel_bg"]
        border = c["summary_cancel_border"]
        icon = "⏹"
        msg = "Task was cancelled."
    else:
        color = c["summary_fail_bg"]
        border = c["summary_fail_border"]
        icon = "❌"
        msg = f"{passed}/{total} objectives passed. {failed} failed"
        if not_run:
            msg += f", {not_run} not run"
        msg += f" after {elapsed_s:.1f}s."

    divider = c["divider"]
    desc_fg = c["desc_fg"]
    rows = ""
    for obj_id, entry in results.items():
        s = entry.get("status", "unknown")
        row_icon = "✅" if s == "passed" else ("❌" if s == "failed" else "⏭")
        summary_text = (
            entry.get("summary", "")
            or entry.get("evidence", {}).get("worker_result_summary", "")
        )
        if len(summary_text) > 200:
            summary_text = summary_text[:197] + "…"
        detail = (
            f"<br/><span style='color:{desc_fg};margin-left:16px;'>"
            f"{_esc(summary_text)}</span>"
            if summary_text
            else ""
        )
        rows += (
            f"<div style='font-size:{_px(12, scale)};padding:3px 0;"
            f"border-top:1px solid {divider};margin-top:2px;'>"
            f"{row_icon} <b>{_esc(obj_id)}</b>{detail}</div>"
        )

    return (
        "<div style='"
        f"background:{color};"
        f"border-left:4px solid {border};"
        "border-radius:4px;"
        "margin:8px 4px;"
        "padding:10px 14px;"
        f"font-size:{_px(13, scale)};"
        f"color:{c['summary_fg']};"
        "'>"
        f"{icon} <b>{msg}</b>"
        f"{rows}"
        "</div>"
    )


def debug_block(label: str, content: str) -> str:
    """Monospace debug JSON block."""
    label_html = "<b style='color:" + _DARK["header_fg"] + ";'>" + _esc(label) + "</b><br/>"
    return (
        "<div style='"
        "background:#212121;"
        "color:#80CBC4;"
        "font-family:monospace;"
        "font-size:11px;"
        "padding:8px 10px;"
        "border-radius:4px;"
        "margin:4px 4px;"
        "white-space:pre-wrap;"
        "'>"
        + label_html
        + _esc(content)
        + "</div>"
    )


def system_note(text: str, dark: bool = False, scale: float = 1.0) -> str:
    """Subtle system/info note line."""
    c = _DARK if dark else _LIGHT
    return (
        "<div style='"
        "text-align:center;"
        f"color:{c['system_fg']};"
        f"font-size:{_px(11, scale)};"
        "margin:4px 0;"
        f"'>{_esc(text)}</div>"
    )


def welcome_bubble(dark: bool = False, scale: float = 1.0) -> str:
    """Centered onboarding message shown on launch."""
    c = _DARK if dark else _LIGHT
    return (
        "<div style='text-align:center;margin:24px 32px 8px 32px;'>"
        f"<div style='font-size:{_px(22, scale)};margin-bottom:8px;'>✈️</div>"
        f"<div style='font-weight:700;font-size:{_px(15, scale)};color:{c['ai_accent']};margin-bottom:6px;'>"
        "Trinity Pilot</div>"
        f"<div style='font-size:{_px(12, scale)};color:{c['system_fg']};line-height:1.6;'>"
        "Describe any desktop task and I'll break it into objectives and execute them.<br/>"
        "Type a task below to get started."
        "</div>"
        "</div>"
    )


def state_banner(label: str, color: str, dark: bool = False, scale: float = 1.0) -> str:
    """Centered state-transition banner (planning / executing)."""
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    bg = f"rgba({r},{g},{b},0.12)"
    border_color = f"rgba({r},{g},{b},0.35)"
    return (
        f"<div style='text-align:center;margin:6px 4px;padding:5px 12px;"
        f"border-radius:4px;background:{bg};border:1px solid {border_color};"
        f"font-size:{_px(11, scale)};color:{color};font-weight:600;letter-spacing:0.5px;'>"
        f"{label}</div>"
    )


def execution_row(
    label: str,
    status: str,
    indent_level: int = 0,
    dark: bool = False,
    scale: float = 1.0,
) -> str:
    """Compact inline execution step row with status indicator.

    Status values: "running", "done", "failed", "pending".
    Unknown statuses fall back to "pending" style.
    """
    c = _DARK if dark else _LIGHT
    padding_left = indent_level * 16

    _STATUS_ICONS = {
        "running": "⏳",  # hourglass / spinner-like
        "done": "✓",     # check mark
        "failed": "✗",   # ballot x
        "pending": "–",  # en-dash
    }
    _STATUS_FG_KEYS = {
        "running": "exec_running_fg",
        "done": "exec_done_fg",
        "failed": "exec_failed_fg",
        "pending": "exec_pending_fg",
    }

    icon = _STATUS_ICONS.get(status, _STATUS_ICONS["pending"])
    fg_key = _STATUS_FG_KEYS.get(status, "exec_pending_fg")
    fg = c[fg_key]

    # running gets a subtle background tint
    if status == "running":
        bg = c["exec_running_bg"]
        bg_style = f"background:{bg};"
    else:
        bg_style = ""

    return (
        f"<div style='"
        f"padding-left:{padding_left}px;"
        f"padding-top:2px;padding-bottom:2px;"
        f"font-size:{_px(12, scale)};"
        f"font-family:monospace;"
        f"{bg_style}"
        f"color:{fg};"
        f"'>"
        f"{icon}&nbsp;{_esc(label)}"
        f"</div>"
    )


def confirmation_prompt(dark: bool = False, scale: float = 1.0) -> str:
    """Inline prompt asking the user to confirm or cancel an action."""
    c = _DARK if dark else _LIGHT
    return (
        "<div style='"
        "text-align:center;"
        f"color:{c['system_fg']};"
        f"font-size:{_px(12, scale)};"
        "margin:6px 0;"
        "'>"
        "Proceed? — type <b>yes</b> to confirm or <b>no</b> to cancel."
        "</div>"
    )
