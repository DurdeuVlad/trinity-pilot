"""JSON-backed settings manager."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


class RuntimeSettings(TypedDict):
    """Normalized runtime settings consumed by unified-app components."""

    gemini_api_key: str
    openai_api_key: str
    ai_provider: str
    default_timeout_seconds: int
    max_retries: int
    default_domain: str
    frame_rate_limit: int
    max_frame_count: int
    show_bounding_boxes: bool
    theme: str


_DEFAULT_SETTINGS_PATH = (
    Path(__file__).resolve().parent.parent / "_runtime" / "orchestrator_settings.json"
)


class SettingsManager:
    """Load and persist application settings."""

    DEFAULTS = {
        "gemini_api_key": "",
        "openai_api_key": "",
        "ai_provider": "gemini",
        "default_timeout_seconds": 60,
        "max_retries": 3,
        "default_domain": "Auto-detect",
        "frame_rate_limit": 5,
        "max_frame_count": 100,
        "show_bounding_boxes": True,
        "theme": "dark",
    }

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_SETTINGS_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> RuntimeSettings:
        """Load settings with defaults fallback."""
        if not self.path.exists():
            return dict(self.DEFAULTS)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            merged: RuntimeSettings = dict(self.DEFAULTS)
            merged.update(raw)
            return merged
        except Exception:
            return dict(self.DEFAULTS)

    def save(self, data: dict) -> RuntimeSettings:
        """Persist settings to disk."""
        merged: RuntimeSettings = dict(self.DEFAULTS)
        merged.update(data)
        self.path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        return merged
