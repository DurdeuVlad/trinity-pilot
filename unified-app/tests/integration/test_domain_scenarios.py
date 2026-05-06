"""
Domain scenario test suite: single-domain and cross-domain handoff scenarios.

Structure:
  - CLI:      1 easy + 1 moderate
  - Web:      1 easy + 1 moderate
  - Desktop:  1 easy + 1 moderate
  - Cross:    3 scenarios (easy / moderate / complex), each with
              3 objectives and 6 objective prompts in the approved_plan

Total: 9 scenarios x 15 assertions = 135 test cases.

All scenarios inherit from BaseHandoffScenario and require zero fixture code.
Cross-domain tasks use domain='web' or domain='mixed'; both resolve to
browser_mcp which acts as the coordinating backend.
"""
from __future__ import annotations

import pytest

from .base_orchestrator_scenarios import BaseHandoffScenario

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCliEasyRunHealthCheck(BaseHandoffScenario):
    """
    CLI easy: single command, unambiguous success criterion.
    Confirms the orchestrator forwards a one-sub-objective plan without modification.
    """

    task_description = "Check whether the Python interpreter is available and report its version"
    domain = "cli"
    approved_plan = [
        "Run 'python --version' and capture the output",
    ]
    expected_domain = "cli"
    expected_target_server = "cli_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


class TestCliModerateOrganizeDownloads(BaseHandoffScenario):
    """
    CLI moderate: sandboxed Downloads cleanup pipeline.
    Four sub-objectives cover discovery, classification, file moves, and manifest output.
    Tests that a realistic pipeline plan is forwarded intact.
    """

    task_description = (
        "Organize the sandboxed downloads folder at "
        "_runtime/domain_scenarios/cli_moderate_downloads/inbox by file type, "
        "then write a manifest of the files that were moved"
    )
    domain = "cli"
    approved_plan = [
        "Inspect _runtime/domain_scenarios/cli_moderate_downloads/inbox and list every file with its extension",
        "Create documents, images, installers, and archives folders under _runtime/domain_scenarios/cli_moderate_downloads/organized",
        "Move only .pdf, .docx, and .txt files to documents; .png and .jpg files to images; .exe and .msi files to installers; .zip files to archives; leave .tmp and extensionless files in inbox",
        "Write _runtime/domain_scenarios/cli_moderate_downloads/organized/manifest.txt with the moved file names grouped by destination, skipped file names, and Total moved: 8",
    ]
    expected_domain = "cli"
    expected_target_server = "cli_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------

class TestWebEasyNavigateToDocumentation(BaseHandoffScenario):
    """
    Web easy: navigate to a known URL and confirm page load.
    Simplest possible browser task: one sub-objective, one assertion.
    """

    task_description = "Open the Python documentation homepage"
    domain = "web"
    approved_plan = [
        "Navigate to docs.python.org and confirm the page loaded",
    ]
    expected_domain = "web"
    expected_target_server = "browser_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


class TestWebModerateSearchAndExtract(BaseHandoffScenario):
    """
    Web moderate: multi-sub-objective search, sort, and structured extraction.
    Involves navigation, interaction, filtering, and data extraction.
    Verifies that a four-sub-objective browser plan is forwarded intact.
    """

    task_description = (
        "Search GitHub for the top Python async libraries, "
        "filter by star count, and extract the top 3 names and descriptions"
    )
    domain = "web"
    approved_plan = [
        "Navigate to github.com/search?q=python+async&type=repositories",
        "Sort results by star count descending",
        "Extract the repository name, description, and star count for the first 3 results",
        "Verify each result is a Python repository before reporting",
    ]
    expected_domain = "web"
    expected_target_server = "browser_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


# ---------------------------------------------------------------------------
# Desktop
# ---------------------------------------------------------------------------

class TestDesktopEasyOpenApplication(BaseHandoffScenario):
    """
    Desktop easy: launch a single application.
    Baseline desktop scenario: one sub-objective, one application.
    """

    task_description = "Open Notepad"
    domain = "desktop"
    approved_plan = [
        "Click the Start menu and launch Notepad",
    ]
    expected_domain = "desktop"
    expected_target_server = "desktop_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


class TestDesktopModerateCreateFormattedNote(BaseHandoffScenario):
    """
    Desktop moderate: create a structured document via GUI.
    Four sub-objectives: open, type header, add sections, save to a specific path.
    Tests that a realistic GUI workflow plan is forwarded without truncation.
    """

    task_description = (
        "Create a meeting notes template in Notepad with sections for "
        "attendees, agenda, and action items, then save it to the Desktop"
    )
    domain = "desktop"
    approved_plan = [
        "Open Notepad",
        "Type the document header: 'Meeting Notes - [Date]'",
        "Add three sections: Attendees, Agenda, Action Items with placeholder lines",
        "Save the file as meeting_notes_template.txt on the Desktop",
    ]
    expected_domain = "desktop"
    expected_target_server = "desktop_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


