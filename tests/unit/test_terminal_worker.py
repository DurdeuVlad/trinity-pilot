"""Terminal worker unit tests â€” uses mock LLM for the agentic loop."""
from __future__ import annotations

import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.llm.base import LLMProvider, LLMResponse
from trinity_pilot.workers.base import WorkerError
from trinity_pilot.workers.terminal_worker import TerminalWorker

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


def _run_command(command, allow_failure=False):
    args = {"command": command}
    if allow_failure:
        args["allow_failure"] = True
    return LLMResponse(
        content="",
        tool_calls=[{"name": "run_command", "args": args}],
    )


def _write_file(path, content):
    return LLMResponse(
        content="",
        tool_calls=[{"name": "write_file", "args": {"path": path, "content": content}}],
    )


def _tool(tool_name, **args):
    return LLMResponse(content="", tool_calls=[{"name": tool_name, "args": args}])


# ---------------------------------------------------------------------------
# Spec helpers
# ---------------------------------------------------------------------------

def _spec(goal: str, **kwargs) -> ObjectiveSpec:
    defaults = dict(
        objective_id="obj-term",
        goal=goal,
        dependencies=[],
        domain=DomainType.TERMINAL,
        required_capabilities=["terminal_command"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["exit code 0"],
        evidence_bundle=["stdout", "stderr", "exit_code"],
        max_attempts=3,
        rollback_or_abort_rule="abort",
    )
    defaults.update(kwargs)
    return ObjectiveSpec(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTerminalWorker:
    async def test_echo_command_captured_in_stdout(self):
        llm = _MockLLM([
            _run_command("echo hello world"),
            _finish("success", "echoed"),
        ])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("run `echo hello world`"))
        # PowerShell echo splits args onto separate lines; check both words present
        assert "hello" in evidence["stdout"] and "world" in evidence["stdout"]
        assert evidence["exit_code"] == 0

    async def test_exit_code_nonzero_run_command_returns_error_observation(self):
        # When a command exits non-zero, _dispatch_tool returns an error string.
        # The LLM then calls finish(failure). run_loop returns WorkerResult(failure).
        # execute() does NOT raise WorkerError for failure status â€” it returns evidence.
        llm = _MockLLM([
            _run_command("exit 1", allow_failure=True),
            _finish("failure", "command failed with exit code 1"),
        ])
        worker = TerminalWorker(llm=llm)
        spec = _spec("run `exit 1`")
        evidence = await worker.execute(spec)
        assert evidence["exit_code"] == 1
        assert evidence["worker_result_status"] == "failure"

    async def test_exit_code_nonzero_without_allow_failure_observation(self):
        # Without allow_failure, _dispatch_tool returns FAILED observation.
        # LLM sees it and calls finish(failure). No WorkerError raised.
        llm = _MockLLM([
            _run_command("exit 1"),
            _finish("failure", "command failed"),
        ])
        worker = TerminalWorker(llm=llm)
        spec = _spec("run `exit 1`")
        evidence = await worker.execute(spec)
        assert evidence["worker_result_status"] == "failure"

    async def test_workspace_retained_after_execution(self):
        """BH-001: worker must NOT rmtree workspace; orchestrator owns cleanup."""
        import os
        import shutil

        llm = _MockLLM([_finish("success", "done")])
        worker = TerminalWorker(llm=llm)
        import trinity_pilot.workers.terminal_worker as tw_mod

        original_validate = tw_mod.validate_evidence
        captured = {}

        def capturing_validate(domain, evidence):
            captured["workspace"] = evidence.get("workspace")
            return original_validate(domain, evidence)

        tw_mod.validate_evidence = capturing_validate
        try:
            await worker.execute(_spec("run `echo test`"))
        finally:
            tw_mod.validate_evidence = original_validate

        workspace = captured.get("workspace")
        assert workspace and os.path.isdir(workspace), "workspace should remain after execute"
        shutil.rmtree(workspace, ignore_errors=True)

    async def test_created_files_captured_in_evidence(self):
        import os
        import tempfile
        tmp = tempfile.mkdtemp()
        out_path = os.path.join(tmp, "output.txt").replace("\\", "/")
        llm = _MockLLM([
            _write_file(out_path, "content"),
            _finish("success", "file written"),
        ])
        spec = ObjectiveSpec(
            objective_id="obj-files",
            goal="write content to a file",
            dependencies=[],
            domain=DomainType.TERMINAL,
            required_capabilities=["shell_raw"],
            risk_class=RiskClass.LOW,
            preconditions=[],
            success_tests=["file created"],
            evidence_bundle=["created_files"],
            max_attempts=1,
            rollback_or_abort_rule="abort",
        )
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(spec)
        assert out_path in evidence["created_files"]

    async def test_deterministic_tier_verify_tag_folded_into_transcript_observation(self):
        llm = _MockLLM([
            _run_command("echo hello"),
            _finish("success", "ran it"),
        ])
        spec = ObjectiveSpec(
            objective_id="obj-verify",
            goal="run a command",
            dependencies=[],
            domain=DomainType.TERMINAL,
            required_capabilities=["shell_raw"],
            risk_class=RiskClass.LOW,
            preconditions=[],
            success_tests=[],
            evidence_bundle=["stdout"],
            max_attempts=1,
            rollback_or_abort_rule="abort",
        )
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(spec)

        transcript = evidence.get("llm_transcript", [])
        run_command_entries = [t for t in transcript if t.get("tool_name") == "run_command"]
        assert run_command_entries, "expected a run_command transcript entry"
        assert "[VERIFY:deterministic]" in run_command_entries[0]["tool_result"]
        assert "exit_code=0" in run_command_entries[0]["tool_result"]
        # Tiered verify is in-loop only â€” never written to evidence directly.
        assert "verify_action" not in evidence
        assert all(not k.startswith("VERIFY") for k in evidence)


    async def test_metadata_command_used_when_present(self):
        # The agentic path sees the goal via LLM. We test that when the LLM
        # calls run_command with the metadata command, the stdout is captured.
        llm = _MockLLM([
            _run_command("echo metadata-marker"),
            _finish("success", "done"),
        ])
        spec = ObjectiveSpec(
            objective_id="obj-meta-cmd",
            goal="Execute the command some vague prose in a terminal.",
            dependencies=[],
            domain=DomainType.TERMINAL,
            required_capabilities=[],
            risk_class=RiskClass.LOW,
            preconditions=[],
            success_tests=["exit code 0"],
            evidence_bundle=["stdout"],
            max_attempts=1,
            rollback_or_abort_rule="abort",
            metadata={"command": "echo metadata-marker"},
        )
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(spec)
        assert "metadata-marker" in evidence["stdout"]
        assert evidence["exit_code"] == 0

    async def test_vague_goal_llm_calls_finish(self):
        # With a vague goal, the LLM can still call finish(failure) cleanly.
        llm = _MockLLM([
            _finish("failure", "cannot determine command from vague goal"),
        ])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("just do something vague"))
        assert evidence["worker_result_status"] == "failure"

    async def test_timeout_raises_worker_error(self, monkeypatch, tmp_path):
        import asyncio
        import os

        import trinity_pilot.workers.terminal_worker as tw_mod

        workspace = str(tmp_path / "terminal-workspace")
        monkeypatch.setattr(tw_mod.tempfile, "mkdtemp", lambda prefix: workspace)

        async def slow_run_loop(spec, evidence, **kwargs):
            await asyncio.sleep(999)

        llm = _MockLLM([])
        worker = TerminalWorker(llm=llm)
        worker.run_loop = slow_run_loop  # type: ignore

        spec = _spec("run `echo test`")
        spec.metadata["timeout_seconds"] = 0.01

        with pytest.raises(WorkerError, match="[Tt]imeout"):
            await worker.execute(spec)

        assert not os.path.exists(workspace)

    async def test_worker_error_cleans_workspace(self, monkeypatch):
        import os
        import tempfile

        workspace = tempfile.mkdtemp(prefix="trinity-term-test-")
        monkeypatch.setattr(
            "trinity_pilot.workers.terminal_worker.tempfile.mkdtemp",
            lambda prefix: workspace,
        )

        async def failing_run_loop(spec, evidence, **kwargs):
            raise RuntimeError("boom")

        worker = TerminalWorker(llm=_MockLLM([]))
        worker.run_loop = failing_run_loop  # type: ignore

        with pytest.raises(WorkerError, match="execution failed"):
            await worker.execute(_spec("fail"))
        assert not os.path.exists(workspace)


