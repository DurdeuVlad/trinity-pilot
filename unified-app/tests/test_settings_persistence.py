"""Tests for persisted runtime settings."""
from __future__ import annotations

from orchestrator.settings_manager import SettingsManager


def test_full_persistence(tmp_path) -> None:
    manager = SettingsManager(str(tmp_path / "settings.json"))

    saved = manager.save(
        {
            "gemini_api_key": "persisted-key",
            "default_timeout_seconds": 222,
            "max_retries": 5,
            "enable_glass_box": False,
            "default_domain": "CLI",
            "frame_rate_limit": 15,
            "max_frame_count": 150,
            "show_bounding_boxes": False,
            "theme": "dark",
        }
    )

    loaded = manager.load()

    assert loaded == saved
    assert loaded["max_frame_count"] == 150
