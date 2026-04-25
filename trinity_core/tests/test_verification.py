from __future__ import annotations

from pathlib import Path

from trinity_core.models import TaskInput
from trinity_core.verification import build_verification


def test_build_verification_uses_explicit_checks_to_override_weak_fallbacks(tmp_path: Path) -> None:
    target = tmp_path / "done.txt"
    target.write_text("ok", encoding="utf-8")
    task = TaskInput(
        task_id="verify-explicit",
        description="Create a file",
        domain="cli",
        verification_checks=[
            {"kind": "file_exists", "target": str(target), "expected": True},
        ],
    )

    verification = build_verification(
        task=task,
        module="cli",
        backend_result={"status": "success", "metadata": {}},
        task_status="success",
        execution_log=[],
        output_text="created file",
    )

    assert verification.status == "success"
    assert verification.source == "executor"
    assert verification.checks[0].kind == "file_exists"
    assert verification.checks[0].status == "success"


def test_build_verification_marks_transient_failure_unknown() -> None:
    task = TaskInput(
        task_id="verify-transient",
        description="Open the dashboard",
        domain="desktop",
    )

    verification = build_verification(
        task=task,
        module="desktop",
        backend_result={"status": "failure", "error": "window_not_found while app is still loading", "metadata": {}},
        task_status="failure",
        execution_log=[],
        output_text="window_not_found while app is still loading",
    )

    assert verification.status == "unknown"
    assert verification.review_required is True


def test_build_verification_cli_uses_command_exit_code_evidence() -> None:
    task = TaskInput(
        task_id="verify-cli",
        description="Run dir",
        domain="cli",
    )
    execution_log = [
        {
            "step": 1,
            "action": "dir",
            "result": "success",
            "details": "listed files",
            "timestamp": "2026-04-13T00:00:00",
            "exit_code": 0,
        }
    ]

    verification = build_verification(
        task=task,
        module="cli",
        backend_result={"status": "success", "metadata": {}},
        task_status="success",
        execution_log=execution_log,
        output_text="listed files",
    )

    assert verification.status == "success"
    assert any(check.kind == "command_exit_code" for check in verification.checks)


def test_build_verification_window_exists_requires_observed_window() -> None:
    task = TaskInput(
        task_id="verify-window",
        description="Open Notepad",
        domain="desktop",
        verification_checks=[{"kind": "window_exists", "target": "Notepad", "expected": True}],
        context={"app_name": "Notepad"},
    )

    verification = build_verification(
        task=task,
        module="desktop",
        backend_result={"status": "success", "metadata": {"app_context": "Notepad"}},
        task_status="success",
        execution_log=[],
        output_text="Open Notepad",
    )

    assert verification.status == "unknown"
    assert verification.checks[0].status == "unknown"


def test_url_matches_tolerates_normal_redirect_normalization() -> None:
    task = TaskInput(
        task_id="verify-url",
        description="Open example.com",
        domain="web",
        verification_checks=[{"kind": "url_matches", "target": "current_url", "expected": "http://example.com"}],
    )

    verification = build_verification(
        task=task,
        module="browser",
        backend_result={"result": "success", "current_url": "https://example.com/"},
        task_status="success",
        execution_log=[],
        output_text="loaded page",
    )

    assert verification.status == "success"
    assert verification.checks[0].status == "success"


def test_browser_verification_does_not_treat_model_text_as_browser_evidence() -> None:
    task = TaskInput(
        task_id="verify-browser-weak",
        description="Open the page",
        domain="web",
        verification_checks=[{"kind": "visible_tool_execution", "target": "mcp_visible_tools", "expected": True}],
    )

    verification = build_verification(
        task=task,
        module="browser",
        backend_result={"status": "success", "metadata": {}},
        task_status="success",
        execution_log=[{"step": 1, "action": "echo", "result": "success", "details": "hello", "timestamp": "2026-04-17T00:00:00"}],
        output_text="done",
    )

    assert verification.status == "unknown"
    assert verification.evidence["combined_text"] == "hello"
    assert verification.evidence["model_text"] == "done"


def test_desktop_verification_does_not_treat_generic_tool_success_as_completion() -> None:
    task = TaskInput(
        task_id="verify-desktop-weak",
        description="Open Notepad",
        domain="desktop",
        verification_checks=[{"kind": "visible_tool_execution", "target": "mcp_visible_tools", "expected": True}],
    )

    verification = build_verification(
        task=task,
        module="desktop",
        backend_result={"status": "success", "metadata": {}},
        task_status="success",
        execution_log=[{"step": 1, "action": "echo", "result": "success", "details": "hello", "timestamp": "2026-04-17T00:00:00"}],
        output_text="done",
    )

    assert verification.status == "unknown"
