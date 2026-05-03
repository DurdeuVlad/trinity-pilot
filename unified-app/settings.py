"""Simple JSON-backed settings store."""
from __future__ import annotations

import json
from pathlib import Path

_PATH = Path(__file__).parent / "settings.json"


class Settings:
    def __init__(self, path: Path = _PATH) -> None:
        self._path = path
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._save()

    def update(self, data: dict) -> None:
        self._data.update(data)
        self._save()

    def all(self) -> dict:
        return dict(self._data)

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception:
            pass


_instance = Settings()


def get_settings() -> Settings:
    return _instance
