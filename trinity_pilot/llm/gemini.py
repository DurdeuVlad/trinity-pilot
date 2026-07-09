from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse

_MAX_RETRIES = 2
_RETRY_BACKOFF_S = 1.5


def _generate_with_retry(call: Callable[[], Any]) -> Any:
    """Retry a blocking generate_content call on transient server overload.

    Gemini returns 503 UNAVAILABLE ("high demand") under sustained load, which
    is common when running large evaluation suites back-to-back. Retrying with
    a short backoff clears most of these without surfacing a planning failure.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return call()
        except genai_errors.ServerError as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_S * (attempt + 1))
                continue
            raise
    raise last_exc  # pragma: no cover — unreachable, satisfies type checkers


def _build_contents(messages: list[LLMMessage]) -> list[genai_types.Content]:
    """Convert LLMMessage list to Gemini Content objects.

    Supported roles:
      "user"        → user text Part
      "model"       → model text Part
      "tool_call"   → model FunctionCall Part  (content = JSON {"name":..,"args":..})
      "tool_result" → user FunctionResponse Part (content = JSON {"name":..,"result":..})

    Using proper FunctionCall/FunctionResponse parts ensures the model sees its
    tool invocations in the correct Gemini multi-turn format and does not
    imitate the "[tool_call]:" text pattern from conversation history.
    """
    contents = []
    for msg in messages:
        if msg.role == "tool_call":
            # Gemini 2.5+ thinking models attach thought_signature to function_call
            # Parts.  Reconstructing from JSON loses that opaque blob and causes
            # 400 INVALID_ARGUMENT on the next turn.  When the raw Content object
            # was stored on the message, replay it verbatim — zero reconstruction.
            if msg.raw_provider_content is not None:
                contents.append(msg.raw_provider_content)
                continue
            # Fallback path (older providers / unit-test mocks without raw content):
            # reconstruct from the JSON payload.
            data = json.loads(msg.content)
            parts: list[genai_types.Part] = []
            if thought_text := data.get("thought_text"):
                parts.append(genai_types.Part(thought=True, text=thought_text))
            parts.append(genai_types.Part(
                function_call=genai_types.FunctionCall(
                    name=data["name"],
                    args=data["args"],
                )
            ))
            contents.append(genai_types.Content(role="model", parts=parts))
        elif msg.role == "tool_result":
            data = json.loads(msg.content)
            tool_parts: list[genai_types.Part] = [
                genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name=data["name"],
                        response={"result": data["result"]},
                    )
                )
            ]
            # Attach inline image when the tool result carries one (e.g. take_screenshot).
            # This lets the LLM see the screen and read values like Calculator display.
            if msg.image_data:
                tool_parts.append(genai_types.Part(
                    inline_data=genai_types.Blob(
                        mime_type=msg.image_mime,
                        data=msg.image_data,
                    )
                ))
            contents.append(genai_types.Content(role="user", parts=tool_parts))
        else:
            role = "model" if msg.role == "model" else "user"
            parts: list[genai_types.Part] = [genai_types.Part(text=msg.content)]
            if msg.image_data:
                parts.append(genai_types.Part(
                    inline_data=genai_types.Blob(
                        mime_type=msg.image_mime,
                        data=msg.image_data,
                    )
                ))
            contents.append(genai_types.Content(role=role, parts=parts))
    return contents


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        # Real socket-level deadline: without this, a stalled HTTP call run via
        # run_in_executor() keeps the worker thread blocked forever even after
        # asyncio.wait_for() times out on the asyncio side (cancelling that future
        # does not interrupt the underlying thread). Bounding it here means a
        # stuck call eventually dies on its own instead of leaking a thread.
        self._client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(timeout=150_000),
        )
        self._model_name = model

    @property
    def model(self) -> str:
        return self._model_name

    async def complete(
        self,
        messages: list[LLMMessage],
        system: str = "",
        timeout: float = 120.0,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")

        contents = _build_contents(messages)
        config = genai_types.GenerateContentConfig(
            system_instruction=system if system else None,
            # Explicit generous ceiling — seen the planner's JSON response truncated
            # mid-object on a 6-objective plan under the SDK default, causing a hard
            # "Planner returned invalid JSON" failure (HH04, 2026-06-29).
            max_output_tokens=16384,
        )
        # Run in thread so asyncio.wait_for can reliably cancel if needed.
        # google-genai's async client holds HTTP connections open (SSE/chunked),
        # which prevents the event loop from processing cancellations.
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _generate_with_retry(lambda: self._client.models.generate_content(
                    model=self._model_name,
                    contents=contents,
                    config=config,
                )),
            ),
            timeout=timeout,
        )
        token_count = getattr(getattr(response, "usage_metadata", None), "total_token_count", 0) or 0
        # For thinking models (gemini-2.5-pro etc.) response.text may raise ValueError
        # when the response contains thought parts. Extract only non-thought text parts.
        text = ""
        try:
            text = response.text or ""
        except Exception:
            if hasattr(response, "candidates") and response.candidates:
                for part in (getattr(response.candidates[0].content, "parts", None) or []):
                    if not getattr(part, "thought", False):
                        text += getattr(part, "text", "") or ""
        finish_reason = None
        if hasattr(response, "candidates") and response.candidates:
            finish_reason = getattr(response.candidates[0], "finish_reason", None)
        if finish_reason is not None and str(finish_reason) not in ("FinishReason.STOP", "STOP"):
            # #region agent log
            from trinity_pilot.telemetry.trace import emit as _trace_non_stop_finish

            _trace_non_stop_finish(
                "gemini.py:complete",
                "non_stop_finish_reason",
                {
                    "finish_reason": str(finish_reason),
                    "text_len": len(text),
                    "token_count": token_count,
                },
            )
            # #endregion
        return LLMResponse(content=text, raw=response, token_count=token_count)

    async def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        system: str = "",
        timeout: float = 120.0,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")

        contents = _build_contents(messages)
        config = genai_types.GenerateContentConfig(
            system_instruction=system if system else None,
            tools=tools,
        )
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _generate_with_retry(lambda: self._client.models.generate_content(
                    model=self._model_name,
                    contents=contents,
                    config=config,
                )),
            ),
            timeout=timeout,
        )

        tool_calls: list[dict[str, Any]] = []
        raw_model_content: Any = None
        if hasattr(response, "candidates") and response.candidates:
            raw_model_content = response.candidates[0].content
            # content can be None if the candidate finished with no content (e.g. blocked,
            # MAX_TOKENS with nothing generated yet, or other non-STOP finish reasons).
            if raw_model_content is not None:
                for part in (raw_model_content.parts or []):
                    if fn := getattr(part, "function_call", None):
                        tool_calls.append({"name": fn.name, "args": dict(fn.args)})

        # Only access .text when no function_calls — avoids SDK warning about
        # "non-text parts in response: ['function_call']"
        text = ""
        if not tool_calls:
            try:
                text = response.text or ""
            except Exception:
                if hasattr(response, "candidates") and response.candidates:
                    for part in (getattr(response.candidates[0].content, "parts", None) or []):
                        if not getattr(part, "thought", False):
                            text += getattr(part, "text", "") or ""
        token_count = getattr(getattr(response, "usage_metadata", None), "total_token_count", 0) or 0
        if not text and not tool_calls:
            # #region agent log
            from trinity_pilot.telemetry.trace import emit as _trace_empty_response

            finish_reason = None
            safety_ratings = None
            if hasattr(response, "candidates") and response.candidates:
                finish_reason = getattr(response.candidates[0], "finish_reason", None)
                safety_ratings = getattr(response.candidates[0], "safety_ratings", None)
            _trace_empty_response(
                "gemini.py:complete_with_tools",
                "empty_response",
                {
                    "finish_reason": str(finish_reason),
                    "safety_ratings": str(safety_ratings),
                    "token_count": token_count,
                },
            )
            # #endregion
        return LLMResponse(
            content=text,
            raw=response,
            tool_calls=tool_calls,
            token_count=token_count,
            # raw_model_content carries the original Gemini Content object so
            # callers can attach it to LLMMessage.raw_provider_content and replay
            # it verbatim (preserving thought_signature for 2.5+ models).
            raw_model_content=raw_model_content,
        )
