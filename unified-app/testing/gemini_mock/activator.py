"""Activation helpers that inject the Gemini mock into sys.modules."""
from __future__ import annotations

import os
import sys
import types
import warnings
from importlib import util
from typing import Any

from testing.gemini_mock import mock_genai

_ACTIVE = False
_ORIGINAL_MODULES: dict[str, Any] = {}
_TARGET_KEYS = (
    "google",
    "google.generativeai",
    "google.genai",
    "google.api_core",
    "google.api_core.exceptions",
)


def _ensure_google_namespace() -> types.ModuleType:
    """Return a google namespace module, creating one when absent."""
    google_module = sys.modules.get("google")
    if isinstance(google_module, types.ModuleType):
        return google_module
    google_module = types.ModuleType("google")
    google_module.__path__ = []  # type: ignore[attr-defined]
    sys.modules["google"] = google_module
    return google_module


def _build_google_api_core_stub() -> tuple[types.ModuleType, types.ModuleType]:
    """Build minimal google.api_core modules with catchable exception classes."""
    exceptions_module = types.ModuleType("google.api_core.exceptions")

    class GoogleAPICallError(Exception):
        """Base class for stubbed Google API exceptions."""

    class ResourceExhausted(GoogleAPICallError):
        """Quota exceeded error."""

    class Unauthenticated(GoogleAPICallError):
        """Authentication failure error."""

    class NotFound(GoogleAPICallError):
        """Resource missing error."""

    exceptions_module.GoogleAPICallError = GoogleAPICallError  # type: ignore[attr-defined]
    exceptions_module.ResourceExhausted = ResourceExhausted  # type: ignore[attr-defined]
    exceptions_module.Unauthenticated = Unauthenticated  # type: ignore[attr-defined]
    exceptions_module.NotFound = NotFound  # type: ignore[attr-defined]

    api_core_module = types.ModuleType("google.api_core")
    api_core_module.exceptions = exceptions_module  # type: ignore[attr-defined]
    return api_core_module, exceptions_module


def _snapshot_modules() -> None:
    """Capture the current module objects that activation may replace."""
    _ORIGINAL_MODULES.clear()
    for key in _TARGET_KEYS:
        _ORIGINAL_MODULES[key] = sys.modules.get(key)


def _restore_modules() -> None:
    """Restore the module objects that existed before activation."""
    for key, value in _ORIGINAL_MODULES.items():
        if value is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = value
    _ORIGINAL_MODULES.clear()


def activate(backend: Any = None, env_var: str = "GEMINI_MOCK") -> Any:
    """Inject the mock module into sys.modules and return the active backend."""
    global _ACTIVE
    if _ACTIVE:
        if backend is not None:
            mock_genai.set_backend(backend)
            return backend
        return mock_genai.get_backend()
    if backend is None:
        mode = os.getenv(env_var, "").lower()
        if mode in ("", "1", "true", "queue"):
            from testing.gemini_mock.backends.queue_backend import QueueBackend

            backend = QueueBackend()
        elif mode == "stdio":
            from testing.gemini_mock.backends.stdio_backend import StdioBackend

            backend = StdioBackend()
        elif mode == "http":
            from testing.gemini_mock.server import HttpBackend

            backend = HttpBackend(os.getenv("GEMINI_MOCK_SERVER_URL", "http://localhost:8765"))
        elif mode in ("llm", "claude", "openai"):
            from testing.gemini_mock.backends.llm_backend import LLMBackend

            provider = os.getenv("GEMINI_MOCK_LLM_PROVIDER", "anthropic")
            if mode in ("claude", "openai"):
                provider = "anthropic" if mode == "claude" else "openai"
            backend = LLMBackend(provider=provider)
        else:
            from testing.gemini_mock.backends.queue_backend import QueueBackend

            warnings.warn(
                f"GEMINI_MOCK={mode!r} is not a recognised mode; falling back to QueueBackend",
                stacklevel=2,
            )
            backend = QueueBackend()
    _snapshot_modules()
    google_module = _ensure_google_namespace()
    sys.modules["google.generativeai"] = mock_genai
    google_module.generativeai = mock_genai  # type: ignore[attr-defined]
    sys.modules["google.genai"] = mock_genai
    google_module.genai = mock_genai  # type: ignore[attr-defined]
    if util.find_spec("google.api_core.exceptions") is None:
        api_core_module, exceptions_module = _build_google_api_core_stub()
        sys.modules["google.api_core"] = api_core_module
        sys.modules["google.api_core.exceptions"] = exceptions_module
        google_module.api_core = api_core_module  # type: ignore[attr-defined]
    mock_genai.set_backend(backend)
    _ACTIVE = True
    return backend


def deactivate() -> None:
    """Restore the original module state and clear the active backend."""
    global _ACTIVE
    if not _ACTIVE:
        mock_genai.set_backend(None)
        return
    _restore_modules()
    mock_genai.set_backend(None)
    _ACTIVE = False


def is_active() -> bool:
    """Return whether the Gemini mock is currently active."""
    return _ACTIVE


def maybe_autoactivate(env_var: str = "GEMINI_MOCK") -> None:
    """Activate automatically when the configured environment variable is set."""
    if os.getenv(env_var):
        activate()


maybe_autoactivate()
