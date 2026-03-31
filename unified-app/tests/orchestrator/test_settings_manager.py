"""Tests for settings manager persistence."""
from __future__ import annotations

from orchestrator.settings_manager import SettingsManager


def test_settings_load_defaults(tmp_path):
    manager = SettingsManager(str(tmp_path / "settings.json"))
    data = manager.load()
    assert "default_timeout_seconds" in data
    assert data["enable_glass_box"] is True


def test_settings_save_and_load(tmp_path):
    manager = SettingsManager(str(tmp_path / "settings.json"))
    manager.save({"default_timeout_seconds": 120, "theme": "light"})
    data = manager.load()
    assert data["default_timeout_seconds"] == 120
    assert data["theme"] == "light"
