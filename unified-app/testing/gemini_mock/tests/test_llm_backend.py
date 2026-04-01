from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from testing.gemini_mock.backends.llm_backend import LLMBackend, _SYSTEM_PROMPT
from testing.gemini_mock.mock_genai import GenerationConfig


def test_llm_backend_rejects_unknown_provider() -> None:
    backend = LLMBackend(provider="unknown")

    with pytest.raises(ValueError, match="unknown provider"):
        backend.respond("prompt", "gemini", GenerationConfig())


def test_llm_backend_raises_clear_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import_module(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr("testing.gemini_mock.backends.llm_backend.import_module", fake_import_module)

    backend = LLMBackend(provider="anthropic")
    with pytest.raises(ImportError, match="pip install anthropic"):
        backend.respond("prompt", "gemini", GenerationConfig())


def test_llm_backend_anthropic_formats_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeMessages:
        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(content=[SimpleNamespace(text='{"ok":true}')])

    class FakeAnthropicClient:
        def __init__(self) -> None:
            self.messages = FakeMessages()

    fake_module = SimpleNamespace(Anthropic=FakeAnthropicClient)
    monkeypatch.setattr("testing.gemini_mock.backends.llm_backend.import_module", lambda _: fake_module)

    backend = LLMBackend(provider="Anthropic")
    result = backend.respond("prompt body", "gemini-model", GenerationConfig(response_mime_type="application/json"))

    assert result == '{"ok":true}'
    assert "application/json" in captured["messages"][0]["content"]
    assert "gemini-model" in captured["messages"][0]["content"]
    assert captured["system"] == _SYSTEM_PROMPT


def test_llm_backend_ollama_uses_urllib(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"response": "ollama text"}).encode()

    monkeypatch.setattr(
        "testing.gemini_mock.backends.llm_backend.urllib.request.urlopen",
        lambda request, timeout=30: FakeResponse(),
    )

    backend = LLMBackend(provider="ollama", model="llama3.2")
    result = backend.respond("prompt", "gemini", GenerationConfig())

    assert result == "ollama text"
