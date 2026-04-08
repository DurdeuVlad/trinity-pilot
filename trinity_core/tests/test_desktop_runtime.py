import pytest

from trinity_core.llm.llm_provider import LLMResponse
from trinity_core.models import TaskInput
from trinity_core.orchestrators.desktop_runtime import DesktopRuntime
from trinity_core.orchestrators.review_types import ReviewResult


class _FakeDesktopAdapter:
    async def execute(self, task):
        class R:
            status = "success"
            error = None
            metadata = {"ok": True}

        return R()

    async def wait_for_process(self, app_name, timeout):
        return None

    async def wait_for_window_title(self, title, timeout):
        return None

    async def wait_for_ui_element(self, element_name, element_type, timeout):
        return None

    async def wait_for_text_in_window(self, text, timeout):
        return None


class _FakeLLM:
    async def call(self, messages, tools):
        return LLMResponse(text="done")


class _RejectingReviewer:
    def __init__(self):
        self.n = 0

    async def review(self, objective, definition_of_done, execution_log):
        self.n += 1
        return ReviewResult(False, "retry")


class _ApprovingReviewer:
    async def review(self, objective, definition_of_done, execution_log):
        return ReviewResult(True, "approved")


@pytest.mark.asyncio
async def test_desktop_runtime_rejects_after_max_attempts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reviewer = _RejectingReviewer()
    runtime = DesktopRuntime(_FakeDesktopAdapter(), llm_provider=_FakeLLM(), reviewer=reviewer)

    result = await runtime.execute(TaskInput(task_id="d1", description="open app", domain="desktop"))

    assert result.status == "failure"
    assert reviewer.n == 3


@pytest.mark.asyncio
async def test_desktop_runtime_success_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = DesktopRuntime(_FakeDesktopAdapter(), llm_provider=_FakeLLM(), reviewer=_ApprovingReviewer())

    result = await runtime.execute(TaskInput(task_id="d2", description="open Notepad", domain="desktop"))

    assert result.status == "success"
