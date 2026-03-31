"""Output validation for AI-generated actions and module results."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of output validation."""
    
    is_valid: bool
    confidence: float  # 0.0 to 1.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    
    def has_errors(self) -> bool:
        """Check if validation found errors."""
        return len(self.errors) > 0
    
    def has_warnings(self) -> bool:
        """Check if validation found warnings."""
        return len(self.warnings) > 0
    
    def to_summary(self) -> str:
        """Generate a summary string for logging."""
        if self.is_valid:
            if self.warnings:
                return f"Valid (confidence={self.confidence:.2f}, {len(self.warnings)} warnings)"
            return f"Valid (confidence={self.confidence:.2f})"
        return f"Invalid: {'; '.join(self.errors)}"


class OutputValidator:
    """Validates AI-generated actions and module execution results."""
    
    VALID_ACTION_TYPES = ["browse", "desktop", "cli", "done"]
    VALID_MODULES = ["web_browser", "desktop_app", "cli_runner", None]
    REQUIRED_ACTION_FIELDS = ["rationale", "action_type", "module", "parameters", "done"]
    
    def validate_action(self, action: dict) -> ValidationResult:
        """Validate AI-generated action before execution.
        
        Args:
            action: Action dictionary from AI
            
        Returns:
            ValidationResult with validation status
        """
        errors = []
        warnings = []
        
        # Type check
        if not isinstance(action, dict):
            errors.append(f"Action must be a dictionary, got {type(action)}")
            return ValidationResult(is_valid=False, confidence=0.0, errors=errors)
        
        # Required fields check
        for field in self.REQUIRED_ACTION_FIELDS:
            if field not in action:
                errors.append(f"Missing required field: {field}")
        
        # Action type validation
        action_type = action.get("action_type")
        if action_type not in self.VALID_ACTION_TYPES:
            errors.append(f"Invalid action_type: {action_type}. Must be one of {self.VALID_ACTION_TYPES}")
        
        # Module validation
        module = action.get("module")
        if module not in self.VALID_MODULES:
            errors.append(f"Invalid module: {module}. Must be one of {self.VALID_MODULES}")
        
        # Parameters validation
        parameters = action.get("parameters")
        if not isinstance(parameters, dict):
            errors.append(f"Parameters must be a dictionary, got {type(parameters)}")
        
        # Done flag validation
        done = action.get("done")
        if not isinstance(done, bool):
            errors.append(f"'done' must be a boolean, got {type(done)}")
        elif done and module is not None:
            warnings.append("done=true should have module=null")
        
        # Rationale validation
        rationale = action.get("rationale")
        if rationale and not isinstance(rationale, str):
            warnings.append(f"Rationale should be a string, got {type(rationale)}")
        elif rationale and len(rationale) < 10:
            warnings.append("Rationale is very short (< 10 chars)")
        
        # Result summary validation
        if done:
            result_summary = action.get("result_summary")
            if not result_summary:
                warnings.append("done=true should include result_summary")
        
        # Confidence scoring
        confidence = self._calculate_confidence(errors, warnings)
        
        is_valid = len(errors) == 0
        
        if not is_valid:
            logger.warning(f"[OutputValidator] Action validation failed: {errors}")
        elif warnings:
            logger.info(f"[OutputValidator] Action validation passed with warnings: {warnings}")
        
        return ValidationResult(
            is_valid=is_valid,
            confidence=confidence,
            errors=errors,
            warnings=warnings
        )
    
    def validate_result(
        self,
        result: Any,
        expected_type: Optional[type] = None,
        check_error_status: bool = True
    ) -> ValidationResult:
        """Validate module execution result.
        
        Args:
            result: Result from module execution
            expected_type: Optional expected type for the result
            check_error_status: Whether to check for error status in result
            
        Returns:
            ValidationResult with validation status
        """
        errors = []
        warnings = []
        
        # None check
        if result is None:
            warnings.append("Result is None")
        
        # Type check
        if expected_type and result is not None and not isinstance(result, expected_type):
            errors.append(f"Expected type {expected_type.__name__}, got {type(result).__name__}")
        
        # Check for error indicators in result
        if check_error_status and hasattr(result, "status"):
            status = getattr(result, "status")
            if status == "failure":
                error_msg = getattr(result, "error", None) or getattr(result, "message", "unknown")
                errors.append(f"Module reported failure: {error_msg}")
            elif status not in ["success", "partial", "cancelled"]:
                warnings.append(f"Unexpected status: {status}")
        
        # Check for error field
        if hasattr(result, "error") and getattr(result, "error"):
            error_msg = getattr(result, "error")
            if error_msg and error_msg != "":
                errors.append(f"Result contains error: {error_msg}")
        
        # Confidence scoring
        confidence = self._calculate_confidence(errors, warnings)
        
        is_valid = len(errors) == 0
        
        if not is_valid:
            logger.warning(f"[OutputValidator] Result validation failed: {errors}")
        elif warnings:
            logger.debug(f"[OutputValidator] Result validation passed with warnings: {warnings}")
        
        return ValidationResult(
            is_valid=is_valid,
            confidence=confidence,
            errors=errors,
            warnings=warnings
        )
    
    def validate_json_schema(self, data: dict, required_fields: list[str]) -> ValidationResult:
        """Validate that a dictionary contains required fields.
        
        Args:
            data: Dictionary to validate
            required_fields: List of required field names
            
        Returns:
            ValidationResult with validation status
        """
        errors = []
        warnings = []
        
        if not isinstance(data, dict):
            errors.append(f"Expected dictionary, got {type(data)}")
            return ValidationResult(is_valid=False, confidence=0.0, errors=errors)
        
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: {field}")
            elif data[field] is None:
                warnings.append(f"Field '{field}' is None")
        
        confidence = self._calculate_confidence(errors, warnings)
        is_valid = len(errors) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            confidence=confidence,
            errors=errors,
            warnings=warnings
        )
    
    def _calculate_confidence(self, errors: list[str], warnings: list[str]) -> float:
        """Calculate confidence score based on errors and warnings.
        
        Args:
            errors: List of validation errors
            warnings: List of validation warnings
            
        Returns:
            Confidence score from 0.0 to 1.0
        """
        if errors:
            return 0.0
        elif len(warnings) >= 3:
            return 0.5
        elif len(warnings) == 2:
            return 0.7
        elif len(warnings) == 1:
            return 0.85
        else:
            return 1.0
