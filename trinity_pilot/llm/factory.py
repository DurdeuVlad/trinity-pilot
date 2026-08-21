"""Provider selection shared by the orchestrator, workers, and UI."""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from trinity_pilot.llm.base import LLMProvider
from trinity_pilot.llm.gemini import GeminiProvider
from trinity_pilot.llm.openai import OpenAIProvider


def create_provider(
    provider: str,
    api_key: str,
    model: str,
    default_timeout: float | None = None,
) -> LLMProvider:
    normalized = provider.strip().lower()
    if normalized == "openai":
        return OpenAIProvider(api_key=api_key, model=model, default_timeout=default_timeout)
    if normalized == "gemini":
        return GeminiProvider(api_key=api_key, model=model, default_timeout=default_timeout)
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}. Use 'openai' or 'gemini'.")


def create_provider_for_settings(settings: Any, role: str = "worker") -> LLMProvider:
    if settings.llm_provider == "openai":
        model = settings.openai_model
        api_key = settings.openai_api_key
        timeout = settings.openai_timeout_seconds
    else:
        model = settings.gemini_planner_model if role == "planner" else settings.gemini_worker_model
        api_key = settings.gemini_api_key
        timeout = settings.gemini_timeout_seconds
    return create_provider(settings.llm_provider, api_key, model, timeout)


def create_provider_from_env(role: str = "worker") -> LLMProvider:
    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider:
        provider = "openai" if os.getenv("OPENAI_API_KEY") else "gemini"
    if provider not in {"openai", "gemini"}:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}. Use 'openai' or 'gemini'.")
    if provider == "openai":
        return create_provider(
            provider,
            os.getenv("OPENAI_API_KEY", ""),
            os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
            float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120")),
        )
    return create_provider(
        provider,
        os.getenv("GEMINI_API_KEY", ""),
        os.getenv(
            "GEMINI_PLANNER_MODEL" if role == "planner" else "GEMINI_WORKER_MODEL",
            "gemini-2.5-flash",
        ),
        float(os.getenv("GEMINI_TIMEOUT_SECONDS", "120")),
    )
