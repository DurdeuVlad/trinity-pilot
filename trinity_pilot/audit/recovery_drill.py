from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class RecoveryDrillResult:
    passed: bool
    intentional_failure: bool
    second_attempt_changed: bool
    changed_fields: list[str]
    cause: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def action_signature(attempt: dict[str, Any]) -> dict[str, Any]:
    evidence = attempt.get("evidence") or {}
    return evidence.get("action_signature") or {
        "action": attempt.get("action"),
        "target": evidence.get("target"),
        "args": evidence.get("args"),
        "steering_context": evidence.get("steering_context"),
    }


def compare_attempts(first: dict[str, Any], second: dict[str, Any], *, reflections: list[dict] | None = None) -> RecoveryDrillResult:
    first_sig = action_signature(first)
    second_sig = action_signature(second)
    changed = sorted(
        key for key in set(first_sig) | set(second_sig)
        if first_sig.get(key) != second_sig.get(key)
    )
    intentional = bool((first.get("evidence") or {}).get("intentional_failure"))
    reflection_hint = ""
    for row in reflections or []:
        if row.get("recovery_hint"):
            reflection_hint = str(row["recovery_hint"])
            break
    cause = reflection_hint or str((second.get("evidence") or {}).get("steering_context") or "")
    passed = intentional and bool(changed) and bool(cause)
    if not intentional:
        reason = "first attempt did not record intentional harness failure"
    elif not changed:
        reason = "second attempt did not change action signature"
    elif not cause:
        reason = "no reviewer/reflection/steering cause was recorded"
    else:
        reason = "second attempt changed because recovery context was available"
    return RecoveryDrillResult(passed, intentional, bool(changed), changed, cause, reason)


def drill_objective_metadata(expected_text: str) -> dict[str, Any]:
    return {
        "audit_recovery_drill": True,
        "force_first_attempt_failure": True,
        "expected_text": expected_text,
    }


def signature_json(signature: dict[str, Any]) -> str:
    return json.dumps(signature, sort_keys=True, default=str)
