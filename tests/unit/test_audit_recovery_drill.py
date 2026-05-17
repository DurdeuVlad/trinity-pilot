from trinity_pilot.audit.recovery_drill import compare_attempts


def test_recovery_drill_intentional_failure_and_changed_second_attempt():
    first = {"evidence": {"intentional_failure": True, "action_signature": {"action": "type", "args": ["bad"]}}}
    second = {"evidence": {"action_signature": {"action": "type", "args": ["fixed"], "steering_context": "use hint"}}}

    result = compare_attempts(first, second, reflections=[{"recovery_hint": "use hint"}])

    assert result.passed is True
    assert result.intentional_failure is True
    assert "args" in result.changed_fields


def test_unchanged_second_attempt_fails():
    first = {"evidence": {"intentional_failure": True, "action_signature": {"action": "type", "args": ["same"]}}}
    second = {"evidence": {"action_signature": {"action": "type", "args": ["same"]}}}

    result = compare_attempts(first, second, reflections=[{"recovery_hint": "try something else"}])

    assert result.passed is False
    assert result.second_attempt_changed is False
