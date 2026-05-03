"""
Concrete UnifiedAppObjectiveRunner handoff scenario classes.

Each class sets class-variable overrides only; all 9 test methods are
inherited from BaseHandoffScenario and run automatically by pytest.

Total: 7 scenarios × 15 assertions = 105 test cases.
"""
from __future__ import annotations

import pytest

from .base_orchestrator_scenarios import BaseHandoffScenario

pytestmark = pytest.mark.integration


class TestCliHandoffWithPlan(BaseHandoffScenario):
    """CLI task with a 2-sub-objective approved plan routes to cli_mcp."""

    task_description = "List files in the current directory and summarize them"
    domain = "cli"
    approved_plan = ["Inspect the current directory", "Summarize the result"]
    expected_domain = "cli"
    expected_target_server = "cli_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


class TestWebHandoffWithPlan(BaseHandoffScenario):
    """Web task with a 3-sub-objective approved plan routes to browser_mcp."""

    task_description = "Open GitHub and browse the issues page"
    domain = "web"
    approved_plan = [
        "Navigate to github.com",
        "Open the issues tab",
        "Report the open issue count",
    ]
    expected_domain = "web"
    expected_target_server = "browser_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


class TestDesktopHandoffWithPlan(BaseHandoffScenario):
    """Desktop task with an approved plan routes to desktop_mcp."""

    task_description = "Open Notepad and type a short note"
    domain = "desktop"
    approved_plan = ["Launch Notepad", "Type the note content", "Save and close"]
    expected_domain = "desktop"
    expected_target_server = "desktop_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


class TestMixedDomainResolvesToWeb(BaseHandoffScenario):
    """domain='mixed' must resolve to web/browser_mcp per _DOMAIN_TARGETS."""

    task_description = "Open GitHub repo page and check the latest commit"
    domain = "mixed"
    approved_plan = ["Open the GitHub repo page", "Read the latest commit message"]
    expected_domain = "web"
    expected_target_server = "browser_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


class TestBrowserAliasResolvesToWeb(BaseHandoffScenario):
    """domain='browser' is an alias — must resolve identically to 'web'."""

    task_description = "Search for Python documentation in the browser"
    domain = "browser"
    approved_plan = ["Open browser", "Navigate to docs.python.org"]
    expected_domain = "web"
    expected_target_server = "browser_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


class TestEmptyPlanForwarded(BaseHandoffScenario):
    """No approved_plan supplied — sub_objectives must be forwarded as []."""

    task_description = "Run a quick CLI health check"
    domain = "cli"
    approved_plan = []
    expected_domain = "cli"
    expected_target_server = "cli_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


class TestFailurePropagated(BaseHandoffScenario):
    """
    When the bridge returns status='failure', the bus payload must carry
    'failure'. History still records COMPLETED because UnifiedAppObjectiveRunner
    only marks FAILED on an exception, not on a non-success result status.
    """

    task_description = "Attempt a task that the backend will report as failed"
    domain = "cli"
    approved_plan = ["Run the sub-objective that fails"]
    expected_domain = "cli"
    expected_target_server = "cli_mcp"
    expected_final_status = "failure"
    bridge_result_status = "failure"
