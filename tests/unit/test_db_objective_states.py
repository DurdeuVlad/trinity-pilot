"""Tests for objective_states table and db.py updates (AC-2.2)."""
import sqlite3
from trinity_pilot.memory.db import open_db


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
