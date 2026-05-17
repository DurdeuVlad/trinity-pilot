from __future__ import annotations

import asyncio
import json
from typing import Any

from google import genai
from google.genai import types as genai_types

from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse


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
            contents.append(genai_types.Content(
                role="user",
                parts=[genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name=data["name"],
                        response={"result": data["result"]},
                    )
                )]
            ))
        else:
            role = "model" if msg.role == "model" else "user"
            contents.append(genai_types.Content(
                role=role,
                parts=[genai_types.Part(text=msg.content)]
            ))
    return contents


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self._client = genai.Client(api_key=api_key)
        self._model_name = model

    @property
    def model(self) -> str:
        return self._model_name

    async def complete(
        self,
        messages: list[LLMMessage],
        system: str = "",
        timeout: float = 30.0,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")

        contents = _build_contents(messages)
        config = genai_types.GenerateContentConfig(
            system_instruction=system if system else None,
        )
        coro = self._client.aio.models.generate_content(
            model=self._model_name,
            contents=contents,
            config=config,
        )
        response = await asyncio.wait_for(coro, timeout=timeout)
        token_count = getattr(getattr(response, "usage_metadata", None), "total_token_count", 0) or 0
        return LLMResponse(content=response.text, raw=response, token_count=token_count)

    async def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        system: str = "",
        timeout: float = 30.0,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")

        contents = _build_contents(messages)
        config = genai_types.GenerateContentConfig(
            system_instruction=system if system else None,
            tools=tools,
        )
        coro = self._client.aio.models.generate_content(
            model=self._model_name,
            contents=contents,
            config=config,
        )
        response = await asyncio.wait_for(coro, timeout=timeout)

        tool_calls: list[dict[str, Any]] = []
        raw_model_content: Any = None
        if hasattr(response, "candidates") and response.candidates:
            raw_model_content = response.candidates[0].content
            for part in (raw_model_content.parts or []):
                if fn := getattr(part, "function_call", None):
                    tool_calls.append({"name": fn.name, "args": dict(fn.args)})

        # Only access .text when no function_calls — avoids SDK warning about
        # "non-text parts in response: ['function_call']"
        text = ""
        if not tool_calls:
            text = getattr(response, "text", "") or ""
        token_count = getattr(getattr(response, "usage_metadata", None), "total_token_count", 0) or 0
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
