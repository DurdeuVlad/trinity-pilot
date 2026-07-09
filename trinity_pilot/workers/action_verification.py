from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Protocol

from tenacity import AsyncRetrying, retry_if_result, stop_after_delay, wait_exponential

_DEFAULT_EVENTUALLY_DEADLINE_SECONDS = 10.0


class ActionTier(StrEnum):
    """Which verification strategy a dispatched action gets, per C5's design.

    No predicate-checkable tier here — that idea was deliberately dropped:
    letting a planner or registry improvise *which* deterministic check
    applies to an arbitrary action is its own mismatch failure mode. Every
    action maps to exactly one of these three, chosen by us at registration
    time, not guessed at runtime.
    """

    DETERMINISTIC = "deterministic"
    EVENTUALLY_CONSISTENT = "eventually_consistent"
    LLM_GROUNDED = "llm_grounded"


# Data-driven action -> tier lookup. An action with no entry here gets no
# tiered verification at all — today's behavior, unchanged. Adding an action
# is a one-line registry change, not a new dispatcher branch.
TIER_REGISTRY: dict[str, ActionTier] = {
    "write_file": ActionTier.DETERMINISTIC,
    "run_command": ActionTier.DETERMINISTIC,
    "launch_app": ActionTier.EVENTUALLY_CONSISTENT,
    "navigate": ActionTier.EVENTUALLY_CONSISTENT,
    "click_button": ActionTier.LLM_GROUNDED,
    "type_text": ActionTier.LLM_GROUNDED,
}


class SensorCheck(Protocol):
    def __call__(self) -> Awaitable[bool]: ...


class SensorRead(Protocol):
    def __call__(self) -> Awaitable[str]: ...


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """In-loop-only grounding result. Never written to `evidence` — folding
    this into the acting LLM's next observation is the only consumer, per the
    design decision to keep tiered verification worker-internal."""

    tier: ActionTier
    detail: str
    ok: bool | None  # None = undetermined; the acting LLM judges from `detail`


async def verify_action(
    action_name: str,
    evidence: dict[str, Any],
    *,
    sensor_check: SensorCheck | None = None,
    sensor_read: SensorRead | None = None,
    deadline_seconds: float = _DEFAULT_EVENTUALLY_DEADLINE_SECONDS,
) -> VerifyResult | None:
    """Run the registered tier's verification for one just-dispatched action.

    Returns None when the action isn't registered, or when a required sensor
    callable wasn't supplied for an eventually-consistent/LLM-grounded action —
    callers fold nothing extra into the observation in that case, same as
    today's behavior.
    """
    tier = TIER_REGISTRY.get(action_name)
    if tier is None:
        return None

    match tier:
        case ActionTier.DETERMINISTIC:
            return _verify_deterministic(action_name, evidence)
        case ActionTier.EVENTUALLY_CONSISTENT:
            if sensor_check is None:
                return None
            return await _verify_eventually(tier, sensor_check, deadline_seconds)
        case ActionTier.LLM_GROUNDED:
            if sensor_read is None:
                return None
            return await _verify_llm_grounded(tier, sensor_read)


def _verify_deterministic(action_name: str, evidence: dict[str, Any]) -> VerifyResult:
    if action_name == "write_file":
        failures = evidence.get("write_file_failures") or []
        ok = not failures
        detail = (
            "write_file verified: file exists on disk"
            if ok
            else f"write_file verification failed: {failures[-1]}"
        )
        return VerifyResult(tier=ActionTier.DETERMINISTIC, detail=detail, ok=ok)

    if action_name == "run_command":
        exit_code = evidence.get("exit_code")
        ok = exit_code == 0
        detail = f"run_command verified: exit_code={exit_code}"
        return VerifyResult(tier=ActionTier.DETERMINISTIC, detail=detail, ok=ok)

    return VerifyResult(
        tier=ActionTier.DETERMINISTIC,
        detail=f"no deterministic check defined for '{action_name}'",
        ok=None,
    )


async def _verify_eventually(
    tier: ActionTier,
    sensor_check: SensorCheck,
    deadline_seconds: float,
) -> VerifyResult:
    retryer = AsyncRetrying(
        retry=retry_if_result(lambda result: result is False),
        stop=stop_after_delay(deadline_seconds),
        wait=wait_exponential(multiplier=0.2, max=2.0),
    )
    try:
        ok = bool(await retryer(sensor_check))
    except Exception:
        ok = False

    detail = (
        "confirmed after polling"
        if ok
        else f"not confirmed within {deadline_seconds}s deadline"
    )
    return VerifyResult(tier=tier, detail=detail, ok=ok)


async def _verify_llm_grounded(tier: ActionTier, sensor_read: SensorRead) -> VerifyResult:
    try:
        detail = await sensor_read()
    except Exception as exc:
        detail = f"sensor read failed: {exc}"
    return VerifyResult(tier=tier, detail=detail, ok=None)
