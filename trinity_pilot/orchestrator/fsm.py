from __future__ import annotations

from enum import Enum


class ObjectiveState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    STUCK = "stuck"
    STEERED = "steered"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


VALID_TRANSITIONS: dict[ObjectiveState, set[ObjectiveState]] = {
    ObjectiveState.PENDING:  {ObjectiveState.RUNNING},
    ObjectiveState.RUNNING:  {ObjectiveState.STUCK, ObjectiveState.DONE, ObjectiveState.FAILED, ObjectiveState.CANCELLED},
    ObjectiveState.STUCK:    {ObjectiveState.STEERED, ObjectiveState.FAILED},
    ObjectiveState.STEERED:  {ObjectiveState.RUNNING, ObjectiveState.DONE, ObjectiveState.FAILED},
    ObjectiveState.DONE:     set(),
    ObjectiveState.FAILED:   set(),
    ObjectiveState.CANCELLED: set(),
}


def transition(current: ObjectiveState, next_: ObjectiveState) -> ObjectiveState:
    """Validate and apply an FSM transition. Raises ValueError on illegal move."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if next_ not in allowed:
        raise ValueError(
            f"Invalid transition: {current.value!r} -> {next_.value!r}. "
            f"Allowed: {[s.value for s in allowed]}"
        )
    return next_
