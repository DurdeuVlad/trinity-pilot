"""Unified data models for Trinity integration."""
from typing import Any, Optional, List, Dict, Literal
from pydantic import BaseModel, Field

# Canonical failure code map — machine-readable codes keyed by category.
_FAILURE_CODE_MAP: dict[str, str] = {
    "timeout": "TIMEOUT",
    "auth_failure": "AUTH_FAILURE",
    "cancelled": "CANCELLED",
    "backend_error": "BACKEND_ERROR",
    "user_error": "USER_ERROR",
    "health_check_failed": "HEALTH_CHECK_FAILED",
}

# Categories for which a retry is plausible.
_RETRIABLE_CATEGORIES: frozenset[str] = frozenset({"timeout", "backend_error", "health_check_failed"})


def failure_code(category: str) -> str:
    """Return the canonical error code for a failure category."""
    return _FAILURE_CODE_MAP.get(category, "UNKNOWN_FAILURE")


def is_retriable(category: str) -> bool:
    """Return True when the failure category is considered transient or ambiguous."""
    return category in _RETRIABLE_CATEGORIES


class TaskInput(BaseModel):
    """Unified input model for all Trinity modules."""
    task_id: str = Field(..., description="Unique task identifier")
    description: str = Field(..., description="Task description in natural language")
    expected_outcome: Optional[str] = Field(None, description="Expected result")
    domain: Literal["web", "desktop", "cli"] = Field(..., description="Execution domain")
    context: Dict = Field(default_factory=dict, description="Domain-specific context")
    max_retries: int = Field(3, description="Maximum retry attempts")
    timeout: Optional[int] = Field(None, description="Timeout in seconds")
    cancel_event: Any = Field(None, description="Optional cooperative cancellation signal")

class ExecutionLog(BaseModel):
    """Unified execution log entry."""
    step: int
    action: str
    result: Literal["success", "failure", "skipped"]
    details: Optional[str] = None
    timestamp: str

class TaskResult(BaseModel):
    """Unified output model for all Trinity modules."""
    task_id: str
    status: Literal["success", "failure", "need_assistance"]
    category: Optional[str] = Field(None, description="Normalized contract category")
    code: Optional[str] = Field(None, description="Machine-readable error code")
    retriable: Optional[bool] = Field(None, description="Whether the operation is retriable")
    error: Optional[str] = Field(None, description="Human-readable error message (legacy compatible)")
    execution_log: List[ExecutionLog] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)
    metadata: Dict = Field(default_factory=dict, description="Module-specific data")
