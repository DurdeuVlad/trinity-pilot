"""Snapshot-style tests for prompt registry consistency (UA-S7).

Guards against duplicate or conflicting retry/error-handling guidance
across provider prompts for planner and executor phases.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.prompt_registry import (
    PromptRegistry,
    _ACTION_ERROR_HANDLING_RULES,
)


# ── Canonical block is shared ──────────────────────────────────────────────

def test_canonical_error_rules_not_empty() -> None:
    assert "retry" in _ACTION_ERROR_HANDLING_RULES.lower()
    assert "infeasible" in _ACTION_ERROR_HANDLING_RULES.lower()


def test_gemini_action_prompt_contains_canonical_rules() -> None:
    reg = PromptRegistry("gemini")
    prompt = reg.action_system_prompt()
    assert _ACTION_ERROR_HANDLING_RULES in prompt


def test_openai_action_prompt_contains_canonical_rules() -> None:
    reg = PromptRegistry("openai")
    prompt = reg.action_system_prompt()
    assert _ACTION_ERROR_HANDLING_RULES in prompt


# ── No inline duplication ──────────────────────────────────────────────────

def test_gemini_action_prompt_error_handling_appears_once() -> None:
    """The canonical block must not be duplicated in the Gemini action prompt."""
    prompt = PromptRegistry("gemini").action_system_prompt()
    assert prompt.count("Error-handling rules:") == 1


def test_openai_action_prompt_error_handling_appears_once() -> None:
    prompt = PromptRegistry("openai").action_system_prompt()
    assert prompt.count("Error-handling rules:") == 1


# ── No conflicting retry guidance in planner prompts ──────────────────────

def test_gemini_replan_prompt_has_no_retry_contradiction() -> None:
    """Replan prompt must not instruct the LLM to retry failed objectives."""
    prompt = PromptRegistry("gemini").replan_system_prompt()
    # The replan prompt should not tell the LLM to retry — only to revise
    assert "retry it once" not in prompt.lower()


def test_openai_replan_prompt_has_no_retry_contradiction() -> None:
    prompt = PromptRegistry("openai").replan_system_prompt()
    assert "retry it once" not in prompt.lower()


def test_gemini_decompose_prompt_has_no_retry_contradiction() -> None:
    """Decompose prompt must not inject error-handling retry rules."""
    prompt = PromptRegistry("gemini").decompose_system_prompt()
    assert "retry it once" not in prompt.lower()
    assert "Error-handling rules:" not in prompt


def test_openai_decompose_prompt_has_no_retry_contradiction() -> None:
    prompt = PromptRegistry("openai").decompose_system_prompt()
    assert "retry it once" not in prompt.lower()
    assert "Error-handling rules:" not in prompt


# ── Provider fallback ──────────────────────────────────────────────────────

def test_unknown_provider_falls_back_to_openai() -> None:
    reg = PromptRegistry("anthropic")
    assert reg.provider_name == "openai"
    assert _ACTION_ERROR_HANDLING_RULES in reg.action_system_prompt()


# ── Style conventions preserved ───────────────────────────────────────────

def test_gemini_action_prompt_contains_schema_field_rationale() -> None:
    prompt = PromptRegistry("gemini").action_system_prompt()
    assert '"rationale"' in prompt


def test_openai_action_prompt_contains_schema_field_rationale() -> None:
    prompt = PromptRegistry("openai").action_system_prompt()
    assert '"rationale"' in prompt


def test_both_providers_reflection_prompt_has_achieved_field() -> None:
    for name in ("gemini", "openai"):
        prompt = PromptRegistry(name).reflection_system_prompt()
        assert '"achieved"' in prompt, f"{name} reflection prompt missing 'achieved'"
