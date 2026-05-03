"""Thin shim — delegates to root settings store."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from settings import get_settings


class SettingsManager:
    def load(self) -> dict:
        return get_settings().all()

    def save(self, data: dict) -> None:
        get_settings().update(data)
