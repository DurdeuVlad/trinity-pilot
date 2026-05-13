"""Tests for migrated GeminiProvider using google.genai async client (AC-1.2)."""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.llm.base import LLMMessage, LLMResponse


def make_mock_response(text: str = "result", total_tokens: int = 42) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.usage_metadata = MagicMock()
    response.usage_metadata.total_token_count = total_tokens
    response.candidates = []
    return response


@pytest.fixture
def provider():
    with patch("trinity_pilot.llm.gemini.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        yield GeminiProvider(api_key="fake-key", model="gemini-2.0-flash"), mock_client


def test_complete_returns_token_count(provider):
    gemini, mock_client = provider
    mock_response = make_mock_response(total_tokens=99)
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    result = asyncio.run(gemini.complete([LLMMessage(role="user", content="hello")]))
    assert isinstance(result, LLMResponse)
    assert result.token_count == 99
    assert result.content == "result"


def test_complete_uses_wait_for_timeout(provider):
    """asyncio.wait_for is used -- a hung coroutine raises TimeoutError."""
    gemini, mock_client = provider

    async def hang(*args, **kwargs):
        await asyncio.sleep(9999)

    mock_client.aio.models.generate_content = AsyncMock(side_effect=hang)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            gemini.complete(
                [LLMMessage(role="user", content="hello")],
                timeout=0.01,
            )
        )


def test_complete_token_count_zero_when_usage_metadata_missing(provider):
    gemini, mock_client = provider
    mock_response = make_mock_response()
    mock_response.usage_metadata = None
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    result = asyncio.run(gemini.complete([LLMMessage(role="user", content="hello")]))
    assert result.token_count == 0


def test_complete_does_not_use_to_thread(provider):
    """Ensure no asyncio.to_thread usage -- native async only."""
    import trinity_pilot.llm.gemini as gemini_module
    import inspect
    source = inspect.getsource(gemini_module)
    assert "to_thread" not in source, "gemini.py must not use asyncio.to_thread"
