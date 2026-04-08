from __future__ import annotations

import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def _make_fake_logger_module() -> tuple[ModuleType, list[tuple[str, dict]]]:
    calls: list[tuple[str, dict]] = []
    fake_module = ModuleType("audit_debugger.prompt_logger")

    def _capture(kind: str):
        def _inner(**kwargs):
            calls.append((kind, kwargs))
            payload = dict(kwargs)
            payload.setdefault("phase", "ai_reasoning")
            payload.setdefault("message", f"LLM {kind}")
            payload.setdefault("data", kwargs.get("data", kwargs))
            return payload

        return _inner

    for name in ("log_prompt", "record_prompt", "emit_prompt"):
        setattr(fake_module, name, _capture("prompt"))
    for name in ("log_response", "record_response", "emit_response"):
        setattr(fake_module, name, _capture("response"))
    for name in ("log_llm_interaction", "record_interaction", "emit_interaction"):
        setattr(fake_module, name, _capture("interaction"))
    return fake_module, calls


def _make_fake_types():
    class _Content:
        def __init__(self, role, parts):
            self.role = role
            self.parts = parts

    class _Part:
        def __init__(self, text):
            self.text = text

    class _GenerateContentConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    return SimpleNamespace(Content=_Content, Part=_Part, GenerateContentConfig=_GenerateContentConfig)


def test_gemini_provider_emits_prompt_and_response_events(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt_logger = pytest.importorskip("audit_debugger.prompt_logger")
    fake_module, calls = _make_fake_logger_module()

    for name in ("log_prompt", "record_prompt", "emit_prompt", "log_response", "record_response", "emit_response", "log_llm_interaction", "record_interaction", "emit_interaction"):
        monkeypatch.setattr(prompt_logger, name, getattr(fake_module, name), raising=False)

    monkeypatch.setitem(sys.modules, "audit_debugger.prompt_logger", prompt_logger)

    gemini_provider = importlib.import_module("orchestrator.providers.gemini_provider")
    importlib.reload(gemini_provider)
    GeminiProvider = gemini_provider.GeminiProvider

    response = SimpleNamespace(
        text='{"status":"ok"}',
        usage_metadata=SimpleNamespace(
            prompt_token_count=11,
            candidates_token_count=7,
            total_token_count=18,
        ),
        finish_reason="STOP",
    )

    class _FakeModels:
        async def generate_content(self, **kwargs):
            return response

    class _FakeAio:
        def __init__(self):
            self.models = _FakeModels()

    class _FakeClient:
        def __init__(self):
            self.aio = _FakeAio()

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._client = _FakeClient()
    provider._types = _make_fake_types()
    provider.cache = None
    provider._last_cache_key = None

    messages = [
        {"role": "system", "content": "system api_key=sk-live-123 password=hunter2 token=tok-456"},
        {"role": "user", "content": "plan the next step"},
        {"role": "assistant", "content": "previous context"},
    ]

    result = asyncio.run(provider.call(messages, json_mode=True))

    assert result == response.text
    assert calls, "GeminiProvider should emit at least one reasoning event"

    prompt_calls = [payload for kind, payload in calls if kind in {"prompt", "interaction"}]
    response_calls = [payload for kind, payload in calls if kind in {"response", "interaction"}]

    assert prompt_calls, "GeminiProvider should emit a prompt-side reasoning event"
    assert response_calls, "GeminiProvider should emit a response-side reasoning event"

    prompt_payload = prompt_calls[0].get("data", prompt_calls[0])
    response_payload = response_calls[-1].get("data", response_calls[-1])

    assert prompt_payload["model"] == provider.MODEL
    assert prompt_payload["prompt_length"] > 0
    assert isinstance(prompt_payload.get("context_tokens_estimate"), int)
    assert any(
        key in prompt_payload
        for key in ("prompt_preview", "prompt", "messages", "system_instructions", "system_instruction")
    )

    assert response_payload["model"] == provider.MODEL
    assert response_payload["response_length"] == len(response.text)
    assert response_payload["response_preview"].startswith("{")
    assert response_payload["finish_reason"] == "STOP"
    assert response_payload["tokens"] == {"prompt": 11, "completion": 7, "total": 18}
