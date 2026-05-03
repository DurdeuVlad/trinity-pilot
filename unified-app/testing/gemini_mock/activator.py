"""Stub Gemini mock activator. Real patching not needed for non-live tests."""
from __future__ import annotations

from typing import Any


def activate(backend: Any = None) -> None:
    pass


def deactivate() -> None:
    pass
