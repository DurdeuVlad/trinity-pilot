from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DomainType(str, Enum):
    BROWSER = "browser"
    TERMINAL = "terminal"
    DESKTOP = "desktop"
    MIXED = "mixed"


class RiskClass(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FailureReason(str, Enum):
    MISSING_ARTIFACT = "missing_artifact"
    FAILED_ASSERTION = "failed_assertion"
    UI_STATE_MISMATCH = "ui_state_mismatch"
    WRONG_OUTPUT = "wrong_output"
    ENVIRONMENT_DIVERGENCE = "environment_divergence"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    """One planner-authored, guided-LLM-checkable verification item for an objective.

    No predicate/deterministic tier here by design — a planner picking the wrong
    deterministic check for an objective is a mismatch failure mode (see the
    MIXED-domain router crash precedent), so every checklist item is scoped
    narrowly via `instruction` and answered by the reviewer LLM against the
    named `sensors`' fresh data, not judged from the full evidence blob.
    """

    instruction: str
    sensors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"instruction": self.instruction, "sensors": list(self.sensors)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChecklistItem":
        instruction = str(data.get("instruction", "")).strip()
        sensors = data.get("sensors") or []
        return cls(instruction=instruction, sensors=tuple(str(s) for s in sensors))

    def is_valid(self) -> bool:
        return bool(self.instruction) and bool(self.sensors)


_REQUIRED_SPEC_FIELDS = (
    "objective_id",
    "goal",
    "dependencies",
    "domain",
    "required_capabilities",
    "risk_class",
    "preconditions",
    "success_tests",
    "evidence_bundle",
    "max_attempts",
    "rollback_or_abort_rule",
)


@dataclass
class ObjectiveSpec:
    objective_id: str
    goal: str
    dependencies: list[str]
    domain: DomainType
    required_capabilities: list[str]
    risk_class: RiskClass
    preconditions: list[str]
    success_tests: list[str]
    evidence_bundle: list[str]
    max_attempts: int
    rollback_or_abort_rule: str
    metadata: dict[str, Any] = field(default_factory=dict)
    verification_checklist: tuple[ChecklistItem, ...] = ()

    def validate(self) -> None:
        # String fields must be non-empty (strip whitespace before check)
        for fname in ("objective_id", "goal", "rollback_or_abort_rule"):
            if not str(getattr(self, fname, "") or "").strip():
                raise ValueError(f"ObjectiveSpec missing required field: {fname}")
        # List fields must not be None (empty list is valid for deps/preconditions)
        for fname in (
            "dependencies",
            "required_capabilities",
            "preconditions",
            "success_tests",
            "evidence_bundle",
        ):
            if getattr(self, fname) is None:
                raise ValueError(f"ObjectiveSpec missing required field: {fname}")
        # Enum fields
        if self.domain is None:
            raise ValueError("ObjectiveSpec missing required field: domain")
        if self.risk_class is None:
            raise ValueError("ObjectiveSpec missing required field: risk_class")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "goal": self.goal,
            "dependencies": self.dependencies,
            "domain": self.domain.value,
            "required_capabilities": self.required_capabilities,
            "risk_class": self.risk_class.value,
            "preconditions": self.preconditions,
            "success_tests": self.success_tests,
            "evidence_bundle": self.evidence_bundle,
            "max_attempts": self.max_attempts,
            "rollback_or_abort_rule": self.rollback_or_abort_rule,
            "metadata": self.metadata,
            "verification_checklist": [item.to_dict() for item in self.verification_checklist],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ObjectiveSpec":
        return cls(
            objective_id=data["objective_id"],
            goal=data["goal"],
            dependencies=data["dependencies"],
            domain=DomainType(data["domain"]),
            required_capabilities=data["required_capabilities"],
            risk_class=RiskClass(data["risk_class"]),
            preconditions=data["preconditions"],
            success_tests=data["success_tests"],
            evidence_bundle=data["evidence_bundle"],
            max_attempts=data["max_attempts"],
            rollback_or_abort_rule=data["rollback_or_abort_rule"],
            metadata=data.get("metadata", {}),
            verification_checklist=tuple(
                ChecklistItem.from_dict(item)
                for item in (data.get("verification_checklist") or [])
                if isinstance(item, dict)
            ),
        )


@dataclass
class TaskRecord:
    task_id: str
    user_request: str
    objectives: list[ObjectiveSpec] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class AttemptLog:
    attempt_id: str
    objective_id: str
    task_id: str
    attempt_number: int
    status: str  # "running" | "passed" | "failed"
    failure_reason: FailureReason | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReviewResult:
    passed: bool
    failure_reason: FailureReason | None = None
    notes: str = ""
    recovery_hint: str = ""


from trinity_pilot.orchestrator.budget import BudgetExceeded, ObjectiveBudget  # noqa: E402,F401
