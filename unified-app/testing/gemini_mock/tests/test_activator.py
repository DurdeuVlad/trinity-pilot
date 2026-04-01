from __future__ import annotations

import importlib

from testing.gemini_mock.mock_genai import set_backend


class _StubBackend:
    """Backend stub for activator tests."""

    def respond(self, prompt: object, model_name: str, generation_config: object) -> str:
        return '{"steps":["stub"],"estimated_duration":5,"confidence":0.8}'


def teardown_function() -> None:
    """Ensure the activator is reset after each test."""
    from testing.gemini_mock.activator import deactivate

    deactivate()
    set_backend(None)


def test_activate_injects_mock_and_deactivate_restores() -> None:
    activator = importlib.import_module("testing.gemini_mock.activator")
    backend = _StubBackend()

    activator.activate(backend=backend)
    assert activator.is_active() is True

    import google.generativeai as genai

    assert genai.__name__ == "testing.gemini_mock.mock_genai"

    activator.deactivate()
    assert activator.is_active() is False


def test_activate_provides_google_api_core_stub_when_missing() -> None:
    activator = importlib.import_module("testing.gemini_mock.activator")
    activator.activate(backend=_StubBackend())

    from google.api_core import exceptions as google_exceptions

    assert issubclass(google_exceptions.ResourceExhausted, Exception)
    assert issubclass(google_exceptions.Unauthenticated, Exception)

