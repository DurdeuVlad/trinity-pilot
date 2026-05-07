from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,
    user_request TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    objectives_json TEXT NOT NULL DEFAULT '[]',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attempt_logs (
    attempt_id     TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL,
    objective_id   TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    status         TEXT NOT NULL,
    failure_reason TEXT,
    evidence_json  TEXT NOT NULL DEFAULT '{}',
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reflections (
    reflection_id  TEXT PRIMARY KEY,
    objective_id   TEXT NOT NULL,
    task_id        TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    failure_reason TEXT,
    notes          TEXT NOT NULL DEFAULT '',
    recovery_hint  TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS task_fts USING fts5(
    task_id,
    user_request,
    content='tasks',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS tasks_ai AFTER INSERT ON tasks BEGIN
    INSERT INTO task_fts(rowid, task_id, user_request)
    VALUES (new.rowid, new.task_id, new.user_request);
END;

CREATE TRIGGER IF NOT EXISTS tasks_ad AFTER DELETE ON tasks BEGIN
    INSERT INTO task_fts(task_fts, rowid, task_id, user_request)
    VALUES ('delete', old.rowid, old.task_id, old.user_request);
END;

CREATE TRIGGER IF NOT EXISTS tasks_au AFTER UPDATE ON tasks BEGIN
    INSERT INTO task_fts(task_fts, rowid, task_id, user_request)
    VALUES ('delete', old.rowid, old.task_id, old.user_request);
    INSERT INTO task_fts(rowid, task_id, user_request)
    VALUES (new.rowid, new.task_id, new.user_request);
END;
"""


def open_db(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


@contextmanager
def get_conn(path: str | Path = ":memory:") -> Generator[sqlite3.Connection, None, None]:
    conn = open_db(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
