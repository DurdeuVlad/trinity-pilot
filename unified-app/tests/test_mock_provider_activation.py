"""Regression tests for MockProvider bootstrap behavior."""
from __future__ import annotations

from orchestrator.providers.mock_provider import MockProvider


def test_mock_provider_activates_gemini_mock(monkeypatch):
    calls: list[str] = []

    def fake_activate():
        calls.append("activate")

    monkeypatch.setattr("testing.gemini_mock.activator.activate", fake_activate)

    MockProvider()

    assert calls == ["activate"]