# ---------------------------------------------------------------------------
# Cross-domain
# ---------------------------------------------------------------------------

class TestCrossDomainEasyWebResearchAndSave(BaseHandoffScenario):
    """
    Cross-domain easy: Web retrieval + CLI persistence + verification.

    Objectives:
      1. Retrieve content from the web             (sub-objectives 1-2)
      2. Persist the content to disk via CLI       (sub-objectives 3-4)
      3. Verify the saved result                   (sub-objectives 5-6)

    Primary domain is 'web' because the entry point is a browser action.
    browser_mcp coordinates the full six-sub-objective plan.
    """

    task_description = (
        "Look up the current Python release notes on python.org "
        "and save the key points to a local file"
    )
    domain = "web"
    approved_plan = [
        # Objective 1: retrieve
        "Navigate to python.org/downloads and locate the latest release section",
        "Extract the version number and the top 5 highlighted changes",
        # Objective 2: persist
        "Open a terminal and create the file python_release_notes.txt",
        "Write the extracted version number and change list into the file",
        # Objective 3: verify
        "Confirm the file exists and contains the expected version string",
        "Print the file path and line count as the final result",
    ]
    expected_domain = "web"
    expected_target_server = "browser_mcp"
    expected_final_status = "success"
    bridge_result_status = "success"


class TestCrossDomainModerateSystemStatusReport(BaseHandoffScenario):
    """
    Cross-domain moderate: CLI diagnostics + Web dashboard cross-check + Desktop report.

    Objectives:
      1. Gather system metrics via CLI             (sub-objectives 1-2)
      2. Cross-check metrics against web dashboard (sub-objectives 3-4)
      3. Write the validated report via desktop GUI (sub-objectives 5-6)

    domain='mixed' stays mixed so Core coordinates sub-objective routing.
    """

    task_description = (
        "Collect CPU, memory, and disk metrics from the terminal, "
        "verify them against the local monitoring dashboard, "
        "and create a status report in Notepad"
    )
    domain = "mixed"
    approved_plan = [
        # Objective 1: CLI diagnostics
        "Run 'wmic cpu get loadpercentage' and 'systeminfo' to capture CPU and memory usage",
        "Run 'dir C:\\ /s' to measure disk usage and summarise free space on each drive",
        # Objective 2: dashboard cross-check
        "Open the monitoring dashboard at http://localhost:3000 in the browser",
        "Locate the CPU, memory, and disk panels and compare values with the CLI output",
        # Objective 3: desktop report
        "Open Notepad and paste the CLI metrics alongside the dashboard readings",
        "Save the file as system_status_report.txt with today's date in the filename",
    ]
    expected_domain = "mixed"
    expected_target_server = ""
    expected_final_status = "success"
    bridge_result_status = "success"


class TestCrossDomainComplexDeploymentVerification(BaseHandoffScenario):
    """
    Cross-domain complex: post-deployment verification spanning all three domains.

    Objectives:
      1. CLI - confirm process running and health endpoint responds (sub-objectives 1-2)
      2. Web - smoke test the deployed UI and authenticated flow     (sub-objectives 3-4)
      3. Desktop - append deployment log entry and save summary      (sub-objectives 5-6)

    domain='mixed' stays mixed so Core coordinates sub-objective routing.
    This is the most complex scenario: it exercises CLI, browser, and desktop
    capabilities in a single approved plan with a hard dependency chain.
    """

    task_description = (
        "After a deployment: verify the service process is running via CLI, "
        "confirm the UI responds correctly in the browser, "
        "then append a success entry to the deployment log and save a summary note"
    )
    domain = "mixed"
    approved_plan = [
        # Objective 1: CLI process and health check
        "Run 'tasklist | findstr app.exe' to confirm the service process is running",
        "Run 'curl -s http://localhost:8080/health' and verify the JSON response contains status=ok",
        # Objective 2: browser smoke test
        "Navigate to http://localhost:8080 in the browser and confirm the homepage loads",
        "Submit the test credentials on the login form and verify the dashboard page appears",
        # Objective 3: record result
        "Open logs/deployment.log in a text editor and append a timestamped success entry",
        "Save a deployment summary as deploy_done.txt on the Desktop with version and timestamp",
    ]
    expected_domain = "mixed"
    expected_target_server = ""
    expected_final_status = "success"
    bridge_result_status = "success"
