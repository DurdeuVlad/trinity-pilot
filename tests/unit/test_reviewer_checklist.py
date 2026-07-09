"""Checklist engine unit tests (C1 generalization) — mocked LLM, mocked sensors."""
from __future__ import annotations

import json

import pytest

from trinity_pilot.core.types import (
    ChecklistItem,
    DomainType,
    FailureReason,
    ObjectiveSpec,
    RiskClass,
)
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.reviewer.checklist import ChecklistEvalError, evaluate_checklist


def _make_spec(checklist: tuple[ChecklistItem, ...] = ()) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="obj-1",
        goal="do the thing",
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=[],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=[],
        evidence_bundle=["stdout"],
        max_attempts=3,
        rollback_or_abort_rule="abort",
        verification_checklist=checklist,
    )


class _QueuedProvider(LLMProvider):
    """Returns one queued JSON reply per `complete()` call, in order."""

    def __init__(self, replies: list[dict]) -> None:
        self._replies = iter(json.dumps(r) for r in replies)
        self.call_count = 0

    async def complete(self, messages: list[LLMMessage], system: str = "") -> LLMResponse:
        self.call_count += 1
        return LLMResponse(content=next(self._replies))

    async def complete_with_tools(self, messages, tools, system=""):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_no_checklist_returns_none():
    provider = _QueuedProvider([])
    result = await evaluate_checklist(_make_spec(), {"stdout": "ok"}, provider)
    assert result is None
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_all_items_malformed_returns_none_no_llm_call():
    checklist = (ChecklistItem(instruction="check it", sensors=()),)  # invalid: no sensors
    provider = _QueuedProvider([])
    result = await evaluate_checklist(_make_spec(checklist), {"stdout": "ok"}, provider)
    assert result is None
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_single_item_pass():
    checklist = (ChecklistItem(instruction="stdout contains ok", sensors=("stdout",)),)
    provider = _QueuedProvider([{"passed": True, "notes": "matches"}])
    result = await evaluate_checklist(_make_spec(checklist), {"stdout": "ok"}, provider)
    assert result is not None
    assert result.passed is True
    assert result.failure_reason is None


@pytest.mark.asyncio
async def test_single_item_fail_vetoes_objective():
    checklist = (ChecklistItem(instruction="stdout contains ok", sensors=("stdout",)),)
    provider = _QueuedProvider([{"passed": False, "notes": "stdout was empty"}])
    result = await evaluate_checklist(_make_spec(checklist), {"stdout": ""}, provider)
    assert result is not None
    assert result.passed is False
    assert result.failure_reason == FailureReason.FAILED_ASSERTION
    assert "stdout contains ok" in result.notes


@pytest.mark.asyncio
async def test_one_failing_item_among_several_vetoes_objective():
    checklist = (
        ChecklistItem(instruction="stdout contains ok", sensors=("stdout",)),
        ChecklistItem(instruction="exit code is zero", sensors=("exit_code",)),
    )
    # Order of completion across asyncio.TaskGroup tasks is not guaranteed to
    # match list order, so both replies must be valid regardless of which
    # item's coroutine resolves first.
    provider = _QueuedProvider([
        {"passed": True, "notes": "ok"},
        {"passed": False, "notes": "exit code was 1"},
    ])
    result = await evaluate_checklist(
        _make_spec(checklist), {"stdout": "ok", "exit_code": 1}, provider
    )
    assert result is not None
    assert result.passed is False


@pytest.mark.asyncio
async def test_malformed_item_skipped_alongside_valid_one():
    checklist = (
        ChecklistItem(instruction="", sensors=("stdout",)),  # invalid: no instruction
        ChecklistItem(instruction="stdout contains ok", sensors=("stdout",)),
    )
    provider = _QueuedProvider([{"passed": True, "notes": "ok"}])
    result = await evaluate_checklist(_make_spec(checklist), {"stdout": "ok"}, provider)
    assert result is not None
    assert result.passed is True
    assert "1 malformed checklist item(s) skipped" in result.notes


@pytest.mark.asyncio
async def test_missing_sensor_data_still_calls_llm_with_empty_data():
    checklist = (ChecklistItem(instruction="check a sensor that never ran", sensors=("never_ran",)),)
    provider = _QueuedProvider([{"passed": False, "insufficient_data": True, "notes": "no data present"}])
    result = await evaluate_checklist(_make_spec(checklist), {"stdout": "ok"}, provider)
    assert result is not None
    # Regression: an unanswerable item (planner under-specified sensors) must not
    # veto the objective — found via a real VM run where this exact shape caused
    # a genuinely successful task to fail 3/3 attempts (see 2026-06-29 audit).
    assert result.passed is True


@pytest.mark.asyncio
async def test_insufficient_data_item_does_not_veto_alongside_passing_items():
    checklist = (
        ChecklistItem(instruction="file exists", sensors=("created_files",)),
        ChecklistItem(instruction="content is exactly X", sensors=("created_files",)),
    )
    provider = _QueuedProvider([
        {"passed": True, "notes": "file is present"},
        {"passed": False, "insufficient_data": True, "notes": "sensor only proves existence, not content"},
    ])
    result = await evaluate_checklist(
        _make_spec(checklist), {"created_files": ["C:/x/y.txt"]}, provider
    )
    assert result is not None
    assert result.passed is True
    assert "inconclusive" in result.notes


@pytest.mark.asyncio
async def test_real_answered_failure_still_vetoes_even_with_other_inconclusive_items():
    checklist = (
        ChecklistItem(instruction="file exists", sensors=("created_files",)),
        ChecklistItem(instruction="content is exactly X", sensors=("created_files",)),
    )
    provider = _QueuedProvider([
        {"passed": False, "notes": "file is genuinely missing"},
        {"passed": False, "insufficient_data": True, "notes": "sensor only proves existence, not content"},
    ])
    result = await evaluate_checklist(
        _make_spec(checklist), {"created_files": []}, provider
    )
    assert result is not None
    assert result.passed is False


@pytest.mark.asyncio
async def test_invalid_json_response_raises_checklist_eval_error():
    checklist = (ChecklistItem(instruction="check it", sensors=("stdout",)),)

    class _BadProvider(LLMProvider):
        async def complete(self, messages, system=""):
            return LLMResponse(content="not json at all")

        async def complete_with_tools(self, messages, tools, system=""):
            raise NotImplementedError

    with pytest.raises(ChecklistEvalError):
        await evaluate_checklist(_make_spec(checklist), {"stdout": "ok"}, _BadProvider())
