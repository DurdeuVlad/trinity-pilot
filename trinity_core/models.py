"""Unified data models for Trinity integration."""
from typing import Any, Optional, List, Dict, Literal
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

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
    verification_checks: List["VerificationCheck"] = Field(
        default_factory=list,
        description="Optional structured postcondition checks supplied by the executor",
    )
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


VerificationStatus = Literal["success", "failure", "unknown", "not_requested"]


class VerificationCheck(BaseModel):
    """Structured postcondition check shared across executor, adapters, and reviewer."""

    kind: str
    target: Optional[str] = None
    expected: Any = None
    actual: Any = None
    status: VerificationStatus = "unknown"
    message: Optional[str] = None


class VerificationEnvelope(BaseModel):
    """Normalized verification result attached to every TaskResult when available."""

    status: VerificationStatus = "not_requested"
    checks: List[VerificationCheck] = Field(default_factory=list)
    summary: str = ""
    evidence: Dict[str, Any] = Field(default_factory=dict)
    review_required: bool = False
    source: Literal["executor", "fallback", "mixed", "none"] = "none"

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
    verification: Optional[VerificationEnvelope] = Field(
        None,
        description="Normalized deterministic verification result",
    )
    metadata: Dict = Field(default_factory=dict, description="Module-specific data")


TaskInput.model_rebuild()
TaskResult.model_rebuild()


class RuntimeStatus(str, Enum):
    """Frozen runtime session status."""
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    TERMINATED = "terminated"


class RuntimeFailureCategory(str, Enum):
    """Frozen runtime failure categories."""
    BACKEND_UNAVAILABLE = "backend_unavailable"
    TOOL_SCHEMA_ERROR = "tool_schema_error"
    SESSION_LIFECYCLE_ERROR = "session_lifecycle_error"
    VALIDATOR_REJECTION = "validator_rejection"
    EXECUTION_FAILURE = "execution_failure"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"
    TERMINATED = "terminated"
    TRANSPORT_ERROR = "transport_error"


class RuntimeEventType(str, Enum):
    """Frozen runtime event types."""
    SESSION_CREATED = "session_created"
    OBJECTIVE_STARTED = "objective_started"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    RETRY_SCHEDULED = "retry_scheduled"
    OBJECTIVE_COMPLETED = "objective_completed"
    OBJECTIVE_FAILED = "objective_failed"
    SESSION_INTERRUPTED = "session_interrupted"
    SESSION_TERMINATED = "session_terminated"


class RuntimeEvent(BaseModel):
    """Runtime event emitted during backend execution."""
    sequence: int = Field(..., description="Sequential event number")
    event_type: RuntimeEventType = Field(..., description="Event type")
    timestamp: str = Field(..., description="ISO timestamp")
    session_id: str = Field(..., description="Session identifier")
    objective_id: Optional[str] = Field(None, description="Objective identifier if applicable")
    action_id: Optional[str] = Field(None, description="Action identifier if applicable")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event-specific data")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class RuntimeArtifact(BaseModel):
    """Runtime artifact produced during execution."""
    artifact_id: str = Field(..., description="Unique artifact identifier")
    artifact_type: str = Field(..., description="Artifact type (screenshot, log, file, etc.)")
    path: Optional[str] = Field(None, description="File path if applicable")
    content: Optional[str] = Field(None, description="Inline content if applicable")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Artifact metadata")
    timestamp: str = Field(..., description="ISO timestamp")


class RuntimeResult(BaseModel):
    """Runtime execution result."""
    session_id: str = Field(..., description="Session identifier")
    objective_id: str = Field(..., description="Objective identifier")
    status: RuntimeStatus = Field(..., description="Final status")
    error: Optional[str] = Field(None, description="Error message if failed")
    failure_category: Optional[RuntimeFailureCategory] = Field(None, description="Failure category if failed")
    output: Optional[str] = Field(None, description="Execution output")
    artifacts: List[RuntimeArtifact] = Field(default_factory=list, description="Produced artifacts")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Result metadata")
    started_at: str = Field(..., description="ISO timestamp when started")
    completed_at: Optional[str] = Field(None, description="ISO timestamp when completed")


class CapabilityDescriptor(BaseModel):
    """Backend capability descriptor."""
    capability_id: str = Field(..., description="Unique capability identifier")
    name: str = Field(..., description="Human-readable capability name")
    description: str = Field(..., description="Capability description")
    category: str = Field(..., description="Capability category")
    enabled: bool = Field(True, description="Whether capability is enabled")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Capability parameters")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class BackendProfile(BaseModel):
    """Backend profile configuration."""
    backend_id: Literal["cli", "browser", "desktop"] = Field(..., description="Backend identifier")
    name: str = Field(..., description="Backend name")
    description: str = Field(..., description="Backend description")
    capabilities: List[CapabilityDescriptor] = Field(default_factory=list, description="Available capabilities")
    max_retries: int = Field(3, description="Default max retries")
    timeout: int = Field(300, description="Default timeout in seconds")
    safety_policy: Dict[str, Any] = Field(default_factory=dict, description="Safety policy configuration")
    prompt_config: Dict[str, Any] = Field(default_factory=dict, description="Prompt configuration")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class RuntimeSession(BaseModel):
    """Runtime session state."""
    session_id: str = Field(..., description="Unique session identifier")
    backend_id: Literal["cli", "browser", "desktop"] = Field(..., description="Backend identifier")
    status: RuntimeStatus = Field(RuntimeStatus.CREATED, description="Current status")
    created_at: str = Field(..., description="ISO timestamp when created")
    started_at: Optional[str] = Field(None, description="ISO timestamp when started")
    completed_at: Optional[str] = Field(None, description="ISO timestamp when completed")
    events: List[RuntimeEvent] = Field(default_factory=list, description="Session events")
    artifacts: List[RuntimeArtifact] = Field(default_factory=list, description="Session artifacts")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Session metadata")
