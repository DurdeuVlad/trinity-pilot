"""DesktopWorker unit tests."""
from __future__ import annotations

import builtins
import tempfile
import os

import pytest
from PIL import Image, ImageGrab

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse
from trinity_pilot.workers.desktop_worker import DesktopWorker


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------

class _MockLLM(LLMProvider):
    def __init__(self, responses):
        self._responses = iter(responses)

    async def complete(self, messages, system="", **kwargs):
        raise NotImplementedError

    async def complete_with_tools(self, messages, tools, system="", **kwargs):
        return next(self._responses)

    @property
    def model(self):
        return "mock"


def _finish(status="success", summary="done"):
    return LLMResponse(
        content="",
        tool_calls=[{"name": "finish", "args": {"status": status, "summary": summary}}],
    )


def _write_file_response(path, content):
    return LLMResponse(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": path, "content": content}}],
    )


# ---------------------------------------------------------------------------
# Spec helpers
# ---------------------------------------------------------------------------

def _desktop_spec(goal: str = 'Inspect app "Calculator"') -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="desktop-1",
        goal=goal,
        dependencies=[],
        domain=DomainType.DESKTOP,
        required_capabilities=["desktop_automation"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["desktop evidence captured or degraded"],
        evidence_bundle=["screenshot"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDesktopWorkerAgenticPath:
    async def test_execute_calls_run_loop_and_returns_evidence(self):
        """execute() wires to run_loop — finish response returns evidence dict."""
        llm = _MockLLM([_finish("success", "done")])
        worker = DesktopWorker(llm=llm)
        evidence = await worker.execute(_desktop_spec())
        assert evidence["domain"] == "desktop"
        assert evidence["objective_id"] == "desktop-1"
        assert evidence["worker_result_status"] == "success"
        assert evidence["worker_result_summary"] == "done"

    async def test_write_file_tool_creates_file_and_updates_evidence(self):
        """write_file tool call via run_loop writes the file and logs it."""
        tmp = tempfile.mkdtemp()
        out_path = os.path.join(tmp, "result.txt").replace("\\", "/")
        llm = _MockLLM([
            _write_file_response(out_path, "hello desktop"),
            _finish("success", "file written"),
        ])
        worker = DesktopWorker(llm=llm)
        evidence = await worker.execute(_desktop_spec("write hello desktop to a file"))
        assert out_path in evidence["written_files"]
        assert os.path.exists(out_path)
        assert open(out_path).read() == "hello desktop"

    async def test_finish_failure_returns_evidence_without_raising(self):
        """finish(failure) returns evidence with worker_result_status=failure, no exception."""
        llm = _MockLLM([_finish("failure", "could not complete task")])
        worker = DesktopWorker(llm=llm)
        evidence = await worker.execute(_desktop_spec())
        assert evidence["worker_result_status"] == "failure"

    async def test_action_log_populated_by_tool_calls(self):
        """Each tool call adds an entry to action_log in evidence."""
        tmp = tempfile.mkdtemp()
        out_path = os.path.join(tmp, "log_test.txt").replace("\\", "/")
        llm = _MockLLM([
            _write_file_response(out_path, "test content"),
            _finish("success", "done"),
        ])
        worker = DesktopWorker(llm=llm)
        evidence = await worker.execute(_desktop_spec("write test content to file"))
        assert any("Wrote file" in entry for entry in evidence["action_log"])


class TestDesktopWorkerLegacyHelpers:
    """Test legacy helper methods that are still on the class."""

    async def test_run_objective_degraded_mode_when_not_win32(self, monkeypatch):
        """_run_objective sets degraded_mode when platform is not win32."""
        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.setattr(ImageGrab, "grab", lambda: Image.new("RGB", (8, 8), "white"))

        evidence = {
            "domain": "desktop",
            "objective_id": "desktop-1",
            "screenshot": None,
            "element_tree_snapshot": None,
            "action_log": [],
            "selected_actions": [],
            "typed_text": "",
            "visible_text": "",
            "written_files": [],
            "degraded_mode": False,
            "error": None,
        }
        worker = DesktopWorker.__new__(DesktopWorker)
        await worker._run_objective(_desktop_spec(), evidence)
        assert evidence["degraded_mode"] is True

    async def test_run_objective_degraded_mode_when_uia_fails(self, monkeypatch):
        """_run_objective sets degraded_mode when pywinauto is unavailable."""
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in {"pywinauto", "pyautogui"}:
                raise ModuleNotFoundError(name)
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("sys.platform", "win32")
        monkeypatch.setattr(builtins, "__import__", fake_import)
        monkeypatch.setattr(ImageGrab, "grab", lambda: Image.new("RGB", (8, 8), "white"))

        evidence = {
            "domain": "desktop",
            "objective_id": "desktop-1",
            "screenshot": None,
            "element_tree_snapshot": None,
            "action_log": [],
            "selected_actions": [],
            "typed_text": "",
            "visible_text": "",
            "written_files": [],
            "degraded_mode": False,
            "error": None,
        }
        worker = DesktopWorker.__new__(DesktopWorker)
        await worker._run_objective(_desktop_spec(), evidence)
        assert evidence["degraded_mode"] is True
        assert evidence["screenshot"]
        assert evidence["element_tree_snapshot"] is None
        assert any("UIA failed" in item for item in evidence["action_log"])
        assert any("Screenshot captured via PIL ImageGrab" in item for item in evidence["action_log"])
