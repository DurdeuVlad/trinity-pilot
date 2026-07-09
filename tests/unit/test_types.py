import pytest

from trinity_pilot.core.types import (
    AttemptLog,
    ChecklistItem,
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


class TestObjectiveSpecMetadataRoundTrip:
    def test_to_dict_includes_metadata(self):
        spec = _make_spec(metadata={"timeout_seconds": 30, "env": "prod"})
        d = spec.to_dict()
        assert d["metadata"] == {"timeout_seconds": 30, "env": "prod"}

    def test_from_dict_restores_metadata(self):
        spec = _make_spec(metadata={"key": "value"})
        restored = ObjectiveSpec.from_dict(spec.to_dict())
        assert restored.metadata == {"key": "value"}

    def test_from_dict_defaults_metadata_to_empty(self):
        spec = _make_spec()
        d = spec.to_dict()
        del d["metadata"]
        restored = ObjectiveSpec.from_dict(d)
        assert restored.metadata == {}


class TestAttemptLogDefaults:
    def test_default_evidence_is_empty_dict(self):
        log = AttemptLog(
            attempt_id="a",
            objective_id="b",
            task_id="c",
            attempt_number=1,
            status="passed",
        )
        assert log.evidence == {}

    def test_default_failure_reason_is_none(self):
        log = AttemptLog(
            attempt_id="a",
            objective_id="b",
            task_id="c",
            attempt_number=1,
            status="passed",
        )
        assert log.failure_reason is None


class TestObjectiveSpecValidateEdgeCases:
    def test_negative_max_attempts_raises_value_error(self):
        spec = _make_spec(max_attempts=-1)
        with pytest.raises(ValueError, match="max_attempts"):
            spec.validate()

    def test_whitespace_goal_raises_value_error(self):
        spec = _make_spec(goal="   ")
        with pytest.raises(ValueError, match="goal"):
            spec.validate()


class TestChecklistItem:
    def test_valid_item(self):
        item = ChecklistItem(instruction="verify the sum is correct", sensors=("read_file",))
        assert item.is_valid()

    def test_missing_instruction_is_invalid(self):
        item = ChecklistItem(instruction="", sensors=("read_file",))
        assert not item.is_valid()

    def test_missing_sensors_is_invalid(self):
        item = ChecklistItem(instruction="verify the sum is correct", sensors=())
        assert not item.is_valid()

    def test_to_dict_and_from_dict_roundtrip(self):
        item = ChecklistItem(instruction="check it", sensors=("read_file", "screenshot"))
        restored = ChecklistItem.from_dict(item.to_dict())
        assert restored == item

    def test_from_dict_malformed_missing_sensors_does_not_raise(self):
        item = ChecklistItem.from_dict({"instruction": "check it"})
        assert item.instruction == "check it"
        assert item.sensors == ()
        assert not item.is_valid()

    def test_from_dict_empty_dict_does_not_raise(self):
        item = ChecklistItem.from_dict({})
        assert not item.is_valid()

    def test_is_frozen(self):
        item = ChecklistItem(instruction="check it", sensors=("read_file",))
        with pytest.raises(AttributeError):
            item.instruction = "changed"  # type: ignore[misc]


class TestObjectiveSpecVerificationChecklist:
    def test_defaults_to_empty_tuple(self):
        spec = _make_spec()
        assert spec.verification_checklist == ()

    def test_roundtrip_via_to_dict_from_dict(self):
        items = (ChecklistItem(instruction="check it", sensors=("read_file",)),)
        spec = _make_spec(verification_checklist=items)
        restored = ObjectiveSpec.from_dict(spec.to_dict())
        assert restored.verification_checklist == items

    def test_from_dict_skips_non_dict_entries_without_raising(self):
        spec = _make_spec()
        d = spec.to_dict()
        d["verification_checklist"] = ["not-a-dict", 42, None]
        restored = ObjectiveSpec.from_dict(d)
        assert restored.verification_checklist == ()

    def test_from_dict_defaults_when_key_absent(self):
        spec = _make_spec()
        d = spec.to_dict()
        del d["verification_checklist"]
        restored = ObjectiveSpec.from_dict(d)
        assert restored.verification_checklist == ()


class TestTaskRecordObjectives:
    def test_objectives_can_be_set(self):
        record = TaskRecord(task_id="t-1", user_request="req", objectives=["obj-a", "obj-b"])
        assert record.objectives == ["obj-a", "obj-b"]

    def test_objectives_default_empty(self):
        record = TaskRecord(task_id="t-1", user_request="req")
        assert record.objectives == []
