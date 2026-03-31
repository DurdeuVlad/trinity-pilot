"""Basic memory smoke test."""
from __future__ import annotations

import os

import pytest

psutil = pytest.importorskip("psutil")


def test_memory_usage_under_load():
    process = psutil.Process(os.getpid())
    initial = process.memory_info().rss / (1024 * 1024)

    payload = []
    for _ in range(5000):
        payload.append({"frame": "x" * 2048})

    final = process.memory_info().rss / (1024 * 1024)
    growth = final - initial
    assert growth < 200
