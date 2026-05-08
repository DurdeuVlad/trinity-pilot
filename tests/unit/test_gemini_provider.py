"""GeminiProvider unit tests — no live API calls."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGeminiProviderModel:
    def test_model_property_returns_model_name(self):
        with patch("google.generativeai.configure"):
            from trinity_pilot.llm.gemini import GeminiProvider
            provider = GeminiProvider(api_key="fake-key", model="gemini-2.0-flash")
        assert provider.model == "gemini-2.0-flash"

    def test_model_property_default(self):
        with patch("google.generativeai.configure"):
            from trinity_pilot.llm.gemini import GeminiProvider
            provider = GeminiProvider(api_key="fake-key")
        # Default model is gemini-1.5-pro (constructor default) — just verify it's a string
        assert isinstance(provider.model, str)
        assert len(provider.model) > 0

    def test_model_property_custom_value(self):
        with patch("google.generativeai.configure"):
            from trinity_pilot.llm.gemini import GeminiProvider
            provider = GeminiProvider(api_key="fake-key", model="gemini-custom-test")
        assert provider.model == "gemini-custom-test"


class TestGeminiProviderCompleteWithTools:
    async def test_complete_with_tools_returns_tool_calls(self):
        import asyncio

        # Build a fake response with a function_call part
        fake_fn_call = MagicMock()
        fake_fn_call.name = "browser_click"
        fake_fn_call.args = {"selector": "#submit"}

        fake_part = MagicMock()
        fake_part.function_call = fake_fn_call

        fake_response = MagicMock()
        fake_response.parts = [fake_part]
        fake_response.text = ""

        fake_chat = MagicMock()
        fake_chat.send_message = MagicMock(return_value=fake_response)

        fake_model = MagicMock()
        fake_model.start_chat = MagicMock(return_value=fake_chat)

        with patch("google.generativeai.configure"):
            with patch("google.generativeai.GenerativeModel", return_value=fake_model):
                from trinity_pilot.llm.gemini import GeminiProvider
                from trinity_pilot.llm.base import LLMMessage
                provider = GeminiProvider(api_key="fake-key", model="gemini-2.0-flash")
                result = await provider.complete_with_tools(
                    messages=[LLMMessage(role="user", content="click submit")],
                    tools=[{"name": "browser_click"}],
                )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "browser_click"
        assert result.tool_calls[0]["args"] == {"selector": "#submit"}

    async def test_complete_with_tools_empty_messages_raises(self):
        with patch("google.generativeai.configure"):
            from trinity_pilot.llm.gemini import GeminiProvider
            provider = GeminiProvider(api_key="fake-key")
        with pytest.raises(ValueError, match="messages"):
            await provider.complete_with_tools(messages=[], tools=[])


class TestGeminiProviderCompleteWithToolsNoToolCalls:
    async def test_no_function_call_parts_returns_empty_tool_calls(self):
        # Parts with no function_call attribute (or function_call is None)
        fake_part = MagicMock(spec=[])  # no function_call attribute
        fake_response = MagicMock()
        fake_response.parts = [fake_part]
        fake_response.text = "just a plain response"

        fake_chat = MagicMock()
        fake_chat.send_message = MagicMock(return_value=fake_response)
        fake_model = MagicMock()
        fake_model.start_chat = MagicMock(return_value=fake_chat)

        with patch("google.generativeai.configure"):
            with patch("google.generativeai.GenerativeModel", return_value=fake_model):
                from trinity_pilot.llm.gemini import GeminiProvider
                from trinity_pilot.llm.base import LLMMessage
                provider = GeminiProvider(api_key="fake-key", model="gemini-2.0-flash")
                result = await provider.complete_with_tools(
                    messages=[LLMMessage(role="user", content="hello")],
                    tools=[],
                )

        assert result.tool_calls == []
        assert result.content == "just a plain response"


class TestGeminiProviderCompleteEmptyMessages:
    async def test_complete_empty_messages_raises_value_error(self):
        with patch("google.generativeai.configure"):
            from trinity_pilot.llm.gemini import GeminiProvider
            provider = GeminiProvider(api_key="fake-key")
        with pytest.raises(ValueError, match="messages"):
            await provider.complete(messages=[])


class TestGeminiProviderSystemInstruction:
    async def test_complete_passes_system_instruction_to_model(self):
        from unittest.mock import call

        fake_response = MagicMock()
        fake_response.text = "ok"
        fake_chat = MagicMock()
        fake_chat.send_message = MagicMock(return_value=fake_response)
        fake_model_instance = MagicMock()
        fake_model_instance.start_chat = MagicMock(return_value=fake_chat)

        with patch("google.generativeai.configure"):
            with patch("google.generativeai.GenerativeModel", return_value=fake_model_instance) as mock_gen_model:
                from importlib import reload
                import trinity_pilot.llm.gemini as gem_mod
                reload(gem_mod)
                from trinity_pilot.llm.gemini import GeminiProvider
                from trinity_pilot.llm.base import LLMMessage
                provider = GeminiProvider(api_key="fake-key", model="gemini-2.0-flash")
                await provider.complete(
                    messages=[LLMMessage(role="user", content="hello")],
                    system="You are helpful",
                )

        mock_gen_model.assert_called_once_with(
            "gemini-2.0-flash",
            system_instruction="You are helpful",
        )
