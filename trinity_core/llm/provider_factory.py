"""Factory for production LLM providers used by the shared MCP runtime."""

from __future__ import annotations

from ..config import TrinityConfig
from .llm_provider import LLMProvider
from .openai_tool_provider import OpenAIToolCallingProvider
from .gemini_tool_provider import GeminiToolCallingProvider


def build_runtime_llm_provider(config: TrinityConfig) -> LLMProvider:
    provider_name = (config.ai_provider or "").strip().lower()
    if provider_name == "openai":
        return OpenAIToolCallingProvider(
            api_key=config.openai_api_key,
            model=config.ai_model,
        )
    if provider_name == "gemini":
        return GeminiToolCallingProvider(
            api_key=config.gemini_api_key,
            model=config.ai_model,
        )
    raise ValueError(
        f"Unsupported shared MCP runtime provider '{config.ai_provider}'. "
        "Supported providers: 'openai', 'gemini'"
    )
