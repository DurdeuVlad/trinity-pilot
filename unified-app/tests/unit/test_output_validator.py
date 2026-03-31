"""Unit tests for OutputValidator."""
from types import SimpleNamespace

import pytest

import sys
from pathlib import Path

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

from output_validator import OutputValidator, ValidationResult


class TestValidationResult:
    """Test ValidationResult dataclass."""
    
    def test_has_errors(self):
        """Test has_errors method."""
        result = ValidationResult(is_valid=True, confidence=1.0, errors=[])
        assert not result.has_errors()
        
        result = ValidationResult(is_valid=False, confidence=0.0, errors=["Error 1"])
        assert result.has_errors()
    
    def test_has_warnings(self):
        """Test has_warnings method."""
        result = ValidationResult(is_valid=True, confidence=1.0, warnings=[])
        assert not result.has_warnings()
        
        result = ValidationResult(is_valid=True, confidence=0.85, warnings=["Warning 1"])
        assert result.has_warnings()
    
    def test_to_summary(self):
        """Test summary generation."""
        result = ValidationResult(is_valid=True, confidence=1.0)
        assert "Valid" in result.to_summary()
        assert "1.00" in result.to_summary()
        
        result = ValidationResult(is_valid=True, confidence=0.85, warnings=["Warning"])
        summary = result.to_summary()
        assert "Valid" in summary
        assert "0.85" in summary
        assert "warnings" in summary
        
        result = ValidationResult(is_valid=False, confidence=0.0, errors=["Error 1", "Error 2"])
        summary = result.to_summary()
        assert "Invalid" in summary
        assert "Error 1" in summary
        assert "Error 2" in summary


class TestActionValidation:
    """Test action validation."""
    
    def test_valid_action(self):
        """Test validation of valid action."""
        validator = OutputValidator()
        
        action = {
            "rationale": "Navigate to the website to check status",
            "action_type": "browse",
            "module": "web_browser",
            "parameters": {"action": "navigate", "url": "https://example.com"},
            "done": False
        }
        
        result = validator.validate_action(action)
        
        assert result.is_valid
        assert result.confidence == 1.0
        assert len(result.errors) == 0
    
    def test_valid_done_action(self):
        """Test validation of done action."""
        validator = OutputValidator()
        
        action = {
            "rationale": "Task completed successfully",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True,
            "result_summary": "Successfully completed the task"
        }
        
        result = validator.validate_action(action)
        
        assert result.is_valid
        assert result.confidence == 1.0
    
    def test_missing_required_field(self):
        """Test validation with missing required field."""
        validator = OutputValidator()
        
        action = {
            "action_type": "browse",
            "module": "web_browser",
            "parameters": {},
            "done": False
            # Missing "rationale"
        }
        
        result = validator.validate_action(action)
        
        assert not result.is_valid
        assert result.confidence == 0.0
        assert any("rationale" in err.lower() for err in result.errors)
    
    def test_invalid_action_type(self):
        """Test validation with invalid action type."""
        validator = OutputValidator()
        
        action = {
            "rationale": "Test",
            "action_type": "invalid_type",
            "module": "web_browser",
            "parameters": {},
            "done": False
        }
        
        result = validator.validate_action(action)
        
        assert not result.is_valid
        assert any("action_type" in err.lower() for err in result.errors)
    
    def test_invalid_module(self):
        """Test validation with invalid module."""
        validator = OutputValidator()
        
        action = {
            "rationale": "Test",
            "action_type": "browse",
            "module": "invalid_module",
            "parameters": {},
            "done": False
        }
        
        result = validator.validate_action(action)
        
        assert not result.is_valid
        assert any("module" in err.lower() for err in result.errors)
    
    def test_invalid_parameters_type(self):
        """Test validation with non-dict parameters."""
        validator = OutputValidator()
        
        action = {
            "rationale": "Test",
            "action_type": "browse",
            "module": "web_browser",
            "parameters": "not a dict",
            "done": False
        }
        
        result = validator.validate_action(action)
        
        assert not result.is_valid
        assert any("parameters" in err.lower() for err in result.errors)
    
    def test_invalid_done_type(self):
        """Test validation with non-boolean done flag."""
        validator = OutputValidator()
        
        action = {
            "rationale": "Test",
            "action_type": "browse",
            "module": "web_browser",
            "parameters": {},
            "done": "true"  # String instead of boolean
        }
        
        result = validator.validate_action(action)
        
        assert not result.is_valid
        assert any("done" in err.lower() for err in result.errors)
    
    def test_done_with_module_warning(self):
        """Test that done=true with module!=null generates warning."""
        validator = OutputValidator()
        
        action = {
            "rationale": "Test",
            "action_type": "done",
            "module": "web_browser",  # Should be None
            "parameters": {},
            "done": True
        }
        
        result = validator.validate_action(action)
        
        assert result.is_valid  # Still valid, just warning
        assert result.confidence < 1.0
        assert len(result.warnings) > 0
        assert any("module" in warn.lower() for warn in result.warnings)
    
    def test_short_rationale_warning(self):
        """Test that short rationale generates warning."""
        validator = OutputValidator()
        
        action = {
            "rationale": "Short",  # Less than 10 chars
            "action_type": "browse",
            "module": "web_browser",
            "parameters": {},
            "done": False
        }
        
        result = validator.validate_action(action)
        
        assert result.is_valid
        assert result.confidence < 1.0
        assert any("rationale" in warn.lower() for warn in result.warnings)
    
    def test_done_without_result_summary_warning(self):
        """Test that done=true without result_summary generates warning."""
        validator = OutputValidator()
        
        action = {
            "rationale": "Task complete",
            "action_type": "done",
            "module": None,
            "parameters": {},
            "done": True
            # Missing result_summary
        }
        
        result = validator.validate_action(action)
        
        assert result.is_valid
        assert len(result.warnings) > 0
        assert any("result_summary" in warn.lower() for warn in result.warnings)
    
    def test_non_dict_action(self):
        """Test validation with non-dict action."""
        validator = OutputValidator()
        
        result = validator.validate_action("not a dict")
        
        assert not result.is_valid
        assert result.confidence == 0.0
        assert len(result.errors) > 0


