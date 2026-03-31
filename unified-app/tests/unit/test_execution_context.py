"""Unit tests for ExecutionContext."""
import time
from unittest.mock import Mock

import pytest

import sys
from pathlib import Path

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

from execution_context import (
    ErrorRecord,
    ExecutionContext,
    ModuleResult,
)


class TestModuleResult:
    """Test ModuleResult dataclass."""
    
    def test_success_result(self):
        """Test successful module result."""
        result = ModuleResult(
            module="web_browser",
            status="success",
            output="Page loaded successfully"
        )
        
        assert result.is_success()
        assert not result.is_failure()
        assert result.error is None
    
    def test_failure_result(self):
        """Test failed module result."""
        result = ModuleResult(
            module="desktop_app",
            status="failure",
            output=None,
            error="Application not found"
        )
        
        assert result.is_failure()
        assert not result.is_success()
        assert result.error == "Application not found"
    
    def test_timestamp_auto_generated(self):
        """Test that timestamp is auto-generated."""
        before = time.time()
        result = ModuleResult(module="test", status="success", output="test")
        after = time.time()
        
        assert before <= result.timestamp <= after


class TestErrorRecord:
    """Test ErrorRecord dataclass."""
    
    def test_error_record_creation(self):
        """Test error record creation."""
        error = ErrorRecord(
            error_type="transient",
            error_message="Network timeout",
            attempted_action={"action": "navigate", "url": "https://example.com"}
        )
        
        assert error.error_type == "transient"
        assert error.error_message == "Network timeout"
        assert error.retry_count == 0
    
    def test_increment_retry(self):
        """Test retry count increment."""
        error = ErrorRecord(
            error_type="rate_limit",
            error_message="Too many requests",
            attempted_action={}
        )
        
        error.increment_retry()
        assert error.retry_count == 1
        
        error.increment_retry()
        assert error.retry_count == 2


class TestExecutionContext:
    """Test ExecutionContext."""
    
    def test_initialization(self):
        """Test context initialization."""
        context = ExecutionContext(objective="Test objective")
        
        assert context.objective == "Test objective"
        assert len(context.module_results) == 0
        assert len(context.learned_constraints) == 0
        assert len(context.accumulated_state) == 0
        assert len(context.error_history) == 0
        assert context.retry_count == 0
        assert context.fallback_level == 0
        assert context.checkpoint_id is None
    
    def test_add_result(self):
        """Test adding module result."""
        context = ExecutionContext(objective="Test")
        result = ModuleResult(module="web", status="success", output="OK")
        
        context.add_result("web", result)
        
        assert len(context.module_results) == 1
        assert context.module_results["web"] == result
    
    def test_add_error(self):
        """Test adding error record."""
        context = ExecutionContext(objective="Test")
        error = ErrorRecord(
            error_type="transient",
            error_message="Timeout",
            attempted_action={}
        )
        
        context.add_error(error)
        
        assert len(context.error_history) == 1
        assert context.retry_count == 1
        assert context.error_history[0] == error
    
    def test_add_constraint(self):
        """Test adding learned constraint."""
        context = ExecutionContext(objective="Test")
        
        context.add_constraint("Cannot use sudo commands")
        assert len(context.learned_constraints) == 1
        
        # Should deduplicate
        context.add_constraint("Cannot use sudo commands")
        assert len(context.learned_constraints) == 1
        
        context.add_constraint("Must use Windows commands")
        assert len(context.learned_constraints) == 2
    
    def test_update_state(self):
        """Test updating accumulated state."""
        context = ExecutionContext(objective="Test")
        
        context.update_state("file_created", "/tmp/test.txt")
        context.update_state("service_started", "nginx")
        
        assert context.accumulated_state["file_created"] == "/tmp/test.txt"
        assert context.accumulated_state["service_started"] == "nginx"
        
        # Should overwrite existing keys
        context.update_state("file_created", "/tmp/new.txt")
        assert context.accumulated_state["file_created"] == "/tmp/new.txt"
    
    def test_get_last_error(self):
        """Test getting last error."""
        context = ExecutionContext(objective="Test")
        
        assert context.get_last_error() is None
        
        error1 = ErrorRecord("type1", "msg1", {})
        error2 = ErrorRecord("type2", "msg2", {})
        
        context.add_error(error1)
        assert context.get_last_error() == error1
        
        context.add_error(error2)
        assert context.get_last_error() == error2
    
    def test_get_result(self):
        """Test getting specific module result."""
        context = ExecutionContext(objective="Test")
        result = ModuleResult(module="web", status="success", output="OK")
        
        assert context.get_result("web") is None
        
        context.add_result("web", result)
        assert context.get_result("web") == result
        assert context.get_result("desktop") is None
    
    def test_get_successful_results(self):
        """Test getting successful results."""
        context = ExecutionContext(objective="Test")
        
        success1 = ModuleResult(module="web", status="success", output="OK")
        success2 = ModuleResult(module="cli", status="success", output="Done")
        failure = ModuleResult(module="desktop", status="failure", output=None, error="Failed")
        
        context.add_result("web", success1)
        context.add_result("cli", success2)
        context.add_result("desktop", failure)
        
        successful = context.get_successful_results()
        assert len(successful) == 2
        assert success1 in successful
        assert success2 in successful
        assert failure not in successful
    
    def test_get_failed_results(self):
        """Test getting failed results."""
        context = ExecutionContext(objective="Test")
        
        success = ModuleResult(module="web", status="success", output="OK")
        failure1 = ModuleResult(module="desktop", status="failure", output=None, error="Error 1")
        failure2 = ModuleResult(module="cli", status="failure", output=None, error="Error 2")
        
        context.add_result("web", success)
        context.add_result("desktop", failure1)
        context.add_result("cli", failure2)
        
        failed = context.get_failed_results()
        assert len(failed) == 2
        assert failure1 in failed
        assert failure2 in failed
        assert success not in failed
    
    def test_has_errors(self):
        """Test checking for errors."""
        context = ExecutionContext(objective="Test")
        
        assert not context.has_errors()
        
        error = ErrorRecord("type", "msg", {})
        context.add_error(error)
        
        assert context.has_errors()
    
    def test_reset_retry_count(self):
        """Test resetting retry count."""
        context = ExecutionContext(objective="Test")
        
        error = ErrorRecord("type", "msg", {})
        context.add_error(error)
        context.add_error(error)
        
        assert context.retry_count == 2
        
        context.reset_retry_count()
        assert context.retry_count == 0
    
    def test_increment_fallback_level(self):
        """Test incrementing fallback level."""
        context = ExecutionContext(objective="Test")
        
        assert context.fallback_level == 0
        
        context.increment_fallback_level()
        assert context.fallback_level == 1
        
        context.increment_fallback_level()
        assert context.fallback_level == 2
    
    def test_to_summary(self):
        """Test generating context summary."""
        context = ExecutionContext(objective="Test objective")
        
        # Add some data
        context.add_result("web", ModuleResult("web", "success", "OK"))
        context.add_result("desktop", ModuleResult("desktop", "failure", None, "Error"))
        context.add_error(ErrorRecord("transient", "Timeout", {}))
        context.add_constraint("Use Windows commands")
        context.update_state("file", "/tmp/test.txt")
        
        summary = context.to_summary()
        
        assert summary["objective"] == "Test objective"
        assert summary["module_count"] == 2
        assert summary["successful_modules"] == 1
        assert summary["failed_modules"] == 1
        assert summary["error_count"] == 1
        assert summary["retry_count"] == 1
        assert summary["fallback_level"] == 0
        assert summary["constraints_learned"] == 1
        assert "file" in summary["state_keys"]
