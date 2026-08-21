"""OpenAI Responses API provider for text, vision, and function calling."""
from __future__ import annotations

import asyncio
import base64
import json
from enum import Enum
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse

_MAX_RETRIES = 2
_RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)


def _normalise_schema(value: Any) -> Any:
    if isinstance(value, Enum):
        return str(value.value).lower()
    if isinstance(value, dict):
        return {key: _normalise_schema(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise_schema(item) for item in value]
    return value


def _to_openai_tools(tools: list[Any]) -> list[dict[str, Any]]:
    """Convert the existing Gemini declaration objects to Responses tools."""
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, dict):
            declarations = tool.get("function_declarations") or tool.get("functionDeclarations") or []
        else:
            declarations = getattr(tool, "function_declarations", []) or []
        for declaration in declarations:
            if isinstance(declaration, dict):
                data = declaration
            else:
                data = declaration.model_dump(exclude_none=True, by_alias=False)
            converted.append(
                {
                    "type": "function",
                    "name": data["name"],
                    "description": data.get("description", ""),
                    "parameters": _normalise_schema(data.get("parameters", {})),
                }
            )
    return converted


def _serialise_output_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(exclude_none=True, by_alias=True)
    if hasattr(item, "to_dict"):
        return item.to_dict()
    raise TypeError(f"Unsupported OpenAI output item: {type(item)!r}")


def _messages_to_input(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if message.role == "tool_call":
            if message.raw_provider_content:
                raw_items = message.raw_provider_content
                if not isinstance(raw_items, list):
                    raw_items = [raw_items]
                items.extend(_serialise_output_item(item) for item in raw_items)
                continue
            data = json.loads(message.content)
            items.append(
                {
                    "type": "function_call",
                    "call_id": message.tool_call_id or f"call_{index}",
                    "name": data["name"],
                    "arguments": json.dumps(data.get("args", {})),
                }
            )
            continue
        if message.role == "tool_result":
            data = json.loads(message.content)
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id or f"call_{index}",
                    "output": str(data.get("result", "")),
                }
            )
            if message.image_data:
                image_url = "data:{0};base64,{1}".format(
                    message.image_mime,
                    base64.b64encode(message.image_data).decode("ascii"),
                )
                items.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Screenshot from the tool result."},
                            {"type": "input_image", "image_url": image_url},
                        ],
                    }
                )
            continue

        role = "assistant" if message.role == "model" else message.role
        if message.image_data:
            image_url = "data:{0};base64,{1}".format(
                message.image_mime,
                base64.b64encode(message.image_data).decode("ascii"),
            )
            content: Any = [
                {"type": "input_text", "text": message.content},
                {"type": "input_image", "image_url": image_url},
            ]
        else:
            content = message.content
        items.append({"role": role, "content": content})
    return items


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.6-luna",
        default_timeout: float | None = None,
    ) -> None:
        self._api_key = api_key
        self._model_name = model
        self._client: OpenAI | None = None
        self._default_timeout = float(default_timeout) if default_timeout is not None else 120.0

    @property
    def model(self) -> str:
        return self._model_name

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    async def _create_response(self, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return await asyncio.to_thread(
                    lambda: self._get_client().responses.create(**kwargs)
                )
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise
        raise last_error or RuntimeError("OpenAI response failed")

    @staticmethod
    def _token_count(response: Any) -> int:
        return int(getattr(getattr(response, "usage", None), "total_tokens", 0) or 0)

    async def complete(
        self,
        messages: list[LLMMessage],
        system: str = "",
        timeout: float | None = None,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")
        response = await asyncio.wait_for(
            self._create_response(
                model=self._model_name,
                instructions=system or None,
                input=_messages_to_input(messages),
                max_output_tokens=16384,
            ),
            timeout=self._default_timeout if timeout is None else timeout,
        )
        return LLMResponse(
            content=getattr(response, "output_text", "") or "",
            raw=response,
            token_count=self._token_count(response),
        )

    async def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]],
        system: str = "",
        timeout: float | None = None,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")
        response = await asyncio.wait_for(
            self._create_response(
                model=self._model_name,
                instructions=system or None,
                input=_messages_to_input(messages),
                tools=_to_openai_tools(tools),
                max_output_tokens=16384,
            ),
            timeout=self._default_timeout if timeout is None else timeout,
        )
        tool_calls: list[dict[str, Any]] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "function_call":
                continue
            try:
                args = json.loads(getattr(item, "arguments", "{}") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                {
                    "name": item.name,
                    "args": args,
                    "call_id": getattr(item, "call_id", None),
                }
            )
        return LLMResponse(
            content=getattr(response, "output_text", "") or "",
            raw=response,
            tool_calls=tool_calls,
            token_count=self._token_count(response),
            raw_model_content=getattr(response, "output", None),
        )
