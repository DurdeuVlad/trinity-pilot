"""Unified data models for Trinity integration."""
from typing import Any, Optional, List, Dict, Literal
from pydantic import BaseModel, Field

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
    error: Optional[str] = None
    execution_log: List[ExecutionLog] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)
    metadata: Dict = Field(default_factory=dict, description="Module-specific data")
