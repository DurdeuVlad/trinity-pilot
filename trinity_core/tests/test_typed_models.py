"""Tests for typed models in Desktop and CLI modules."""
import pytest
from pydantic import ValidationError
import sys
import os

# Add module paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../api-accessibility-poc"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../cli-automation-poc"))

from desktop_io_models import DesktopTaskInput, DesktopTaskResult
from cli_io_models import CLITaskInput, CLITaskResult

class TestDesktopModels:
    def test_desktop_input_validation(self):
        """Test Desktop input validation."""
        # Valid input
        input_data = DesktopTaskInput(
            objective="Test",
            app_context="Notepad"
        )
        assert input_data.max_retries == 3  # Default
        
        # Invalid max_retries
        with pytest.raises(ValidationError):
            DesktopTaskInput(
                objective="Test",
                app_context="Notepad",
                max_retries=15  # > 10
            )
    
    def test_desktop_result_success_rate(self):
        """Test success rate calculation."""
        result = DesktopTaskResult(
            status="success",
            successful_actions=8,
            total_actions=10
        )
        assert result.success_rate == 80.0

class TestCLIModels:
    def test_cli_input_validation(self):
        """Test CLI input validation."""
        input_data = CLITaskInput(
            objective="Test",
            expected_outcome="Success"
        )
        assert input_data.timeout == 300  # Default
        
        # Invalid timeout
        with pytest.raises(ValidationError):
            CLITaskInput(
                objective="Test",
                expected_outcome="Success",
                timeout=5000  # > 3600
            )
    
    def test_cli_result_success_rate(self):
        """Test success rate calculation."""
        result = CLITaskResult(
            status="success",
            total_actions=5,
            successful_actions=4,
            attempts=1
        )
        assert result.success_rate == 80.0
