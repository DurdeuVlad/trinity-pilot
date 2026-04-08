"""OpenAI LLM provider using the openai async SDK."""
from __future__ import annotations

import logging

from .base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI (ChatGPT) backend via AsyncOpenAI client."""

    MODEL = "gpt-5.4-mini"  # 2026: Strong coding/subagent model, 400k context, $0.75/$4.50 per 1M tokens
    PROBE_PROMPT = "Reply with the single word OK."

    def __init__(self, api_key: str) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "openai is required for OpenAIProvider. "
                "Install it with: pip install openai"
            ) from exc

        self._client = AsyncOpenAI(
            api_key=api_key,
            timeout=60.0,
            max_retries=3,
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    async def call(self, messages: list[dict], *, json_mode: bool = True) -> str:
        """Send messages to OpenAI and return response text."""
        kwargs: dict = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self._client.chat.completions.create(
            model=self.MODEL,
            messages=messages,
            **kwargs,
        )
        return response.choices[0].message.content

    async def probe(self) -> None:
        """Cheap liveness check — one minimal OpenAI call."""
        response = await self._client.chat.completions.create(
            model=self.MODEL,
            messages=[{"role": "user", "content": self.PROBE_PROMPT}],
            max_tokens=5,
        )
        text = response.choices[0].message.content or ""
        if not text.strip():
            raise ValueError("OpenAI probe returned an empty response.")
        logger.debug("OpenAI probe OK: %s", text.strip()[:20])

    async def close(self) -> None:
        """Close the async OpenAI client before the worker loop exits."""
        await self._client.close()
