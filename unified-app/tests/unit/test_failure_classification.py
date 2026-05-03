"""
Deterministic unit tests: failure code and retriability classification.

No mocks, no I/O. failure_code() and is_retriable() are pure table lookups
whose outputs must be stable for every known category.
"""
from __future__ import annotations

import pytest

from trinity_core.models import failure_code, is_retriable


@pytest.mark.parametrize("category,expected_code", [
    ("timeout",             "TIMEOUT"),
    ("auth_failure",        "AUTH_FAILURE"),
    ("cancelled",           "CANCELLED"),
    ("backend_error",       "BACKEND_ERROR"),
    ("user_error",          "USER_ERROR"),
    ("health_check_failed", "HEALTH_CHECK_FAILED"),
    ("unknown_category",    "UNKNOWN_FAILURE"),   # unmapped → fallback
    ("",                    "UNKNOWN_FAILURE"),   # empty → fallback
])
def test_failure_code(category: str, expected_code: str) -> None:
    assert failure_code(category) == expected_code, (
        f"failure_code({category!r}) should be {expected_code!r}"
    )


@pytest.mark.parametrize("category,expected_retriable", [
    ("timeout",             True),
    ("backend_error",       True),
    ("health_check_failed", True),
    ("auth_failure",        False),
    ("cancelled",           False),
    ("user_error",          False),
    ("unknown_category",    False),   # unknown → not retriable
    ("",                    False),
])
def test_is_retriable(category: str, expected_retriable: bool) -> None:
    assert is_retriable(category) == expected_retriable, (
        f"is_retriable({category!r}) should be {expected_retriable}"
    )
