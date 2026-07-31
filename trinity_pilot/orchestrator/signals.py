from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class ObjectiveStarted:
    task_id: str
    objective_id: str
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class StepCompleted:
    task_id: str
    objective_id: str
    step_num: int
    tool_name: str
    args_hash: str
    token_count: int
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class StuckSignal:
    task_id: str
    objective_id: str
    reason: str
    consecutive_count: int
    user_question: str = ""
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class BudgetWarning:
    task_id: str
    objective_id: str
    budget_type: str  # "steps" | "tokens" | "wall_clock"
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ObjectiveDone:
    task_id: str
    objective_id: str
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ObjectiveFailed:
    task_id: str
    objective_id: str
    failure_reason: str
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SteeringMessage:
    task_id: str
    objective_id: str
    guidance: str
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WorkerStepSignal:
    task_id: str
    objective_id: str
    step_num: int
    tool_name: str
    tokens_this_step: int
    ts: float = field(default_factory=time.time)


Signal = Union[
    ObjectiveStarted,
    StepCompleted,
    StuckSignal,
    BudgetWarning,
    ObjectiveDone,
    ObjectiveFailed,
    SteeringMessage,
    WorkerStepSignal,
]
