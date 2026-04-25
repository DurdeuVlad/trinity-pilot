import pytest
from pydantic import ValidationError
from trinity_core.models import TaskInput, TaskResult, ExecutionLog, VerificationEnvelope

def test_task_input_valid():
    task = TaskInput(
        task_id="test_001",
        description="Navigate to example.com",
        domain="web"
    )
    assert task.task_id == "test_001"
    assert task.domain == "web"

def test_task_result_creation():
    result = TaskResult(
        task_id="test_001",
        status="success",
        execution_log=[]
    )
    assert result.status == "success"


def test_task_input_accepts_verification_checks():
    task = TaskInput(
        task_id="test_002",
        description="Open example.com",
        domain="web",
        verification_checks=[{"kind": "url_equals", "target": "current_url", "expected": "https://example.com"}],
    )
    assert task.verification_checks[0].kind == "url_equals"


def test_task_result_accepts_verification_envelope():
    result = TaskResult(
        task_id="test_003",
        status="success",
        execution_log=[],
        verification=VerificationEnvelope(status="success", summary="verified"),
    )
    assert result.verification is not None
    assert result.verification.status == "success"
