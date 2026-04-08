import pytest

from trinity_core.llm.llm_provider import LLMResponse, ToolCall
from trinity_core.models import TaskInput
from trinity_core.orchestrators.browser_runtime import BrowserRuntime
from trinity_core.orchestrators.review_types import ReviewResult


class _FakeBrowserAdapter:
    async def execute(self, task):
        class R:
            status = "success"
            error = None
            metadata = {"ok": True}

        return R()

    async def wait_for_selector(self, selector, timeout, state):
        return None

    async def wait_for_load_state(self, wait_until, timeout):
        return None

    async def get_current_url(self):
        return "https://example.com"


class _FakeLLM:
    def __init__(self):
        self.calls = 0

    async def call(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(tool_calls=[ToolCall(id="1", name="navigate", arguments={"url": "https://example.com"})])
        return LLMResponse(text="done")


class _FakeReviewer:
    async def review(self, objective, definition_of_done, execution_log):
        return ReviewResult(True, "ok")


@pytest.mark.asyncio
async def test_browser_runtime_approval_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = BrowserRuntime(_FakeBrowserAdapter(), llm_provider=_FakeLLM(), reviewer=_FakeReviewer())

    result = await runtime.execute(TaskInput(task_id="t1", description="navigate", domain="web"))

    assert result.status == "success"
    assert result.metadata["review"] == "ok"


class _RejectTwiceReviewer:
    def __init__(self):
        self.calls = 0

    async def review(self, objective, definition_of_done, execution_log):
        self.calls += 1
        if self.calls < 3:
            return ReviewResult(False, "try again")
        return ReviewResult(True, "finally approved")


@pytest.mark.asyncio
async def test_browser_runtime_rejection_then_approval(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reviewer = _RejectTwiceReviewer()
    runtime = BrowserRuntime(
        _FakeBrowserAdapter(),
        llm_provider=_FakeLLM(),
        reviewer=reviewer,
    )
    result = await runtime.execute(TaskInput(task_id="t2", description="navigate", domain="web"))

    assert result.status == "success"
    assert reviewer.calls == 3


class _AlwaysRejectReviewer:
    def __init__(self):
        self.calls = 0

    async def review(self, objective, definition_of_done, execution_log):
        self.calls += 1
        return ReviewResult(False, "not done")


@pytest.mark.asyncio
async def test_browser_runtime_max_attempts_reached(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reviewer = _AlwaysRejectReviewer()
    runtime = BrowserRuntime(
        _FakeBrowserAdapter(),
        llm_provider=_FakeLLM(),
        reviewer=reviewer,
    )
    result = await runtime.execute(TaskInput(task_id="t3", description="navigate", domain="web"))

    assert result.status == "failure"
    assert reviewer.calls == 3


@pytest.mark.asyncio
async def test_browser_runtime_session_persists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = BrowserRuntime(_FakeBrowserAdapter(), llm_provider=_FakeLLM(), reviewer=_FakeReviewer())

    await runtime.execute(TaskInput(task_id="sess-test", description="navigate", domain="web"))

    session_file = tmp_path / ".trinity" / "sessions" / "sess-test.jsonl"
    assert session_file.exists()
    lines = session_file.read_text().strip().splitlines()
    assert len(lines) >= 1
