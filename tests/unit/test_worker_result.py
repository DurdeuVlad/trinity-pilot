"""Tests for WorkerResult dataclass (Story 1)."""
from __future__ import annotations

import dataclasses
import json

import pytest

from trinity_pilot.workers.worker_result import WorkerResult


def test_worker_result_status_literals():
    r1 = WorkerResult(status="success")
    r2 = WorkerResult(status="partial_blocker")
    r3 = WorkerResult(status="failure")
    assert r1.status == "success"
    assert r2.status == "partial_blocker"
    assert r3.status == "failure"


def test_worker_result_defaults():
    r = WorkerResult(status="success")
    assert r.summary == ""
    assert r.evidence == {}
    assert r.steps_taken == 0
    assert r.tokens_used == 0


def test_worker_result_is_json_serialisable():
    r = WorkerResult(status="success")
    json.dumps(dataclasses.asdict(r))  # must not raise
