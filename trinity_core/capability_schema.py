"""Capability schema v1 validator for trinity_core adapter conformance."""

from __future__ import annotations
from typing import Any

SCHEMA_VERSION = "1.0"

# Required top-level keys and their expected types.
_REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "schema_version": str,
    "domain": str,
    "actions": list,
    "limits": dict,
    "constraints": dict,
}

# Required sub-keys inside limits.
_REQUIRED_LIMITS_KEYS: dict[str, type | tuple[type, ...]] = {
    "timeout_seconds": (int, float),
}

# Required sub-keys inside constraints.
_REQUIRED_CONSTRAINTS_KEYS: dict[str, type | tuple[type, ...]] = {
    "thread_safe": bool,
}


def validate_capabilities(caps: dict[str, Any]) -> list[str]:
    """Validate a capabilities dict against schema v1.

    Returns a list of error strings.  Empty list means the payload is valid.
    """
    errors: list[str] = []

    if not isinstance(caps, dict):
        return ["capabilities must be a dict"]

    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in caps:
            errors.append(f"missing required field: {field!r}")
            continue
        if not isinstance(caps[field], expected_type):
            errors.append(
                f"field {field!r} must be {_type_name(expected_type)}, "
                f"got {type(caps[field]).__name__}"
            )

    # schema_version must be exactly SCHEMA_VERSION
    if caps.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {SCHEMA_VERSION!r}, got {caps.get('schema_version')!r}"
        )

    # actions must be a non-empty list of strings
    actions = caps.get("actions")
    if isinstance(actions, list):
        if not actions:
            errors.append("actions list must not be empty")
        elif not all(isinstance(a, str) for a in actions):
            errors.append("all entries in actions must be strings")

    # limits sub-key validation
    limits = caps.get("limits")
    if isinstance(limits, dict):
        for sub_key, sub_type in _REQUIRED_LIMITS_KEYS.items():
            if sub_key not in limits:
                errors.append(f"limits is missing required key: {sub_key!r}")
            elif not isinstance(limits[sub_key], sub_type):
                errors.append(
                    f"limits.{sub_key} must be {_type_name(sub_type)}, "
                    f"got {type(limits[sub_key]).__name__}"
                )

    # constraints sub-key validation
    constraints = caps.get("constraints")
    if isinstance(constraints, dict):
        for sub_key, sub_type in _REQUIRED_CONSTRAINTS_KEYS.items():
            if sub_key not in constraints:
                errors.append(f"constraints is missing required key: {sub_key!r}")
            elif not isinstance(constraints[sub_key], sub_type):
                errors.append(
                    f"constraints.{sub_key} must be {_type_name(sub_type)}, "
                    f"got {type(constraints[sub_key]).__name__}"
                )

    return errors


def _type_name(t: type | tuple[type, ...]) -> str:
    if isinstance(t, tuple):
        return " or ".join(x.__name__ for x in t)
    return t.__name__
