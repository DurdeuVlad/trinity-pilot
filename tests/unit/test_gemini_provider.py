"""GeminiProvider unit tests — no live API calls."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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
