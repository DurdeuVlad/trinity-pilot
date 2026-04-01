"""Regression tests for the live-suite pytest gate."""

from __future__ import annotations

from types import SimpleNamespace

from trinity_core import conftest


class DummyItem:
    """Minimal pytest item double for marker-gating tests."""

    def __init__(self, markers: set[str]):
        self._markers = markers
        self.added_markers: list[object] = []

    def get_closest_marker(self, name: str) -> object | None:
        return object() if name in self._markers else None

    def add_marker(self, marker: object) -> None:
        self.added_markers.append(marker)


def test_live_suite_enabled_requires_explicit_opt_in(monkeypatch) -> None:
    """Live suites should stay disabled unless the opt-in env var is set."""
    monkeypatch.delenv(conftest.LIVE_TEST_ENV_VAR, raising=False)
    assert conftest.live_suite_enabled() is False

    monkeypatch.setenv(conftest.LIVE_TEST_ENV_VAR, "1")
    assert conftest.live_suite_enabled() is True


def test_collection_hook_skips_live_marked_tests_by_default(monkeypatch) -> None:
    """Integration/performance tests should be marked skipped when opt-in is absent."""
    monkeypatch.delenv(conftest.LIVE_TEST_ENV_VAR, raising=False)
    live_item = DummyItem({"integration"})
    unit_item = DummyItem(set())

    conftest.pytest_collection_modifyitems(SimpleNamespace(), [live_item, unit_item])

    assert len(live_item.added_markers) == 2
    assert unit_item.added_markers == []
