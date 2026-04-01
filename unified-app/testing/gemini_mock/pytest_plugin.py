"""Pytest fixtures for activating the Gemini mock."""
from __future__ import annotations

from collections.abc import Generator

import pytest

from testing.gemini_mock.activator import activate, deactivate
from testing.gemini_mock.backends.queue_backend import QueueBackend

activate(backend=QueueBackend())


@pytest.fixture
def gemini_mock() -> Generator[QueueBackend, None, None]:
    """Activate the Gemini mock for one test and yield its backend."""
    backend = QueueBackend()
    activate(backend=backend)
    try:
        yield backend
    finally:
        deactivate()


@pytest.fixture(scope="module")
def gemini_mock_session() -> Generator[QueueBackend, None, None]:
    """Activate the Gemini mock once per module and yield its backend."""
    backend = QueueBackend()
    activate(backend=backend)
    try:
        yield backend
    finally:
        deactivate()
