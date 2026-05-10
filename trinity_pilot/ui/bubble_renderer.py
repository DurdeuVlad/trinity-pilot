from __future__ import annotations

import html

_DOMAIN_COLORS: dict[str, tuple[str, str]] = {
    "cli": ("#E3F2FD", "#1565C0"),
    "browser": ("#E8F5E9", "#2E7D32"),
    "desktop": ("#FCE4EC", "#C62828"),
}
_DOMAIN_DEFAULT = ("#F3E5F5", "#6A1B9A")


def _esc(text: str) -> str:
    return html.escape(str(text))


def user_bubble(text: str) -> str:
    """Right-aligned user message bubble."""
    return (
        "<div style='"
        "text-align:right;"
        "margin:6px 4px 6px 60px;"
        "'>"
        "<span style='"
        "display:inline-block;"
        "background:#FF6347;"
        "color:white;"
        "padding:8px 14px;"
        "border-radius:16px 16px 4px 16px;"
        "font-size:13px;"
        "line-height:1.4;"
        f"'>{_esc(text)}</span>"
        "</div>"
    )


def ai_bubble(text: str) -> str:
    """Left-aligned AI message bubble."""
    return (
        "<div style='"
        "text-align:left;"
        "margin:6px 60px 2px 4px;"
        "'>"
        "<span style='"
        "display:inline-block;"
        "background:#F5F5F5;"
        "color:#212121;"
        "padding:8px 14px;"
        "border-radius:16px 16px 16px 4px;"
        "border-left:3px solid #FF6347;"
        "font-size:13px;"
        "line-height:1.4;"
        f"'>{_esc(text)}</span>"
        "</div>"
    )


def objectives_card(specs: list[dict]) -> str:
    """Numbered objectives list formatted as a card."""
    rows = ""
    for i, spec in enumerate(specs, 1):
        domain = spec.get("domain", "cli")
        obj_id = _esc(spec.get("objective_id", f"objective_{i}"))
        description = _esc(spec.get("description", spec.get("objective_id", "")))
        bg, fg = _DOMAIN_COLORS.get(domain, _DOMAIN_DEFAULT)
        badge = (
            f"<span style='background:{bg};color:{fg};"
            f"padding:1px 7px;border-radius:10px;font-size:11px;"
            f"font-weight:600;margin-right:6px;'>{_esc(domain)}</span>"
        )
        rows += (
            f"<div style='padding:5px 0;border-bottom:1px solid #EEEEEE;'>"
            f"<b style='color:#FF6347;'>{i}.</b> {badge}"
            f"<b>{obj_id}</b><br/>"
            f"<span style='color:#555;font-size:12px;padding-left:18px;'>{description}</span>"
            f"</div>"
        )

    return (
        "<div style='"
        "margin:8px 4px;"
        "background:#FFFDE7;"
        "border:1px solid #FFC107;"
        "border-radius:8px;"
        "padding:10px 14px;"
        "'>"
        "<div style='font-weight:700;color:#E65100;margin-bottom:6px;font-size:13px;'>"
        "📋 Planned Objectives"
        "</div>"
        f"{rows}"
        "</div>"
    )


def confirmation_prompt() -> str:
    """AI confirmation request after objectives card."""
    return ai_bubble(
        "Ready to run these objectives? "
        "Type \u2018yes\u2019 to start, \u2018no\u2019 to cancel, "
        "or describe what you\u2019d like to change."
    )


def summary_bubble(elapsed_s: float, status: str, results: dict) -> str:
    """Completion summary bubble."""
    total = len(results)
    passed = sum(1 for v in results.values() if v.get("status") == "passed")
    failed = total - passed

    if status == "completed":
        color = "#E8F5E9"
        border = "#4CAF50"
        icon = "\u2705"
        msg = f"All {total} objective{'s' if total != 1 else ''} completed successfully in {elapsed_s:.1f}s."
    elif status == "cancelled":
        color = "#FFF3E0"
        border = "#FF9800"
        icon = "\u23F9"
        msg = "Task was cancelled."
    else:
        color = "#FFEBEE"
        border = "#F44336"
        icon = "\u274C"
        msg = f"{passed}/{total} objectives passed. {failed} failed after {elapsed_s:.1f}s."

    return (
        "<div style='"
        f"background:{color};"
        f"border-left:4px solid {border};"
        "border-radius:4px;"
        "margin:8px 4px;"
        "padding:10px 14px;"
        "font-size:13px;"
        "'>"
        f"{icon} <b>{msg}</b>"
        "</div>"
    )


def debug_block(label: str, content: str) -> str:
    """Monospace debug JSON block."""
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
        f"<b style='color:#FFD54F;'>{_esc(label)}</b><br/>"
        f"{_esc(content)}"
        "</div>"
    )


def system_note(text: str) -> str:
    """Subtle system/info note line."""
    return (
        "<div style='"
        "text-align:center;"
        "color:#9E9E9E;"
        "font-size:11px;"
        "margin:4px 0;"
        f"'>{_esc(text)}</div>"
    )
