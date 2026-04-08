"""Synchronous Gemini provider for module services - uses google-genai SDK."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class GeminiModuleProvider:
    """Synchronous Gemini provider for module services (browser, desktop, CLI).
    
    Module services use a simpler synchronous pattern with direct Gemini client.
    This is the default for 2026 until the orchestrator is fully ready.
    """

    # 2026 Model Options:
    # - gemini-3.1-flash-lite-preview: Ultra-cheap, best for high-volume agentic tasks ($0.125/$0.75 per 1M)
    # - gemini-3-flash-preview: Stronger reasoning, still cheap ($0.45/$2.70 per 1M)
    MODEL = "models/gemini-3.1-flash-lite-preview"  # Default: ultra-cheap
    MODEL_FLASH = "models/gemini-3-flash-preview"  # Alternative: stronger reasoning
    
    def __init__(self, api_key: str, *, use_flash: bool = False) -> None:
        """Initialize synchronous Gemini client for module service use.
        
        Args:
            api_key: Gemini API key
            use_flash: If True, use gemini-3-flash-preview (stronger) instead of lite.
                      Only needed for complex reasoning tasks.
            
        Raises:
            ImportError: If google-genai package is not installed
        """
        try:
            from google import genai
            from google.genai import types as genai_types
        except (ImportError, AttributeError):
            try:
                import google.generativeai as genai
                from google.generativeai import types as genai_types
            except ImportError as exc:
                raise ImportError(
                    "google-genai is required for GeminiModuleProvider. "
                    "Install it with: pip install google-genai"
                ) from exc
        
        self._genai = genai
        self._types = genai_types
        self._client = genai.Client(api_key=api_key)
        self._model = self.MODEL_FLASH if use_flash else self.MODEL
    
    @property
    def client(self):
        """Get the underlying Gemini client for direct use in module services."""
        return self._client
    
    @property
    def model(self) -> str:
        """Get the selected model name (gemini-3.1-flash-lite or gemini-3-flash)."""
        return self._model
    
    @property
    def types(self):
        """Get the genai types module for tool/function declarations."""
        return self._types


def make_gemini_module_provider(api_key: str, *, use_flash: bool = False) -> GeminiModuleProvider:
    """Factory function to create a Gemini module service provider.
    
    This is the default provider for module services in 2026 until the orchestrator
    is fully ready. Gemini is dramatically cheaper than OpenAI for high-volume tasks.
    
    Args:
        api_key: Gemini API key
        use_flash: If True, use gemini-3-flash-preview for stronger reasoning.
                  Set via environment variable: EXECUTOR_USE_FLASH=true
        
    Returns:
        GeminiModuleProvider instance configured with Gemini
    """
    return GeminiModuleProvider(api_key=api_key, use_flash=use_flash)
