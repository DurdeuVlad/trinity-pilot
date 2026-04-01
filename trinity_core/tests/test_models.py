import pytest
from pydantic import ValidationError
from trinity_core.models import TaskInput, TaskResult, ExecutionLog

def test_task_input_valid():
    task = TaskInput(
        task_id="test_001",
        description="Navigate to example.com",
        domain="web"
    )
    assert task.task_id == "test_001"
    assert task.domain == "web"

def test_task_input_invalid_domain():
    with pytest.raises(ValidationError):
        TaskInput(
            task_id="test_001",
            description="Test",
            domain="invalid" # type: ignore
        )

def test_task_result_creation():
    result = TaskResult(
        task_id="test_001",
        status="success",
        execution_log=[]
    )
    assert result.status == "success"
