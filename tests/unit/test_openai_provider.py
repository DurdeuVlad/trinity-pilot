from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from trinity_pilot.llm.base import LLMMessage
from trinity_pilot.llm.openai import _messages_to_input
from trinity_pilot.workers.agentic_mixin import _finish_decl, _make_tool


def _response(*, text: str = "", output=None, tokens: int = 12) -> MagicMock:
    response = MagicMock()
    response.output_text = text
    response.output = output or []
    response.usage.total_tokens = tokens
    return response


class TestOpenAIProvider:
    def test_model_property(self):
        from trinity_pilot.llm.openai import OpenAIProvider

        provider = OpenAIProvider(api_key="fake-key", model="gpt-5.6-luna")

        assert provider.model == "gpt-5.6-luna"

    @pytest.mark.asyncio
    async def test_complete_uses_responses_api(self):
        from trinity_pilot.llm.openai import OpenAIProvider

        with patch("trinity_pilot.llm.openai.OpenAI") as client_cls:
            client = MagicMock()
            client.responses.create.return_value = _response(text="hello")
            client_cls.return_value = client

            result = await OpenAIProvider(
                api_key="fake-key", model="gpt-5.6-luna"
            ).complete(
                [LLMMessage(role="user", content="say hello")],
                system="Be concise.",
            )

        request = client.responses.create.call_args.kwargs
        assert request["model"] == "gpt-5.6-luna"
        assert request["instructions"] == "Be concise."
        assert result.content == "hello"
        assert result.token_count == 12

    @pytest.mark.asyncio
    async def test_complete_with_tools_returns_function_call(self):
        from trinity_pilot.llm.openai import OpenAIProvider

        function_call = SimpleNamespace(
            type="function_call",
            name="finish",
            arguments='{"status":"success","summary":"done"}',
            call_id="call_123",
        )
        with patch("trinity_pilot.llm.openai.OpenAI") as client_cls:
            client = MagicMock()
            client.responses.create.return_value = _response(output=[function_call])
            client_cls.return_value = client

            result = await OpenAIProvider(api_key="fake-key").complete_with_tools(
                [LLMMessage(role="user", content="finish the task")],
                [_make_tool([_finish_decl])],
            )

        assert result.tool_calls == [
            {
                "name": "finish",
                "args": {"status": "success", "summary": "done"},
                "call_id": "call_123",
            }
        ]
        tool = client.responses.create.call_args.kwargs["tools"][0]
        assert tool["type"] == "function"
        assert tool["name"] == "finish"
        assert tool["parameters"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_tool_result_history_preserves_call_id(self):
        from trinity_pilot.llm.openai import OpenAIProvider

        with patch("trinity_pilot.llm.openai.OpenAI") as client_cls:
            client = MagicMock()
            client.responses.create.return_value = _response(text="ok")
            client_cls.return_value = client

            await OpenAIProvider(api_key="fake-key").complete(
                [
                    LLMMessage(role="user", content="do it"),
                    LLMMessage(
                        role="tool_call",
                        content='{"name":"finish","args":{}}',
                        tool_call_id="call_123",
                    ),
                    LLMMessage(
                        role="tool_result",
                        content='{"name":"finish","result":"done"}',
                        tool_call_id="call_123",
                    ),
                ]
            )

        inputs = client.responses.create.call_args.kwargs["input"]
        assert inputs[-2]["type"] == "function_call"
        assert inputs[-2]["call_id"] == "call_123"
        assert inputs[-1] == {
            "type": "function_call_output",
            "call_id": "call_123",
            "output": "done",
        }

    @pytest.mark.asyncio
    async def test_tool_result_screenshot_is_preserved_as_image_input(self):
        from trinity_pilot.llm.openai import OpenAIProvider

        with patch("trinity_pilot.llm.openai.OpenAI") as client_cls:
            client = MagicMock()
            client.responses.create.return_value = _response(text="seen")
            client_cls.return_value = client

            await OpenAIProvider(api_key="fake-key").complete(
                [
                    LLMMessage(
                        role="tool_result",
                        content='{"name":"screenshot","result":"captured"}',
                        image_data=b"png-bytes",
                        image_mime="image/png",
                        tool_call_id="call_123",
                    )
                ]
            )

        inputs = client.responses.create.call_args.kwargs["input"]
        assert inputs[0]["type"] == "function_call_output"
        assert inputs[1]["content"][1] == {
            "type": "input_image",
            "image_url": "data:image/png;base64,cG5nLWJ5dGVz",
        }

    def test_reasoning_and_function_output_items_are_replayed(self):
        message = LLMMessage(
            role="tool_call",
            content='{"name":"finish","args":{}}',
            raw_provider_content=[
                {"type": "reasoning", "id": "rs_123", "summary": []},
                {"type": "function_call", "call_id": "call_123", "name": "finish", "arguments": "{}"},
            ],
            tool_call_id="call_123",
        )

        assert _messages_to_input([message]) == message.raw_provider_content
