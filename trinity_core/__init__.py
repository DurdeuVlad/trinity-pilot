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
    ObjectiveEvidence,
    ObjectivePlan,
    ObjectivePreflightResult,
    SubObjective,
    SubObjectiveResult,
    TaskInput,
    TaskResult,
    VerificationCheck,
    VerificationEnvelope,
)
from .sub_objective_executor import SubObjectiveExecutor
from .strategy_registry import (
    MCPStrategy,
    PromptContribution,
    StrategyRegistry,
)
from .trinity import ObjectiveOrchestrator

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
    "ObjectiveEvidence",
    "ObjectiveOrchestrator",
    "ObjectivePlan",
    "ObjectivePreflightResult",
    "SubObjective",
    "SubObjectiveExecutor",
    "SubObjectiveResult",
    "TaskInput",
    "TaskResult",
    "VerificationCheck",
    "VerificationEnvelope",
    "MCPStrategy",
    "PromptContribution",
    "StrategyRegistry",
]
