from __future__ import annotations

from pathlib import Path


def test_internal_visible_tool_modules_do_not_depend_on_hidden_adapters():
    root = Path(__file__).resolve().parents[1] / "tools"
    assert "BrowserAdapter" not in (root / "browser_tools.py").read_text(encoding="utf-8")
    assert "CLIAdapter" not in (root / "cli_tools.py").read_text(encoding="utf-8")
    assert "DesktopAdapter" not in (root / "desktop_tools.py").read_text(encoding="utf-8")
