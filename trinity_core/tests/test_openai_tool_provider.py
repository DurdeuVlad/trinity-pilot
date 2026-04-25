from __future__ import annotations

import sys
import types

from trinity_core.llm.openai_tool_provider import OpenAIToolCallingProvider
from trinity_core.tools.base import Tool, ToolResult


class _AnnotatedTool(Tool):
    def name(self) -> str:
        return "inspect"

    def description(self) -> str:
        return "Inspect application state."

    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def annotations(self) -> dict:
        return {"readOnlyHint": True, "idempotentHint": True}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", output="")


class _FakeCompletions:
    def __init__(self) -> None:
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="done", tool_calls=[]),
                )
            ]
        )


class _FakeAsyncOpenAI:
    def __init__(self, **kwargs) -> None:
        self.chat = types.SimpleNamespace(completions=_FakeCompletions())

    async def close(self) -> None:
        return None


def test_openai_tool_provider_includes_tool_annotations_in_description(monkeypatch):
    fake_openai_module = types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI)
    monkeypatch.setitem(sys.modules, "openai", fake_openai_module)

    provider = OpenAIToolCallingProvider(api_key="test-key", model="gpt-test")
    tool = _AnnotatedTool()

    async def _run():
        await provider.call(messages=[{"role": "user", "content": "inspect"}], tools={tool.name(): tool})
        return provider._client.chat.completions.last_kwargs

    import asyncio

    kwargs = asyncio.run(_run())
    description = kwargs["tools"][0]["function"]["description"]
    assert "Inspect application state." in description
    assert "readOnlyHint=True" in description
    assert "idempotentHint=True" in description
