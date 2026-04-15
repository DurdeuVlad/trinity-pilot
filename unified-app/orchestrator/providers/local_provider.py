"""Local LLM provider via Ollama — implements the orchestrator base.LLMProvider interface."""
from __future__ import annotations

import logging

import httpx

from .base import LLMProvider

logger = logging.getLogger(__name__)


class LocalProvider(LLMProvider):
    """Ollama-backed LLM backend for the orchestrator layer.

    Mirrors OpenAIProvider's structure: same base class, same logging hooks,
    same close() pattern. Talks directly to Ollama via the openai SDK.
    """

    def __init__(self, base_url: str, model: str) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "openai is required for LocalProvider. "
                "Install it with: pip install openai"
            ) from exc

        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key="ollama",
            timeout=120.0,
            max_retries=0,
        )
        self._model = model
        self._base_url = base_url

    @property
    def provider_name(self) -> str:
        return "local"

    async def call(
        self,
        messages: list[dict],
        *,
        json_mode: bool = True,
        purpose: str | None = None,
    ) -> str:
        kwargs: dict = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resolved_purpose = purpose or self._infer_purpose(messages)
        call_id = self._log_prompt_event(
            messages=messages,
            model=self._model,
            temperature=None,
            purpose=resolved_purpose,
            json_mode=json_mode,
        )
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            **kwargs,
        )
        text = response.choices[0].message.content
        self._log_response_event(
            response_obj=response,
            response_text=text,
            model=self._model,
            purpose=resolved_purpose,
            call_id=call_id,
        )
        return text

    async def probe(self) -> None:
        # .removesuffix() not .rstrip() — rstrip("/v1") strips individual chars
        ollama_root = self._base_url.rstrip("/").removesuffix("/v1")
        try:
            async with httpx.AsyncClient(timeout=5.0) as hc:
                r = await hc.get(f"{ollama_root}/api/tags")
                r.raise_for_status()
                names = [m["name"] for m in r.json().get("models", [])]
        except httpx.ConnectError:
            raise RuntimeError(
                f"Ollama not reachable at {ollama_root}. Run: ollama serve"
            )
        if self._model not in names:
            raise RuntimeError(
                f"Ollama reachable but model {self._model!r} not loaded. "
                f"Run: ollama pull {self._model}"
            )

    async def close(self) -> None:
        await self._client.close()
