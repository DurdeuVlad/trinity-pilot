import pytest

from trinity_core.llm.llm_provider import LLMResponse
from trinity_core.models import TaskInput
from trinity_core.orchestrators.cli_runtime import CLIRuntime
from trinity_core.orchestrators.review_types import ReviewResult


class _FakeCLIAdapter:
    async def execute(self, task):
        class R:
            status = "success"
            error = None
            metadata = {"ok": True}

        return R()

    async def wait_for_output_contains(self, text, timeout):
        return None

    async def wait_for_process_exit(self, process_id, timeout):
        return None

    async def wait_for_file_condition(self, file_path, condition, timeout):
        return None


class _FakeLLM:
    async def call(self, messages, tools):
        return LLMResponse(text="done")


class _Reviewer:
    async def review(self, objective, definition_of_done, execution_log):
        return ReviewResult(True, "pass")


@pytest.mark.asyncio
async def test_cli_runtime_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = CLIRuntime(_FakeCLIAdapter(), llm_provider=_FakeLLM(), reviewer=_Reviewer())

    result = await runtime.execute(TaskInput(task_id="c1", description="run cmd", domain="cli"))

    assert result.status == "success"
    assert result.metadata["review"] == "pass"


class _AlwaysRejectReviewer:
    def __init__(self):
        self.calls = 0

    async def review(self, objective, definition_of_done, execution_log):
        self.calls += 1
        return ReviewResult(False, "fail")


@pytest.mark.asyncio
async def test_cli_runtime_rejection_after_max_attempts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reviewer = _AlwaysRejectReviewer()
    runtime = CLIRuntime(_FakeCLIAdapter(), llm_provider=_FakeLLM(), reviewer=reviewer)

    result = await runtime.execute(TaskInput(task_id="c2", description="run cmd", domain="cli"))

    assert result.status == "failure"
    assert reviewer.calls == 3
