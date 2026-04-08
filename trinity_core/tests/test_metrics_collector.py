"""Unit tests for trinity_core.metrics.MetricsCollector."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trinity_core.metrics.metrics_collector import MetricsCollector


class TestMetricsCollector:
    def _make(self, tmp_path: Path) -> MetricsCollector:
        return MetricsCollector(base_dir=tmp_path / ".metrics")

    def _load_all(self, base_dir: Path) -> list[dict]:
        events = []
        for f in sorted(base_dir.glob("*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    events.append(json.loads(line))
        return events

    def test_record_task_writes_jsonl(self, tmp_path):
        mc = self._make(tmp_path)
        mc.record_task("t1", "web", "success", 123.4)
        events = self._load_all(mc._base_dir)
        assert len(events) == 1
        e = events[0]
        assert e["event"] == "task"
        assert e["task_id"] == "t1"
        assert e["domain"] == "web"
        assert e["status"] == "success"
        assert abs(e["duration_ms"] - 123.4) < 0.01
        assert "timestamp" in e

    def test_record_tool_call(self, tmp_path):
        mc = self._make(tmp_path)
        mc.record_tool_call("navigate", "web", "success", 55.0)
        e = self._load_all(mc._base_dir)[0]
        assert e["event"] == "tool_call"
        assert e["tool_name"] == "navigate"

    def test_record_llm_call(self, tmp_path):
        mc = self._make(tmp_path)
        mc.record_llm_call("web", tokens_used=200, duration_ms=300.0)
        e = self._load_all(mc._base_dir)[0]
        assert e["event"] == "llm_call"
        assert e["tokens_used"] == 200

    def test_record_review(self, tmp_path):
        mc = self._make(tmp_path)
        mc.record_review("cli", approved=True, attempt_number=1)
        e = self._load_all(mc._base_dir)[0]
        assert e["event"] == "review"
        assert e["approved"] is True
        assert e["attempt_number"] == 1

    def test_multiple_events_appended(self, tmp_path):
        mc = self._make(tmp_path)
        mc.record_task("t1", "web", "success", 10.0)
        mc.record_task("t2", "cli", "failure", 20.0)
        events = self._load_all(mc._base_dir)
        assert len(events) == 2

    def test_creates_dir_on_first_write(self, tmp_path):
        metrics_dir = tmp_path / "does_not_exist"
        mc = MetricsCollector(base_dir=metrics_dir)
        mc.record_task("t1", "web", "success", 1.0)
        assert metrics_dir.exists()
