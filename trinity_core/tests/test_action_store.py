from __future__ import annotations

import sqlite3

from trinity_core.action_store import ActionStore


def test_action_store_creates_schema(tmp_path):
    db_path = tmp_path / "actions.db"
    ActionStore(db_path=db_path)

    conn = sqlite3.connect(db_path)
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='actions'"
        ).fetchone()
    finally:
        conn.close()

    assert table is not None


def test_write_and_query_success_record(tmp_path):
    store = ActionStore(db_path=tmp_path / "actions.db")
    store.write(
        "cli",
        "list project files",
        "run_command",
        {"command": "Get-ChildItem"},
        "success",
        ts=1.0,
    )
    store.write(
        "cli",
        "list project files",
        "run_command",
        {"command": "Get-ChildItem"},
        "success",
        ts=2.0,
    )

    successes, failures = store.query("cli", "list files")

    assert failures == []
    assert successes
    assert successes[0].action_name == "run_command"
    assert successes[0].successes == 2
    assert successes[0].total == 2


def test_empty_store_returns_no_prompt_section(tmp_path):
    store = ActionStore(db_path=tmp_path / "actions.db")

    assert store.format_prompt_section("cli", "list files") == ""


def test_query_finds_relevant_record_by_keyword(tmp_path):
    store = ActionStore(db_path=tmp_path / "actions.db")
    store.write("desktop", "open notepad text editor", "launch_app", {"name": "notepad"}, "success", ts=1.0)
    store.write("desktop", "open notepad text editor", "launch_app", {"name": "notepad"}, "success", ts=2.0)

    successes, _ = store.query("desktop", "open text editor")

    assert [pattern.action_name for pattern in successes] == ["launch_app"]


def test_get_rate_uses_rolling_window(tmp_path):
    store = ActionStore(db_path=tmp_path / "actions.db")
    for i in range(25):
        store.write(
            "cli",
            "list files",
            "run_command",
            {"command": "Get-ChildItem"},
            "success" if i >= 5 else "failure",
            ts=float(i),
        )

    successes, total, rate = store.get_rate("cli", "run_command", window=20)

    assert successes == 20
    assert total == 20
    assert rate == 1.0


def test_demoted_actions_trigger_after_threshold(tmp_path):
    store = ActionStore(db_path=tmp_path / "actions.db")
    for i in range(5):
        store.write(
            "desktop",
            "confirm dialog",
            "click_element",
            {"label": "OK"},
            "success" if i == 0 else "failure",
            error_code=None if i == 0 else "CLICK_FAILED",
            ts=float(i),
        )

    demoted = store.demoted_actions("desktop")

    assert len(demoted) == 1
    assert demoted[0].action_name == "click_element"
    assert demoted[0].successes == 1
    assert demoted[0].total == 5
    assert demoted[0].last_error_code == "CLICK_FAILED"


def test_demoted_actions_require_minimum_count(tmp_path):
    store = ActionStore(db_path=tmp_path / "actions.db")
    for i in range(4):
        store.write("desktop", "confirm dialog", "click_element", {"label": "OK"}, "failure", ts=float(i))

    assert store.demoted_actions("desktop") == []


def test_args_preview_redacts_secret_like_fields(tmp_path):
    store = ActionStore(db_path=tmp_path / "actions.db")
    store.write(
        "cli",
        "call api",
        "run_command",
        {"api_key": "abc123", "Authorization": "Bearer abc123", "safe": "value"},
        "success",
    )

    successes, _ = store.query("cli", "call api")

    assert successes[0].args_preview.count("[REDACTED]") == 2
    assert "abc123" not in successes[0].args_preview
    assert "value" in successes[0].args_preview


def test_args_preview_truncates_long_values(tmp_path):
    store = ActionStore(db_path=tmp_path / "actions.db")
    store.write("cli", "write file", "run_command", {"content": "x" * 1000}, "success")

    successes, _ = store.query("cli", "write file")

    assert len(successes[0].args_preview) <= 200
    assert successes[0].args_preview.endswith("...")


def test_fallback_query_when_fts_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(ActionStore, "_probe_fts5", lambda self: False)
    store = ActionStore(db_path=tmp_path / "actions.db")
    store.write("browser", "search github projects", "navigate", {"url": "https://github.com"}, "success", ts=1.0)
    store.write("browser", "search github projects", "navigate", {"url": "https://github.com"}, "success", ts=2.0)

    successes, failures = store.query("browser", "github search")

    assert failures == []
    assert successes[0].action_name == "navigate"
