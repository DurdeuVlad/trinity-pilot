from __future__ import annotations

import asyncio
from typing import Any

import google.generativeai as genai

from trinity_pilot.llm.base import LLMProvider, LLMMessage, LLMResponse


def _to_genai_history(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    history = []
    for msg in messages:
        role = "model" if msg.role == "model" else "user"
        history.append({"role": role, "parts": [msg.content]})
    return history


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-pro") -> None:
        genai.configure(api_key=api_key)
        self._model_name = model

    def _make_model(
        self,
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> genai.GenerativeModel:
        kwargs: dict[str, Any] = {}
        if system:
            kwargs["system_instruction"] = system
        if tools:
            kwargs["tools"] = tools
        return genai.GenerativeModel(self._model_name, **kwargs)

    async def complete(
        self,
        messages: list[LLMMessage],
        system: str = "",
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")

        history = _to_genai_history(messages[:-1])
        last = messages[-1]

        model = self._make_model(system)
        chat = model.start_chat(history=history)

        response = await asyncio.to_thread(chat.send_message, last.content)
        return LLMResponse(content=response.text, raw=response)

    async def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        system: str = "",
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")

        history = _to_genai_history(messages[:-1])
        last = messages[-1]

        model = self._make_model(system, tools=tools)
        chat = model.start_chat(history=history)

        response = await asyncio.to_thread(chat.send_message, last.content)

        tool_calls: list[dict[str, Any]] = []
        for part in response.parts:
            if fn := getattr(part, "function_call", None):
                tool_calls.append({"name": fn.name, "args": dict(fn.args)})

        text = response.text if hasattr(response, "text") else ""
        return LLMResponse(content=text, raw=response, tool_calls=tool_calls)
