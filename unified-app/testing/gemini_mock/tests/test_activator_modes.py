from __future__ import annotations

from testing.gemini_mock.activator import activate, deactivate
from testing.gemini_mock.backends.queue_backend import QueueBackend


def teardown_function() -> None:
    """Reset activator state between tests."""
    deactivate()


def test_activate_stdio_mode_selects_stdio_backend(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MOCK", "stdio")

    backend = activate()

    assert backend.__class__.__name__ == "StdioBackend"


def test_activate_http_mode_uses_server_url(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MOCK", "http")
    monkeypatch.setenv("GEMINI_MOCK_SERVER_URL", "http://localhost:9999")

    backend = activate()

    assert backend.__class__.__name__ == "HttpBackend"
    assert backend.server_url == "http://localhost:9999"


def test_activate_llm_mode_uses_provider(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MOCK", "llm")
    monkeypatch.setenv("GEMINI_MOCK_LLM_PROVIDER", "openai")

    backend = activate()

    assert backend.__class__.__name__ == "LLMBackend"
    assert backend.provider == "openai"


def test_activate_unknown_mode_falls_back_to_queue(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MOCK", "mystery")

    backend = activate()

    assert isinstance(backend, QueueBackend)
