"""OpenAI tool-calling provider for shared MCP strategy runtimes."""

from __future__ import annotations

import json
from typing import Any

from .llm_provider import LLMProvider, LLMResponse, ToolCall


class OpenAIToolCallingProvider(LLMProvider):
    """Use OpenAI chat tool-calling for the shared MCP strategy runtime."""

    def __init__(self, api_key: str, model: str = "gpt-5.4-mini") -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required for the shared MCP strategy runtime.")
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "openai is required for OpenAIToolCallingProvider. Install it with: pip install openai"
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key, timeout=90.0, max_retries=2)
        self.model = model

    async def call(self, messages: list[dict], tools: dict[str, Any]) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": tool.name(),
                        "description": self._tool_description(tool),
                        "parameters": tool.parameters(),
                    },
                }
                for tool in tools.values()
            ],
            tool_choice="auto",
        )
        message = response.choices[0].message
        tool_calls = []
        for tool_call in message.tool_calls or []:
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                ToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=arguments,
                )
            )
        return LLMResponse(text=message.content or "", tool_calls=tool_calls)

    @property
    def provider_name(self) -> str:
        return "openai"

    async def probe(self) -> None:
        """Verify OpenAI API reachability with a minimal call."""
        try:
            await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
        except Exception as exc:
            raise RuntimeError(f"OpenAI probe failed: {exc}") from exc

    async def close(self) -> None:
        await self._client.close()

    def _tool_description(self, tool: Any) -> str:
        description = str(tool.description() or "")
        annotations_method = getattr(tool, "annotations", None)
        if not callable(annotations_method):
            return description
        annotations = annotations_method() or {}
        if not isinstance(annotations, dict) or not annotations:
            return description
        annotation_text = ", ".join(
            f"{key}={value}" for key, value in sorted(annotations.items()) if value is not None
        )
        if not annotation_text:
            return description
        return f"{description} Capability metadata: {annotation_text}."
