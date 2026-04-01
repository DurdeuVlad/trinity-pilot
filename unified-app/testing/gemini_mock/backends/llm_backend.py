"""Provider-backed LLM auto-responder for Gemini mock flows."""
from __future__ import annotations

import json
import os
import urllib.request
from importlib import import_module
from typing import Any

from testing.gemini_mock.mock_genai import GenerationConfig, _flatten_prompt

_SYSTEM_PROMPT = """You are simulating the Gemini AI API in a test environment.
Return valid JSON only when the expected MIME type is application/json.
Use the schema: {"steps": ["step"], "estimated_duration": 10, "confidence": 0.8}."""


class LLMBackend:
    """Delegate Gemini prompts to Anthropic, OpenAI, or Ollama."""

    def __init__(self, provider: str | None = None, model: str | None = None) -> None:
        self.provider = (provider or os.getenv("GEMINI_MOCK_LLM_PROVIDER", "anthropic")).lower()
        self.model = model

    def respond(self, prompt: Any, model_name: str, generation_config: GenerationConfig) -> str:
        """Return one provider-generated response for the given Gemini prompt."""
        mime_type = generation_config.response_mime_type or "text/plain"
        user_message = (
            f"[Gemini model requested: {model_name}]\n"
            f"[Expected MIME type: {mime_type}]\n\n"
            f"{_flatten_prompt(prompt)}"
        )
        if self.provider == "anthropic":
            return self._respond_anthropic(user_message)
        if self.provider == "openai":
            return self._respond_openai(user_message)
        if self.provider == "ollama":
            return self._respond_ollama(user_message)
        raise ValueError(f"LLMBackend: unknown provider {self.provider!r}")

    def _respond_anthropic(self, user_message: str) -> str:
        """Call the Anthropic SDK with a guarded import."""
        try:
            anthropic = import_module("anthropic")
        except ImportError as exc:
            raise ImportError("LLMBackend: provider 'anthropic' requires 'pip install anthropic'") from exc
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=self.model or "claude-3-5-haiku-latest",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    def _respond_openai(self, user_message: str) -> str:
        """Call the OpenAI SDK with a guarded import."""
        try:
            openai = import_module("openai")
        except ImportError as exc:
            raise ImportError("LLMBackend: provider 'openai' requires 'pip install openai'") from exc
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model=self.model or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=1024,
        )
        return response.choices[0].message.content or ""

    def _respond_ollama(self, user_message: str) -> str:
        """Call the Ollama HTTP API using urllib only."""
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        payload = json.dumps(
            {
                "model": self.model or "llama3.2",
                "prompt": f"{_SYSTEM_PROMPT}\n\n{user_message}",
                "stream": False,
            }
        ).encode()
        request = urllib.request.Request(
            f"{base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return str(json.loads(response.read()).get("response", ""))
        except OSError as exc:
            raise RuntimeError(f"LLMBackend: Ollama not reachable at {base_url}") from exc
