"""Stub queue backend for Gemini mock."""
from __future__ import annotations

from typing import Any


class QueueBackend:
    def __init__(self) -> None:
        self._queue: list[Any] = []

    def enqueue(self, response: Any) -> None:
        self._queue.append(response)

    def dequeue(self) -> Any:
        return self._queue.pop(0) if self._queue else None
