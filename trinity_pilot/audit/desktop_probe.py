from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class DesktopProbeResult:
    passed: bool
    visible_text_match: bool
    screenshot_text_match: bool
    file_only_delivery: bool
    evidence_source: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def verify_visible_text(
    expected_text: str,
    *,
    uia_text: str = "",
    screenshot_text: str = "",
    file_paths: list[str | Path] | None = None,
    observed_actions: list[str] | None = None,
) -> DesktopProbeResult:
    expected = expected_text.strip()
    visible = bool(expected and expected in (uia_text or ""))
    screenshot = bool(expected and expected in (screenshot_text or ""))
    files = [Path(p) for p in file_paths or []]
    existing_files = [p for p in files if p.exists()]
    actions = [a.lower() for a in observed_actions or []]
    file_only = bool(existing_files) or any("write_file" in action or "wrote file" in action for action in actions)

    if visible:
        return DesktopProbeResult(True, True, screenshot, False, "uia_text", "Expected text is visible in UIA text")
    if screenshot:
        return DesktopProbeResult(True, False, True, False, "screenshot_text", "Expected text is visible in screenshot text")
    if file_only:
        return DesktopProbeResult(False, False, False, True, "file", "File-only delivery is insufficient for desktop typing proof")
    return DesktopProbeResult(False, False, False, False, "none", "No visible UI or screenshot-backed text evidence matched")


def probe_notepad_visible_text(expected_text: str, *, title_re: str = ".*Notepad.*") -> DesktopProbeResult:
    try:
        from pywinauto import Desktop

        windows = Desktop(backend="uia").windows(title_re=title_re)
        text = "\n".join(win.window_text() for win in windows)
        for win in windows:
            try:
                text += "\n" + "\n".join(child.window_text() for child in win.descendants())
            except Exception:
                continue
        return verify_visible_text(expected_text, uia_text=text)
    except Exception as exc:
        return DesktopProbeResult(False, False, False, False, "uia_error", f"UIA visible text probe failed: {exc}")
