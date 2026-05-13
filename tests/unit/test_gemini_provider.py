"""GeminiProvider unit tests -- no live API calls."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_response(text: str = "ok", parts: list | None = None) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.usage_metadata = MagicMock()
    response.usage_metadata.total_token_count = 12
    if parts is None:
        response.candidates = []
    else:
        candidate = MagicMock()
        candidate.content.parts = parts
        response.candidates = [candidate]
    return response


class TestGeminiProviderModel:
    def test_model_property_returns_model_name(self):
        with patch("trinity_pilot.llm.gemini.genai.Client"):
            from trinity_pilot.llm.gemini import GeminiProvider

            provider = GeminiProvider(api_key="fake-key", model="gemini-2.0-flash")
        assert provider.model == "gemini-2.0-flash"

    def test_model_property_default(self):
        with patch("trinity_pilot.llm.gemini.genai.Client"):
            from trinity_pilot.llm.gemini import GeminiProvider

            provider = GeminiProvider(api_key="fake-key")
        assert isinstance(provider.model, str)
        assert len(provider.model) > 0

    def test_model_property_custom_value(self):
        with patch("trinity_pilot.llm.gemini.genai.Client"):
            from trinity_pilot.llm.gemini import GeminiProvider

            provider = GeminiProvider(api_key="fake-key", model="gemini-custom-test")
        assert provider.model == "gemini-custom-test"


class TestGeminiProviderCompleteWithTools:
    async def test_complete_with_tools_returns_tool_calls(self):
        fake_fn_call = MagicMock()
        fake_fn_call.name = "browser_click"
        fake_fn_call.args = {"selector": "#submit"}

        fake_part = MagicMock()
        fake_part.function_call = fake_fn_call

        with patch("trinity_pilot.llm.gemini.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(
                return_value=_mock_response(text="", parts=[fake_part])
            )
            mock_client_cls.return_value = mock_client

            from trinity_pilot.llm.base import LLMMessage
            from trinity_pilot.llm.gemini import GeminiProvider

            provider = GeminiProvider(api_key="fake-key", model="gemini-2.0-flash")
            result = await provider.complete_with_tools(
                messages=[LLMMessage(role="user", content="click submit")],
                tools=[],
            )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "browser_click"
        assert result.tool_calls[0]["args"] == {"selector": "#submit"}

    async def test_complete_with_tools_empty_messages_raises(self):
        with patch("trinity_pilot.llm.gemini.genai.Client"):
            from trinity_pilot.llm.gemini import GeminiProvider

            provider = GeminiProvider(api_key="fake-key")
        with pytest.raises(ValueError, match="messages"):
            await provider.complete_with_tools(messages=[], tools=[])


class TestGeminiProviderCompleteWithToolsNoToolCalls:
    async def test_no_function_call_parts_returns_empty_tool_calls(self):
        fake_part = MagicMock(spec=[])

        with patch("trinity_pilot.llm.gemini.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(
                return_value=_mock_response(
                    text="just a plain response",
                    parts=[fake_part],
                )
            )
            mock_client_cls.return_value = mock_client

            from trinity_pilot.llm.base import LLMMessage
            from trinity_pilot.llm.gemini import GeminiProvider

            provider = GeminiProvider(api_key="fake-key", model="gemini-2.0-flash")
            result = await provider.complete_with_tools(
                messages=[LLMMessage(role="user", content="hello")],
                tools=[],
            )

        assert result.tool_calls == []
        assert result.content == "just a plain response"

    async def test_complete_with_tools_omits_system_instruction_when_system_empty(self):
        with patch("trinity_pilot.llm.gemini.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response())
            mock_client_cls.return_value = mock_client

            from trinity_pilot.llm.base import LLMMessage
            from trinity_pilot.llm.gemini import GeminiProvider

            provider = GeminiProvider(api_key="fake-key", model="gemini-2.0-flash")
            await provider.complete_with_tools(
                messages=[LLMMessage(role="user", content="hello")],
                tools=[],
                system="",
            )

        config = mock_client.aio.models.generate_content.await_args.kwargs["config"]
        assert config.system_instruction is None


class TestGeminiProviderCompleteEmptyMessages:
    async def test_complete_empty_messages_raises_value_error(self):
        with patch("trinity_pilot.llm.gemini.genai.Client"):
            from trinity_pilot.llm.gemini import GeminiProvider

            provider = GeminiProvider(api_key="fake-key")
        with pytest.raises(ValueError, match="messages"):
            await provider.complete(messages=[])


class TestGeminiProviderSystemInstruction:
    async def test_complete_passes_system_instruction_to_model(self):
        with patch("trinity_pilot.llm.gemini.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response())
            mock_client_cls.return_value = mock_client

            from trinity_pilot.llm.base import LLMMessage
            from trinity_pilot.llm.gemini import GeminiProvider

            provider = GeminiProvider(api_key="fake-key", model="gemini-2.0-flash")
            await provider.complete(
                messages=[LLMMessage(role="user", content="hello")],
                system="You are helpful",
            )

        config = mock_client.aio.models.generate_content.await_args.kwargs["config"]
        assert config.system_instruction == "You are helpful"

    async def test_complete_omits_system_instruction_kwarg_when_system_empty(self):
        with patch("trinity_pilot.llm.gemini.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response())
            mock_client_cls.return_value = mock_client

            from trinity_pilot.llm.base import LLMMessage
            from trinity_pilot.llm.gemini import GeminiProvider

            provider = GeminiProvider(api_key="fake-key", model="gemini-2.0-flash")
            await provider.complete(
                messages=[LLMMessage(role="user", content="hello")],
                system="",
            )

        config = mock_client.aio.models.generate_content.await_args.kwargs["config"]
        assert config.system_instruction is None
