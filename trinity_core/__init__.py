"""Trinity Core - Shared backend execution runtime."""

from .models import (
    BackendProfile,
    CapabilityDescriptor,
    RuntimeArtifact,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeFailureCategory,
    RuntimeResult,
    RuntimeSession,
    RuntimeStatus,
    TaskInput,
    TaskResult,
    VerificationCheck,
    VerificationEnvelope,
)
from .mcp_strategy_runtime import MCPStrategyRuntime
from .strategy_registry import (
    MCPStrategy,
    PromptContribution,
    StrategyRegistry,
)

__all__ = [
    "BackendProfile",
    "CapabilityDescriptor",
    "RuntimeArtifact",
    "RuntimeEvent",
    "RuntimeEventType",
    "RuntimeFailureCategory",
    "RuntimeResult",
    "RuntimeSession",
    "RuntimeStatus",
    "TaskInput",
    "TaskResult",
    "VerificationCheck",
    "VerificationEnvelope",
    "MCPStrategy",
    "MCPStrategyRuntime",
    "PromptContribution",
    "StrategyRegistry",
]
