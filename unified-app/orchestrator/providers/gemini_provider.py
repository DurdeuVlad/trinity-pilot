"""Gemini LLM provider using the google-genai SDK."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .base import LLMProvider

if TYPE_CHECKING:
    from .cache import SmartCache

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Gemini backend via google-genai async client."""

    MODEL = "models/gemini-3.1-flash-lite-preview"  # 2026: Ultra-cheap agentic model, 1M context, $0.125/$0.75 per 1M tokens
    PROBE_PROMPT = "Reply with the single word OK."

    def __init__(self, api_key: str, *, cache: "SmartCache | None" = None) -> None:
        try:
            from google import genai
            from google.genai import types as genai_types
        except (ImportError, AttributeError):
            try:
                import google.generativeai as genai
                from google.generativeai import types as genai_types
            except ImportError as exc:
                raise ImportError(
                "google-genai is required for GeminiProvider. "
                "Install it with: pip install google-genai"
            ) from exc

        self._genai = genai
        self._types = genai_types
        self._client = genai.Client(api_key=api_key)
        self.cache: SmartCache | None = cache
        self._last_cache_key: str | None = None

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def call(
        self,
        messages: list[dict],
        *,
        json_mode: bool = True,
        purpose: str | None = None,
        force_bypass: bool = False,
    ) -> str:
        """Send messages to Gemini and return response text.

        Checks the SmartCache before hitting the API when a cache is attached.
        Stores the response in cache after a live API call (success gate applied
        inside SmartCache.set()).

        Args:
            messages: OpenAI-style message list.
            json_mode: When True, request JSON MIME type from Gemini.
            force_bypass: Skip cache lookup for this call; may still write to
                cache if the fresh response is cacheable.
        """
        # ── Cache read ────────────────────────────────────────────────────────
        if self.cache is not None:
            cached_response, cache_key = self.cache.get(
                messages, self.MODEL, force_bypass=force_bypass
            )
            self._last_cache_key = cache_key
            if cached_response is not None:
                return cached_response

        # ── Live API call ─────────────────────────────────────────────────────
        system_instruction = next(
            (m["content"] for m in messages if m["role"] == "system"), None
        )
        contents = [
            self._types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[self._types.Part(text=m["content"])],
            )
            for m in messages
            if m["role"] in ("user", "assistant")
        ]

        config = self._types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
            response_mime_type="application/json" if json_mode else "text/plain",
        )

        resolved_purpose = purpose or self._infer_purpose(messages)
        call_id = self._log_prompt_event(
            messages=messages,
            model=self.MODEL,
            temperature=0.2,
            purpose=resolved_purpose,
            json_mode=json_mode,
        )
        started = time.perf_counter()
        response = await self._client.aio.models.generate_content(
            model=self.MODEL,
            contents=contents,
            config=config,
        )
        text = response.text
        self._log_response_event(
            response_obj=response,
            response_text=text,
            model=self.MODEL,
            purpose=resolved_purpose,
            call_id=call_id,
            latency_ms={"total": max(1, int((time.perf_counter() - started) * 1000))},
        )

        # ── Cache write ───────────────────────────────────────────────────────
        if self.cache is not None and self._last_cache_key is not None:
            self.cache.set(
                self._last_cache_key,
                text,
                self.MODEL,
                is_action_call=not json_mode,
            )

        return text

    def report_cache_failure(self) -> None:
        """Signal that the most recent cached response caused a downstream failure.

        Call this when the orchestrator detects that the LLM response (which may
        have been served from cache) led to a failed objective.  SmartCache will
        increment the entry's failure_count and evict it once the bypass threshold
        is reached, forcing the next call to hit the live API.
        """
        if self.cache is not None and self._last_cache_key is not None:
            self.cache.report_failure(self._last_cache_key)

    @property
    def cache_stats(self) -> dict | None:
        """Return cache statistics, or None if no cache is attached."""
        return self.cache.get_stats() if self.cache is not None else None

    async def probe(self) -> None:
        """Cheap liveness check — one minimal Gemini call."""
        response = await self._client.aio.models.generate_content(
            model=self.MODEL,
            contents=self.PROBE_PROMPT,
        )
        if not getattr(response, "text", "").strip():
            raise ValueError("Gemini probe returned an empty response.")
        logger.debug("Gemini probe OK: %s", response.text.strip()[:20])

    async def close(self) -> None:
        """Close the async Gemini client before the worker loop exits."""
        aio_client = getattr(self._client, "aio", None)
        aio_close = getattr(aio_client, "aclose", None)
        sync_close = getattr(self._client, "close", None)

        if callable(aio_close):
            await aio_close()
        if callable(sync_close):
            sync_close()
