"""DesktopWorker unit tests."""
from __future__ import annotations

import os
import tempfile

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.llm.base import LLMProvider, LLMResponse
from trinity_pilot.workers.desktop_worker import (
    DesktopWorker,
    _button_locator_strategies,
    _click_button_locator,
    _normalise_click_button_args,
)

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


def test_click_button_accepts_uia_locator_shape_from_model():
    assert _normalise_click_button_args({
        "control": {"control_type": "Button", "title": "Save"},
    }) == ("Save", None, "Button")
    assert _normalise_click_button_args({
        "title_re": "(?i)(don't save|discard)",
    }) == (None, "(?i)(don't save|discard)", "Button")


def test_click_button_builds_exact_and_regex_locator_strategies():
    strategies = _button_locator_strategies("Desktop", None, "Button")
    assert strategies[0] == {"title": "Desktop", "control_type": "Button"}
    assert strategies[-1] == {"title_re": "(?i)Desktop"}


def test_click_button_accepts_top_level_uia_locator_shape():
    assert _click_button_locator({
        "automation_id": "1001",
        "control_type": "Edit",
    }) == {"auto_id": "1001", "control_type": "Edit"}


class TestDesktopWorkerPressKey:
    def test_pywinauto_key_sequence_maps_calculator_operators(self):
        assert DesktopWorker._pywinauto_key_sequence("multiply") == "{*}"
        assert DesktopWorker._pywinauto_key_sequence("add") == "{+}"
        assert DesktopWorker._pywinauto_key_sequence("return") == "{ENTER}"
        assert DesktopWorker._pywinauto_key_sequence("1") == "1"

    def test_normalise_hotkey_keys_accepts_comma_and_plus_forms(self):
        assert DesktopWorker._normalise_hotkey_keys("ctrl,s") == ["ctrl", "s"]
        assert DesktopWorker._normalise_hotkey_keys("ctrl+shift+s") == ["ctrl", "shift", "s"]
        assert DesktopWorker._normalise_hotkey_keys(" ctrl + shift + s ") == ["ctrl", "shift", "s"]

    def test_foreground_target_is_preserved_for_owned_modal_window(self):
        class User32:
            def GetAncestor(self, hwnd, _kind):
                return 100 if hwnd == 200 else 0

            def GetWindow(self, _hwnd, _kind):
                return 0

        assert DesktopWorker._foreground_belongs_to_target(User32(), 100, 200)

    def test_common_out_of_process_save_dialog_is_preserved(self):
        class User32:
            def GetWindowTextLengthW(self, _hwnd):
                return len("Save As")

            def GetWindowTextW(self, _hwnd, buf, _length):
                buf.value = "Save As"

        assert DesktopWorker._foreground_is_common_modal_dialog(User32(), 200)

    def test_intentional_close_is_detected_from_action_log(self):
        assert DesktopWorker._intentional_close_recorded(["Hotkey: alt+f4"])
        assert DesktopWorker._intentional_close_recorded(["Hotkey: alt,f4"])
        assert not DesktopWorker._intentional_close_recorded(["Hotkey: ctrl+s"])

    def test_pyautogui_key_name_maps_calculator_operators(self):
        assert DesktopWorker._pyautogui_key_name("multiply") == "multiply"
        assert DesktopWorker._pyautogui_key_name("equals") == "enter"

    def test_is_meaningful_ui_text_filters_accessibility_labels(self):
        assert not DesktopWorker._is_meaningful_ui_text("Display is 0", "Text")
        assert DesktopWorker._is_meaningful_ui_text("144", "Text")
        assert DesktopWorker._is_meaningful_ui_text("hello world", "Edit")

    def test_score_ui_snippet_prefers_numeric_results(self):
        assert DesktopWorker._score_ui_snippet("144", "Text") > DesktopWorker._score_ui_snippet(
            "Display is 0", "Text"
        )

    def test_uia_snippets_show_result_value(self):
        assert DesktopWorker._uia_snippets_show_result_value(["144"])
        assert DesktopWorker._uia_snippets_show_result_value(["Expression is 12 × 12=144"])
        assert not DesktopWorker._uia_snippets_show_result_value(
            ["Expression is 12 × 12=", "Calculator", "Standard"]
        )

    def test_calculator_text_to_keys_parses_expressions(self):
        assert DesktopWorker._calculator_text_to_keys("12*12") == [
            "1", "2", "multiply", "1", "2", "equals",
        ]
        assert DesktopWorker._calculator_text_to_keys("12 multiplied by 12") == [
            "1", "2", "multiply", "1", "2", "equals",
        ]
        assert DesktopWorker._calculator_text_to_keys("1024+768") == [
            "1", "0", "2", "4", "add", "7", "6", "8", "equals",
        ]
        assert DesktopWorker._calculator_text_to_keys("hello") is None
