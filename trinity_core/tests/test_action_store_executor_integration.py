"""Integration tests: ActionStore write -> format_prompt_section -> system prompt injection cycle."""

from __future__ import annotations

from trinity_core.action_store import ActionStore


def test_proven_patterns_appear_after_two_successes(tmp_path):
    store = ActionStore(db_path=tmp_path / "test.db")
    store.write("cli", "list project files", "run_command", {"command": "Get-ChildItem"}, "success")
    store.write("cli", "list project files", "run_command", {"command": "Get-ChildItem"}, "success")

    section = store.format_prompt_section("cli", "list files in project")

    assert "PROVEN PATTERNS" in section
    assert "run_command" in section


def test_avoid_section_appears_after_high_failure_rate(tmp_path):
    store = ActionStore(db_path=tmp_path / "test.db")
    for i in range(7):
        outcome = "success" if i == 0 else "failure"
        store.write("desktop", "confirm dialog", "click_element", {"label": "OK"}, outcome, error_code="CLICK_FAILED" if outcome == "failure" else None)

    section = store.format_prompt_section("desktop", "confirm dialog box")

    assert "AVOID" in section
    assert "click_element" in section


def test_empty_store_injects_nothing(tmp_path):
    store = ActionStore(db_path=tmp_path / "test.db")
    assert store.format_prompt_section("cli", "list files") == ""


def test_domain_isolation_prevents_cross_domain_bleed(tmp_path):
    store = ActionStore(db_path=tmp_path / "test.db")
    store.write("browser", "open github", "navigate", {"url": "https://github.com"}, "success")
    store.write("browser", "open github", "navigate", {"url": "https://github.com"}, "success")

    section = store.format_prompt_section("cli", "open github")

    assert section == ""


def test_single_success_below_overlap_threshold_excluded(tmp_path):
    store = ActionStore(db_path=tmp_path / "test.db")
    store.write("cli", "completely unrelated task xyz", "run_command", {"command": "dir"}, "success")

    section = store.format_prompt_section("cli", "list project files")

    assert section == ""
