"""Regression tests for ReflectionEngine fast paths."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_UNIFIED = REPO_ROOT / "unified-app"
for _p in (str(REPO_ROOT), str(_UNIFIED)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from orchestrator.prompt_registry import PromptRegistry  # noqa: E402
from orchestrator.reflection_engine import ReflectionEngine  # noqa: E402


@pytest.mark.asyncio
async def test_reflection_fast_path_accepts_successful_text_capture() -> None:
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for successful text capture"))
    engine = ReflectionEngine(provider, PromptRegistry("gemini"))

    reflection = await engine.reflect(
        "Copy the first paragraph from the 'Cats' Wikipedia page.",
        "The cat is a domestic species of small carnivorous mammal that is widely kept as a pet.",
        attempt=0,
    )

    assert reflection.achieved is True
    assert reflection.critique is None


@pytest.mark.asyncio
async def test_reflection_fast_path_accepts_successful_title_capture() -> None:
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for successful title capture"))
    engine = ReflectionEngine(provider, PromptRegistry("gemini"))

    reflection = await engine.reflect(
        "Display the title of the first search result.",
        "Welcome to Python.org",
        attempt=0,
    )

    assert reflection.achieved is True
    assert reflection.critique is None


@pytest.mark.asyncio
async def test_reflection_title_capture_rejects_error_wrappers() -> None:
    provider = MagicMock()
    provider.call = AsyncMock(
        return_value='{"achieved": false, "confidence": 0.7, "critique": "The prior attempt returned an error wrapper instead of a page title."}'
    )
    engine = ReflectionEngine(provider, PromptRegistry("gemini"))

    reflection = await engine.reflect(
        "Display the title of the first search result.",
        "ERROR: browser unavailable",
        attempt=0,
    )

    assert reflection.achieved is False
    assert reflection.critique is not None
    assert "ERROR: browser unavailable" in reflection.critique
    provider.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_reflection_fast_path_accepts_successful_python_file_listing() -> None:
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for successful file listing"))
    engine = ReflectionEngine(provider, PromptRegistry("gemini"))

    reflection = await engine.reflect(
        "Identify Python files in the project.",
        "main.py\ntest_live_execution.py\ntest_live_run.py",
        attempt=0,
    )

    assert reflection.achieved is True
    assert reflection.critique is None


@pytest.mark.asyncio
async def test_reflection_fast_path_accepts_human_summary_for_python_file_listing() -> None:
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for summarized file listing"))
    engine = ReflectionEngine(provider, PromptRegistry("gemini"))

    reflection = await engine.reflect(
        "List all Python files in the current working directory.",
        "Listed Python files in the current working directory.",
        attempt=0,
    )

    assert reflection.achieved is True
    assert reflection.critique is None


@pytest.mark.asyncio
async def test_reflection_fast_path_accepts_current_directory_inspection() -> None:
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for directory inspection"))
    engine = ReflectionEngine(provider, PromptRegistry("gemini"))

    reflection = await engine.reflect(
        "Get the current directory path",
        r"C:\\Users\\User\\Documents\\Github\\desktop-ai-poc-modules",
        attempt=0,
    )

    assert reflection.achieved is True
    assert reflection.critique is None


@pytest.mark.asyncio
async def test_reflection_fast_path_accepts_python_version_output() -> None:
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for python version"))
    engine = ReflectionEngine(provider, PromptRegistry("gemini"))

    reflection = await engine.reflect(
        "python --version",
        "Python 3.13.2",
        attempt=0,
    )

    assert reflection.achieved is True
    assert reflection.critique is None


@pytest.mark.asyncio
async def test_reflection_fast_path_accepts_generic_python_version_success_marker() -> None:
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for python version"))
    engine = ReflectionEngine(provider, PromptRegistry("gemini"))

    reflection = await engine.reflect(
        "Find the installed Python version using the CLI",
        "Result 1: success",
        attempt=0,
    )

    assert reflection.achieved is True
    assert reflection.critique is None


@pytest.mark.asyncio
async def test_reflection_fast_path_rejects_explicit_error_results() -> None:
    provider = MagicMock()
    provider.call = AsyncMock(side_effect=AssertionError("LLM should not be called for explicit errors"))
    engine = ReflectionEngine(provider, PromptRegistry("gemini"))

    reflection = await engine.reflect(
        "Open an application called 'NonExistentApp_XYZ123456' and tell me its version number",
        "ERROR: The application 'NonExistentApp_XYZ123456' could not be found. Therefore, its version number cannot be determined.",
        attempt=0,
    )

    assert reflection.achieved is False
    assert reflection.critique is not None
