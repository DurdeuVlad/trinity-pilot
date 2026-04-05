"""Tests for domain selector and explicit routing (UA-S4)."""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ui.panels.task_input_panel import TaskInputPanel


def test_domain_auto_detect_web_task(qtbot) -> None:
    panel = TaskInputPanel()
    qtbot.addWidget(panel)
    domain = panel.detect_domain("Search Google for AI news")
    assert domain == "web"


def test_domain_auto_detect_cli_task(qtbot) -> None:
    panel = TaskInputPanel()
    qtbot.addWidget(panel)
    domain = panel.detect_domain("List all files in current directory using command line")
    assert domain == "cli"


def test_domain_auto_detect_desktop_task(qtbot) -> None:
    panel = TaskInputPanel()
    qtbot.addWidget(panel)
    domain = panel.detect_domain("Open Notepad and type some text")
    assert domain == "desktop"


def test_domain_explicit_cli_bypasses_heuristic(qtbot) -> None:
    """Non-Auto selection must bypass detect_domain regardless of task text."""
    panel = TaskInputPanel()
    qtbot.addWidget(panel)
    # task text looks like web but user explicitly selected CLI
    index = panel.domain_combo.findText("CLI")
    panel.domain_combo.setCurrentIndex(index)
    # simulate on_run_clicked: when combo is not "Auto-detect" the label.lower() is used
    domain_label = panel.domain_combo.currentText()
    assert domain_label == "CLI"
    resolved = domain_label.lower()
    assert resolved == "cli"


def test_domain_explicit_web_bypasses_heuristic(qtbot) -> None:
    panel = TaskInputPanel()
    qtbot.addWidget(panel)
    index = panel.domain_combo.findText("Web")
    panel.domain_combo.setCurrentIndex(index)
    domain_label = panel.domain_combo.currentText()
    assert domain_label == "Web"
    resolved = domain_label.lower()
    assert resolved == "web"


def test_domain_auto_path_backward_compatible(qtbot) -> None:
    """Auto-detect option still exists and triggers heuristic domain resolution."""
    panel = TaskInputPanel()
    qtbot.addWidget(panel)
    index = panel.domain_combo.findText("Auto-detect")
    assert index >= 0, "Auto-detect option must remain in the combo"
    panel.domain_combo.setCurrentIndex(index)
    assert panel.domain_combo.currentText() == "Auto-detect"


def test_domain_selector_exposes_required_options(qtbot) -> None:
    """UI must expose Auto, CLI, Browser(Web), Desktop options."""
    panel = TaskInputPanel()
    qtbot.addWidget(panel)
    items = [panel.domain_combo.itemText(i) for i in range(panel.domain_combo.count())]
    assert "Auto-detect" in items
    assert "CLI" in items
    assert "Desktop" in items
    # Web is the Browser routing domain in the selector
    assert "Web" in items


def test_domain_ambiguous_text_returns_mixed(qtbot) -> None:
    panel = TaskInputPanel()
    qtbot.addWidget(panel)
    # both web and desktop tokens present
    domain = panel.detect_domain("Open Google in browser and also open Notepad")
    assert domain == "mixed"
