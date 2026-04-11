"""Provider factory — creates the configured LLM provider from settings."""
from __future__ import annotations

import os

from .base import LLMProvider


def make_provider(provider_name: str, api_key: str) -> LLMProvider:
    """Instantiate the correct LLMProvider for the given name and key.

    Args:
        provider_name: "gemini" or "openai" (case-insensitive).
        api_key: The API key for the selected provider.  When empty, the
            matching environment variable is used as a fallback.

    Raises:
        ValueError: If provider_name is not recognised.
        ImportError: If the required SDK for the provider is not installed.
    """
    name = (provider_name or "gemini").lower().strip()

    if name == "gemini":
        resolved = api_key or os.getenv("GEMINI_API_KEY", "")
        if resolved == "mock":
            from .mock_provider import MockProvider
            return MockProvider()
        # Disable cache when running under the Gemini mock test harness
        mock_mode = bool(os.getenv("GEMINI_MOCK", ""))
        from .cache import make_cache
        from .gemini_provider import GeminiProvider
        cache = make_cache(enabled=not mock_mode)
        return GeminiProvider(api_key=resolved, cache=cache)

    # OpenAI provider disabled — using Gemini only.
    # if name in ("openai", "chatgpt"):
    #     from .openai_provider import OpenAIProvider
    #     return OpenAIProvider(api_key=api_key)

    raise ValueError(
        f"Unknown AI provider: {provider_name!r}. "
        "Valid values are 'gemini' and 'openai'."
    )
