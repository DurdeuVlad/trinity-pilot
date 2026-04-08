"""Simplified provider for module services - uses OpenAI synchronously."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ModuleServiceProvider:
    """Synchronous OpenAI provider for module services (browser, desktop, CLI).
    
    Module services use a simpler synchronous pattern with direct OpenAI client.
    This is intentional - they don't need the full async strategy pattern complexity.
    """

    # 2026 Model Options:
    # - gpt-5.4-mini: Balanced choice, strong tool calling, safer for messy tasks ($0.75/$4.50 per 1M)
    # - gpt-5-nano: Ultra-cheap, best for tight prompts + clean tools ($0.05/$0.40 per 1M)
    MODEL = "gpt-5.4-mini"  # Default: balanced choice
    MODEL_NANO = "gpt-5-nano"  # Alternative: ultra-cheap mode
    
    def __init__(self, api_key: str, *, use_nano: bool = False) -> None:
        """Initialize synchronous OpenAI client for module service use.
        
        Args:
            api_key: OpenAI API key
            
        Raises:
            ImportError: If openai package is not installed
        """
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "openai is required for ModuleServiceProvider. "
                "Install it with: pip install openai"
            ) from exc
        
        self._client = OpenAI(api_key=api_key)
    
    @property
    def client(self):
        """Get the underlying OpenAI client for direct use in module services."""
        return self._client
    
    @property
    def model(self) -> str:
        """Get the selected model name (gpt-5.4-mini or gpt-5-nano)."""
        return self._model


def make_module_service_provider(api_key: str, *, use_nano: bool = False) -> ModuleServiceProvider:
    """Factory function to create a module service provider.
    
    This provides a consistent interface and makes it easy to swap providers
    in the future if needed (e.g., to support Gemini in module services).
    
    Args:
        api_key: OpenAI API key
        use_nano: If True, use gpt-5-nano for ultra-cheap mode. Recommended only
                 if your system prompts are tight and tools return clean results.
                 Set via environment variable: EXECUTOR_USE_NANO=true
        
    Returns:
        ModuleServiceProvider instance configured with OpenAI
    """
    return ModuleServiceProvider(api_key=api_key, use_nano=use_nano)
