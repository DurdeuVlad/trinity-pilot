import pytest

from trinity_pilot.core.types import (
    DomainType,
    FailureReason,
    ObjectiveSpec,
    ReviewResult,
    RiskClass,
    TaskRecord,
    TaskStatus,
)


def _make_spec(**overrides) -> ObjectiveSpec:
    base = dict(
        objective_id="obj-1",
        goal="Open browser and navigate to example.com",
        dependencies=[],
        domain=DomainType.BROWSER,
        required_capabilities=["browser_navigation"],
        risk_class=RiskClass.LOW,
        preconditions=["browser installed"],
        success_tests=["page title contains 'Example'"],
        evidence_bundle=["screenshot"],
        max_attempts=3,
        rollback_or_abort_rule="abort on failure",
    )
    base.update(overrides)
    return ObjectiveSpec(**base)


class TestObjectiveSpec:
    def test_valid_spec_passes_validation(self):
        spec = _make_spec()
        spec.validate()  # should not raise

    def test_missing_goal_raises(self):
        spec = _make_spec(goal="")
        with pytest.raises(ValueError, match="goal"):
            spec.validate()

    def test_empty_dependencies_is_valid(self):
        spec = _make_spec(dependencies=[])
        spec.validate()  # empty list is OK

    def test_zero_max_attempts_raises(self):
        spec = _make_spec(max_attempts=0)
        with pytest.raises(ValueError, match="max_attempts"):
            spec.validate()

    def test_roundtrip_to_dict_and_back(self):
        spec = _make_spec()
        restored = ObjectiveSpec.from_dict(spec.to_dict())
        assert restored.objective_id == spec.objective_id
        assert restored.domain == spec.domain
        assert restored.risk_class == spec.risk_class

    def test_metadata_roundtrip(self):
        spec = _make_spec()
        spec.metadata = {"timeout_seconds": 42, "custom_key": "value"}
        restored = ObjectiveSpec.from_dict(spec.to_dict())
        assert restored.metadata["timeout_seconds"] == 42
        assert restored.metadata["custom_key"] == "value"

    def test_metadata_defaults_to_empty_dict(self):
        d = _make_spec().to_dict()
        d.pop("metadata", None)  # simulate old serialized data
        restored = ObjectiveSpec.from_dict(d)
        assert restored.metadata == {}

    def test_domain_enum_values(self):
        assert DomainType.BROWSER.value == "browser"
        assert DomainType.TERMINAL.value == "terminal"
        assert DomainType.DESKTOP.value == "desktop"
        assert DomainType.MIXED.value == "mixed"

    def test_failure_reason_enum_values(self):
        assert FailureReason.MISSING_ARTIFACT.value == "missing_artifact"
        assert FailureReason.UI_STATE_MISMATCH.value == "ui_state_mismatch"


class TestTaskRecord:
    def test_default_status_pending(self):
        record = TaskRecord(task_id="t-1", user_request="do something")
        assert record.status == TaskStatus.PENDING
        assert record.objectives == []


class TestReviewResult:
    def test_passed_review(self):
        r = ReviewResult(passed=True)
        assert r.failure_reason is None

    def test_failed_review_has_reason(self):
        r = ReviewResult(passed=False, failure_reason=FailureReason.WRONG_OUTPUT)
        assert r.failure_reason == FailureReason.WRONG_OUTPUT
