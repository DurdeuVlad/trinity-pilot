from __future__ import annotations

import asyncio
from typing import Any

from google import genai
from google.genai import types as genai_types

from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse


def _build_contents(messages: list[LLMMessage]) -> list[genai_types.Content]:
    contents = []
    for msg in messages:
        role = "model" if msg.role == "model" else "user"
        contents.append(genai_types.Content(
            role=role,
            parts=[genai_types.Part(text=msg.content)]
        ))
    return contents


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
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
        if hasattr(response, "candidates") and response.candidates:
            for part in (response.candidates[0].content.parts or []):
                if fn := getattr(part, "function_call", None):
                    tool_calls.append({"name": fn.name, "args": dict(fn.args)})

        # Only access .text when no function_calls — avoids SDK warning about
        # "non-text parts in response: ['function_call']"
        text = ""
        if not tool_calls:
            text = getattr(response, "text", "") or ""
        token_count = getattr(getattr(response, "usage_metadata", None), "total_token_count", 0) or 0
        return LLMResponse(content=text, raw=response, tool_calls=tool_calls, token_count=token_count)
