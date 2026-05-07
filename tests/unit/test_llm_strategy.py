"""Tests for the LLM strategy pattern. Uses a stub provider — no live API calls."""
from __future__ import annotations

import pytest

from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse


class StubProvider(LLMProvider):
    """Deterministic stub for unit tests."""

    def __init__(self, reply: str = "stub reply") -> None:
        self._reply = reply

    async def complete(self, messages: list[LLMMessage], system: str = "") -> LLMResponse:
        return LLMResponse(content=self._reply)

    async def complete_with_tools(
        self, messages: list[LLMMessage], tools: list[dict], system: str = ""
    ) -> LLMResponse:
        return LLMResponse(content=self._reply, tool_calls=[])


class TestLLMProviderInterface:
    async def test_complete_returns_response(self):
        provider: LLMProvider = StubProvider("hello")
        result = await provider.complete([LLMMessage(role="user", content="hi")])
        assert result.content == "hello"

    async def test_complete_with_tools_returns_response(self):
        provider: LLMProvider = StubProvider("tool reply")
        result = await provider.complete_with_tools(
            messages=[LLMMessage(role="user", content="use a tool")],
            tools=[{"name": "search", "description": "search web"}],
        )
        assert result.content == "tool reply"
        assert result.tool_calls == []

    async def test_provider_is_swappable(self):
        """Strategy pattern: callers depend on LLMProvider, not GeminiProvider."""

        async def call_llm(provider: LLMProvider, prompt: str) -> str:
            r = await provider.complete([LLMMessage(role="user", content=prompt)])
            return r.content

        result = await call_llm(StubProvider("42"), "what is 6*7?")
        assert result == "42"

    def test_message_roles(self):
        m = LLMMessage(role="model", content="response")
        assert m.role == "model"
        assert m.content == "response"

    def test_response_defaults(self):
        r = LLMResponse(content="text")
        assert r.raw is None
        assert r.tool_calls == []