class TestTerminalWorkerNewTools:
    """Coverage for the added SENSOR/ACTION tools (read_file, list_directory, etc.)."""

    async def test_read_file_returns_contents(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world", encoding="utf-8")
        llm = _MockLLM([_tool("read_file", path=str(f)), _finish()])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("read a file"))
        transcript = evidence.get("llm_transcript", [])
        read_entries = [t for t in transcript if t.get("tool_name") == "read_file"]
        assert read_entries and "hello world" in read_entries[0]["tool_result"]

    async def test_read_file_missing_reports_not_found(self, tmp_path):
        missing = tmp_path / "nope.txt"
        llm = _MockLLM([_tool("read_file", path=str(missing)), _finish()])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("read a missing file"))
        transcript = evidence.get("llm_transcript", [])
        read_entries = [t for t in transcript if t.get("tool_name") == "read_file"]
        assert "does not exist" in read_entries[0]["tool_result"]

    async def test_list_directory_lists_entries(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "sub").mkdir()
        llm = _MockLLM([_tool("list_directory", path=str(tmp_path)), _finish()])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("list a directory"))
        transcript = evidence.get("llm_transcript", [])
        entries = [t for t in transcript if t.get("tool_name") == "list_directory"]
        result = entries[0]["tool_result"]
        assert "a.txt" in result and "sub/" in result

    async def test_file_exists_true_and_false(self, tmp_path):
        present = tmp_path / "present.txt"
        present.write_text("x")
        missing = tmp_path / "absent.txt"
        llm = _MockLLM([
            _tool("file_exists", path=str(present)),
            _tool("file_exists", path=str(missing)),
            _finish(),
        ])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("check files"))
        entries = [t for t in evidence.get("llm_transcript", []) if t.get("tool_name") == "file_exists"]
        assert "exists=True type=file" in entries[0]["tool_result"]
        assert "exists=False type=none" in entries[1]["tool_result"]

    async def test_copy_file_verifies_destination(self, tmp_path):
        source = tmp_path / "src.txt"
        source.write_text("data")
        dest = tmp_path / "dest.txt"
        llm = _MockLLM([_tool("copy_file", source=str(source), destination=str(dest)), _finish()])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("copy a file"))
        assert dest.read_text() == "data"
        assert str(dest) in evidence["created_files"]

    async def test_move_file_source_gone_dest_exists(self, tmp_path):
        source = tmp_path / "src.txt"
        source.write_text("data")
        dest = tmp_path / "dest.txt"
        llm = _MockLLM([_tool("move_file", source=str(source), destination=str(dest)), _finish()])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("move a file"))
        assert not source.exists()
        assert dest.read_text() == "data"
        assert evidence.get("deleted_files") == [str(source)]

    async def test_delete_file_verifies_gone(self, tmp_path):
        target = tmp_path / "gone.txt"
        target.write_text("x")
        llm = _MockLLM([_tool("delete_file", path=str(target)), _finish()])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("delete a file"))
        assert not target.exists()
        assert evidence.get("deleted_files") == [str(target)]

    async def test_glob_search_finds_matches(self, monkeypatch, tmp_path):
        import trinity_pilot.workers.terminal_worker as tw_mod
        monkeypatch.setattr(tw_mod.tempfile, "mkdtemp", lambda prefix=None: str(tmp_path))
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.py").write_text("x")
        llm = _MockLLM([_tool("glob_search", pattern="**/*.py"), _finish()])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("find python files"))
        entries = [t for t in evidence.get("llm_transcript", []) if t.get("tool_name") == "glob_search"]
        assert '"count": 2' in entries[0]["tool_result"]

    async def test_env_get_redacts_secret_names(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_API_KEY", "super-secret")
        monkeypatch.setenv("MY_TEST_PLAIN_VAR", "plain-value")
        llm = _MockLLM([
            _tool("env_get", name="MY_TEST_API_KEY"),
            _tool("env_get", name="MY_TEST_PLAIN_VAR"),
            _finish(),
        ])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("check env vars"))
        entries = [t for t in evidence.get("llm_transcript", []) if t.get("tool_name") == "env_get"]
        assert "REDACTED" in entries[0]["tool_result"]
        assert "plain-value" in entries[1]["tool_result"]

    async def test_start_process_check_and_kill(self):
        llm = _MockLLM([
            _tool("start_process", command="Start-Sleep -Seconds 30"),
            _finish(),
        ])
        worker = TerminalWorker(llm=llm)
        evidence = await worker.execute(_spec("start a background process"))
        bg_procs = evidence.get("background_processes", [])
        assert bg_procs and bg_procs[0]["pid"]
        # execute()'s finally-block reap should have killed it and cleared tracking.
        assert worker._background_procs == {}
