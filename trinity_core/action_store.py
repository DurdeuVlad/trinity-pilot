"""Local execution-memory store for visible MCP tool outcomes."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SCHEMA_VERSION = 1
_SENSITIVE_KEY_RE = re.compile(r"(password|token|api[_-]?key|secret|authorization|bearer)", re.I)
_TOKEN_RE = re.compile(r"[a-z0-9_./:\\-]{3,}", re.I)


@dataclass(frozen=True, slots=True)
class ActionRecord:
    id: int
    domain: str
    objective_text: str
    objective_terms: str
    action_name: str
    args_preview: str
    args_hash: str
    outcome: str
    error_code: str | None
    ts: float


@dataclass(frozen=True, slots=True)
class ActionPattern:
    domain: str
    action_name: str
    args_preview: str
    args_hash: str
    successes: int
    total: int
    success_rate: float
    last_error_code: str | None = None


class ActionStore:
    """SQLite-backed store of prior action outcomes.

    This is intentionally small and advisory. It records facts about tool
    outcomes and formats bounded prompt hints; it does not validate or block.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or Path(__file__).resolve().parent / "_data" / "action_store.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_available = self._probe_fts5()
        self._ensure_schema()

    @property
    def fts_available(self) -> bool:
        return self._fts_available

    def write(
        self,
        domain: str,
        objective_text: str,
        action_name: str,
        action_args: Any,
        outcome: str,
        error_code: str | None = None,
        ts: float | None = None,
    ) -> None:
        if outcome not in {"success", "failure"}:
            raise ValueError("outcome must be 'success' or 'failure'")

        objective = self._truncate(str(objective_text or ""), 500)
        objective_terms = self._objective_terms(objective)
        canonical_args = self._canonical_json(action_args)
        args_hash = hashlib.sha256(canonical_args.encode("utf-8")).hexdigest()
        args_preview = self._args_preview(action_args)

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO actions (
                    domain, objective_text, objective_terms, action_name,
                    args_preview, args_hash, outcome, error_code, ts, schema_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    domain,
                    objective,
                    objective_terms,
                    action_name,
                    args_preview,
                    args_hash,
                    outcome,
                    error_code,
                    float(ts if ts is not None else time.time()),
                    _SCHEMA_VERSION,
                ),
            )

    def query(
        self,
        domain: str,
        objective_text: str,
        top_successes: int = 5,
        top_failures: int = 3,
    ) -> tuple[list[ActionPattern], list[ActionPattern]]:
        records = self._candidate_records(domain=domain, objective_text=objective_text)
        if not records:
            return [], []

        objective_tokens = set(self._tokens(objective_text))
        grouped: dict[tuple[str, str, str], list[ActionRecord]] = {}
        for record in records:
            grouped.setdefault((record.domain, record.action_name, record.args_hash), []).append(record)

        successes: list[tuple[float, ActionPattern]] = []
        failures: list[tuple[float, ActionPattern]] = []

        for group_records in grouped.values():
            pattern = self._pattern_from_records(group_records)
            if pattern.total == 0:
                continue

            record_tokens = set()
            for record in group_records:
                record_tokens.update(self._tokens(record.objective_terms))
                record_tokens.update(self._tokens(record.objective_text))
            overlap = self._overlap_ratio(objective_tokens, record_tokens)

            if pattern.successes > 0 and (pattern.total >= 2 or overlap >= 0.60):
                successes.append((pattern.success_rate + overlap, pattern))
            if pattern.total >= 5 and pattern.success_rate < 0.30:
                failures.append(((1.0 - pattern.success_rate) + overlap, pattern))

        successes.sort(key=lambda item: (-item[0], -item[1].total, item[1].action_name))
        failures.sort(key=lambda item: (-item[0], -item[1].total, item[1].action_name))
        return (
            [pattern for _, pattern in successes[:top_successes]],
            [pattern for _, pattern in failures[:top_failures]],
        )

    def get_rate(
        self,
        domain: str,
        action_name: str,
        args_hash: str | None = None,
        window: int = 20,
    ) -> tuple[int, int, float]:
        sql = """
            SELECT outcome FROM actions
            WHERE domain = ? AND action_name = ?
        """
        params: list[Any] = [domain, action_name]
        if args_hash is not None:
            sql += " AND args_hash = ?"
            params.append(args_hash)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        params.append(window)

        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        total = len(rows)
        successes = sum(1 for row in rows if row["outcome"] == "success")
        return successes, total, (successes / total if total else 0.0)

    def demoted_actions(
        self,
        domain: str,
        min_count: int = 5,
        threshold: float = 0.30,
        window: int = 20,
    ) -> list[ActionPattern]:
        with self._connection() as conn:
            keys = conn.execute(
                """
                SELECT DISTINCT action_name, args_hash FROM actions
                WHERE domain = ?
                """,
                (domain,),
            ).fetchall()
            patterns: list[ActionPattern] = []
            for key in keys:
                rows = conn.execute(
                    """
                    SELECT * FROM actions
                    WHERE domain = ? AND action_name = ? AND args_hash = ?
                    ORDER BY ts DESC, id DESC LIMIT ?
                    """,
                    (domain, key["action_name"], key["args_hash"], window),
                ).fetchall()
                records = [self._record_from_row(row) for row in rows]
                pattern = self._pattern_from_records(records)
                if pattern.total >= min_count and pattern.success_rate < threshold:
                    patterns.append(pattern)

        patterns.sort(key=lambda item: (item.success_rate, -item.total, item.action_name))
        return patterns

    def format_prompt_section(self, domain: str, objective_text: str) -> str:
        successes, failures = self.query(domain, objective_text)
        if not successes and not failures:
            return ""

        sections: list[str] = []
        if successes:
            lines = ["PROVEN PATTERNS (past executions in this domain; use only when relevant):"]
            for pattern in successes:
                lines.append(
                    f'- {pattern.action_name} args~"{pattern.args_preview}" '
                    f"succeeded {pattern.successes}/{pattern.total} similar runs."
                )
            sections.append("\n".join(lines))

        if failures:
            lines = ["AVOID (high failure rate in this domain; override only with a reason):"]
            for pattern in failures:
                suffix = f" Last error: {pattern.last_error_code}." if pattern.last_error_code else ""
                lines.append(
                    f'- {pattern.action_name} args~"{pattern.args_preview}" '
                    f"succeeded {pattern.successes}/{pattern.total} similar runs.{suffix}"
                )
            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _probe_fts5(self) -> bool:
        try:
            with sqlite3.connect(":memory:") as conn:
                conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            return True
        except sqlite3.Error:
            return False

    def _ensure_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    objective_text TEXT NOT NULL,
                    objective_terms TEXT NOT NULL,
                    action_name TEXT NOT NULL,
                    args_preview TEXT NOT NULL,
                    args_hash TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('success', 'failure')),
                    error_code TEXT,
                    ts REAL NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_domain_ts ON actions(domain, ts)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_actions_rate ON actions(domain, action_name, args_hash, ts)"
            )
            if self._fts_available:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS actions_fts USING fts5(
                        objective_text,
                        objective_terms,
                        action_name,
                        args_preview,
                        content='actions',
                        content_rowid='id'
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS actions_ai AFTER INSERT ON actions BEGIN
                        INSERT INTO actions_fts(
                            rowid, objective_text, objective_terms, action_name, args_preview
                        )
                        VALUES (
                            new.id, new.objective_text, new.objective_terms,
                            new.action_name, new.args_preview
                        );
                    END
                    """
                )

    def _candidate_records(self, domain: str, objective_text: str) -> list[ActionRecord]:
        terms = self._tokens(objective_text)
        if self._fts_available and terms:
            query = " OR ".join(f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in terms[:12])
            try:
                with self._connection() as conn:
                    rows = conn.execute(
                        """
                        SELECT actions.* FROM actions_fts
                        JOIN actions ON actions_fts.rowid = actions.id
                        WHERE actions.domain = ? AND actions_fts MATCH ?
                        ORDER BY bm25(actions_fts), actions.ts DESC
                        LIMIT 200
                        """,
                        (domain, query),
                    ).fetchall()
                if rows:
                    return [self._record_from_row(row) for row in rows]
            except sqlite3.Error:
                pass

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM actions
                WHERE domain = ?
                ORDER BY ts DESC, id DESC
                LIMIT 500
                """,
                (domain,),
            ).fetchall()

        objective_tokens = set(terms)
        scored: list[tuple[float, ActionRecord]] = []
        for row in rows:
            record = self._record_from_row(row)
            record_tokens = set(self._tokens(record.objective_text))
            record_tokens.update(self._tokens(record.objective_terms))
            record_tokens.update(self._tokens(record.action_name))
            score = self._overlap_ratio(objective_tokens, record_tokens)
            if score > 0 or not objective_tokens:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], -item[1].ts))
        return [record for _, record in scored[:200]]

    def _pattern_from_records(self, records: list[ActionRecord]) -> ActionPattern:
        if not records:
            return ActionPattern("", "", "", "", 0, 0, 0.0)
        sorted_records = sorted(records, key=lambda record: (record.ts, record.id), reverse=True)[:20]
        successes = sum(1 for record in sorted_records if record.outcome == "success")
        total = len(sorted_records)
        last_error = next((record.error_code for record in sorted_records if record.error_code), None)
        first = sorted_records[0]
        return ActionPattern(
            domain=first.domain,
            action_name=first.action_name,
            args_preview=first.args_preview,
            args_hash=first.args_hash,
            successes=successes,
            total=total,
            success_rate=successes / total if total else 0.0,
            last_error_code=last_error,
        )

    def _record_from_row(self, row: sqlite3.Row) -> ActionRecord:
        return ActionRecord(
            id=int(row["id"]),
            domain=str(row["domain"]),
            objective_text=str(row["objective_text"]),
            objective_terms=str(row["objective_terms"]),
            action_name=str(row["action_name"]),
            args_preview=str(row["args_preview"]),
            args_hash=str(row["args_hash"]),
            outcome=str(row["outcome"]),
            error_code=row["error_code"],
            ts=float(row["ts"]),
        )

    def _canonical_json(self, value: Any) -> str:
        try:
            return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), default=str)
        except TypeError:
            return json.dumps(str(value), sort_keys=True)

    def _args_preview(self, value: Any) -> str:
        redacted = self._redact(value)
        preview = self._canonical_json(redacted)
        return self._truncate(preview, 200)

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                redacted[key_text] = "[REDACTED]" if _SENSITIVE_KEY_RE.search(key_text) else self._redact(item)
            return redacted
        if isinstance(value, list):
            return [self._redact(item) for item in value[:20]]
        if isinstance(value, tuple):
            return [self._redact(item) for item in value[:20]]
        if isinstance(value, str):
            if _SENSITIVE_KEY_RE.search(value):
                return "[REDACTED]"
            return self._truncate(value, 300)
        return value

    def _objective_terms(self, text: str) -> str:
        return " ".join(self._tokens(text))

    def _tokens(self, text: Any) -> list[str]:
        seen: set[str] = set()
        tokens: list[str] = []
        for match in _TOKEN_RE.finditer(str(text).lower()):
            token = match.group(0).strip("-_.:/\\")
            if len(token) >= 3 and token not in seen:
                seen.add(token)
                tokens.append(token)
        return tokens

    def _overlap_ratio(self, query_tokens: set[str], record_tokens: set[str]) -> float:
        if not query_tokens or not record_tokens:
            return 0.0
        return len(query_tokens & record_tokens) / len(query_tokens)

    def _truncate(self, value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 3)] + "..."
