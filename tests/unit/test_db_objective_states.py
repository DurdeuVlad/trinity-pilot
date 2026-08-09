"""Tests for objective_states table and db.py updates (AC-2.2)."""
from trinity_pilot.memory.db import open_db
from trinity_pilot.memory.store import ObjectiveStateStore
from trinity_pilot.orchestrator.fsm import ObjectiveState


def test_objective_states_table_created():
    conn = open_db()
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='objective_states'")
    assert cursor.fetchone() is not None


def test_objective_states_insert_select():
    conn = open_db()
    conn.execute("""
        INSERT INTO objective_states (objective_id, task_id, state, step_count, token_count)
        VALUES ('obj-1', 'task-1', 'running', 3, 150)
    """)
    conn.commit()
    row = conn.execute(
        "SELECT state, step_count, token_count FROM objective_states WHERE objective_id='obj-1' AND task_id='task-1'"
    ).fetchone()
    assert row["state"] == "running"
    assert row["step_count"] == 3
    assert row["token_count"] == 150


def test_objective_states_user_question():
    conn = open_db()
    conn.execute("""
        INSERT INTO objective_states (objective_id, task_id, state, user_question)
        VALUES ('obj-2', 'task-1', 'stuck', 'What should I do next?')
    """)
    conn.commit()
    row = conn.execute(
        "SELECT user_question FROM objective_states WHERE objective_id='obj-2'"
    ).fetchone()
    assert row["user_question"] == "What should I do next?"


def test_busy_timeout_set():
    conn = open_db()
    result = conn.execute("PRAGMA busy_timeout").fetchone()
    assert result[0] == 10000


def test_wal_mode_still_enabled(tmp_path):
    db_file = tmp_path / "test.db"
    conn = open_db(db_file)
    result = conn.execute("PRAGMA journal_mode").fetchone()
    assert result[0] == "wal"


def test_existing_tables_still_created():
    conn = open_db()
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "tasks" in tables
    assert "attempt_logs" in tables
    assert "reflections" in tables
    assert "objective_states" in tables


def test_mark_orphaned_running_as_interrupted_resolves_transient_states():
    """RUNNING/STUCK/STEERED left by a crashed prior run must resolve to FAILED
    with a clear failure_reason, not silently stay inconsistent forever."""
    store = ObjectiveStateStore(":memory:")
    store.upsert("t-1", "obj-running", ObjectiveState.RUNNING)
    store.upsert("t-1", "obj-stuck", ObjectiveState.STUCK)
    store.upsert("t-1", "obj-steered", ObjectiveState.STEERED)
    store.upsert("t-1", "obj-done", ObjectiveState.DONE)
    store.upsert("t-1", "obj-failed", ObjectiveState.FAILED)

    resolved = store.mark_orphaned_running_as_interrupted()

    assert set(resolved) == {("t-1", "obj-running"), ("t-1", "obj-stuck"), ("t-1", "obj-steered")}
    for objective_id in ("obj-running", "obj-stuck", "obj-steered"):
        row = store.get("t-1", objective_id)
        assert row["state"] == ObjectiveState.FAILED.value
        assert row["failure_reason"] == "interrupted_by_restart"
    # Already-terminal states must be left untouched.
    assert store.get("t-1", "obj-done")["state"] == ObjectiveState.DONE.value
    assert store.get("t-1", "obj-failed")["failure_reason"] != "interrupted_by_restart"


def test_mark_orphaned_running_as_interrupted_no_op_when_none_transient():
    store = ObjectiveStateStore(":memory:")
    store.upsert("t-1", "obj-done", ObjectiveState.DONE)

    assert store.mark_orphaned_running_as_interrupted() == []