class TestResultValidation:
    """Test result validation."""
    
    def test_valid_result(self):
        """Test validation of valid result."""
        validator = OutputValidator()
        
        result_obj = SimpleNamespace(status="success", output="Task completed")
        result = validator.validate_result(result_obj)
        
        assert result.is_valid
        assert result.confidence == 1.0
    
    def test_none_result_warning(self):
        """Test that None result generates warning."""
        validator = OutputValidator()
        
        result = validator.validate_result(None)
        
        assert result.is_valid
        assert result.confidence < 1.0
        assert len(result.warnings) > 0
        assert any("none" in warn.lower() for warn in result.warnings)
    
    def test_type_mismatch_error(self):
        """Test that type mismatch generates error."""
        validator = OutputValidator()
        
        result = validator.validate_result("string result", expected_type=dict)
        
        assert not result.is_valid
        assert any("type" in err.lower() for err in result.errors)
    
    def test_failure_status_error(self):
        """Test that failure status generates error."""
        validator = OutputValidator()
        
        result_obj = SimpleNamespace(status="failure", error="Something went wrong")
        result = validator.validate_result(result_obj)
        
        assert not result.is_valid
        assert any("failure" in err.lower() for err in result.errors)
    
    def test_unexpected_status_warning(self):
        """Test that unexpected status generates warning."""
        validator = OutputValidator()
        
        result_obj = SimpleNamespace(status="unknown_status")
        result = validator.validate_result(result_obj)
        
        assert result.is_valid
        assert len(result.warnings) > 0
        assert any("status" in warn.lower() for warn in result.warnings)
    
    def test_error_field_present(self):
        """Test that error field generates error."""
        validator = OutputValidator()
        
        result_obj = SimpleNamespace(error="An error occurred")
        result = validator.validate_result(result_obj)
        
        assert not result.is_valid
        assert any("error" in err.lower() for err in result.errors)
    
    def test_skip_error_status_check(self):
        """Test skipping error status check."""
        validator = OutputValidator()
        
        result_obj = SimpleNamespace(status="failure", error="Error")
        result = validator.validate_result(result_obj, check_error_status=False)
        
        # Should still catch error field
        assert not result.is_valid
    
    def test_valid_partial_status(self):
        """Test that partial status is valid."""
        validator = OutputValidator()
        
        result_obj = SimpleNamespace(status="partial", output="Partial completion")
        result = validator.validate_result(result_obj)
        
        assert result.is_valid
    
    def test_valid_cancelled_status(self):
        """Test that cancelled status is valid."""
        validator = OutputValidator()
        
        result_obj = SimpleNamespace(status="cancelled")
        result = validator.validate_result(result_obj)
        
        assert result.is_valid


class TestJsonSchemaValidation:
    """Test JSON schema validation."""
    
    def test_valid_schema(self):
        """Test validation of valid schema."""
        validator = OutputValidator()
        
        data = {"name": "test", "value": 123, "active": True}
        result = validator.validate_json_schema(data, ["name", "value", "active"])
        
        assert result.is_valid
        assert result.confidence == 1.0
    
    def test_missing_required_field(self):
        """Test missing required field."""
        validator = OutputValidator()
        
        data = {"name": "test", "value": 123}
        result = validator.validate_json_schema(data, ["name", "value", "active"])
        
        assert not result.is_valid
        assert any("active" in err.lower() for err in result.errors)
    
    def test_none_field_warning(self):
        """Test that None field generates warning."""
        validator = OutputValidator()
        
        data = {"name": "test", "value": None}
        result = validator.validate_json_schema(data, ["name", "value"])
        
        assert result.is_valid
        assert result.confidence < 1.0
        assert len(result.warnings) > 0
        assert any("value" in warn.lower() for warn in result.warnings)
    
    def test_non_dict_data(self):
        """Test validation with non-dict data."""
        validator = OutputValidator()
        
        result = validator.validate_json_schema("not a dict", ["field"])
        
        assert not result.is_valid
        assert result.confidence == 0.0


class TestConfidenceScoring:
    """Test confidence score calculation."""
    
    def test_perfect_confidence(self):
        """Test perfect confidence with no errors or warnings."""
        validator = OutputValidator()
        
        confidence = validator._calculate_confidence([], [])
        assert confidence == 1.0
    
    def test_zero_confidence_with_errors(self):
        """Test zero confidence with errors."""
        validator = OutputValidator()
        
        confidence = validator._calculate_confidence(["Error 1"], [])
        assert confidence == 0.0
        
        confidence = validator._calculate_confidence(["Error 1", "Error 2"], ["Warning"])
        assert confidence == 0.0
    
    def test_reduced_confidence_with_warnings(self):
        """Test reduced confidence with warnings."""
        validator = OutputValidator()
        
        # 1 warning -> 0.85
        confidence = validator._calculate_confidence([], ["Warning 1"])
        assert confidence == 0.85
        
        # 2 warnings -> 0.7
        confidence = validator._calculate_confidence([], ["Warning 1", "Warning 2"])
        assert confidence == 0.7
        
        # 3+ warnings -> 0.5
        confidence = validator._calculate_confidence([], ["W1", "W2", "W3"])
        assert confidence == 0.5
        
        confidence = validator._calculate_confidence([], ["W1", "W2", "W3", "W4"])
        assert confidence == 0.5
