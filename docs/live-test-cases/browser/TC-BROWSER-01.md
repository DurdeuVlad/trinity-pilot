---
id: TC-BROWSER-01
title: GitHub Bug Issue Lookup
domain: browser
difficulty: Hard
goal: Find the title and number of the first open bug in the microsoft/vscode GitHub repository.
user_prompt: >
  Go to the microsoft/vscode GitHub repo and tell me the title and number of the first open bug.
expected_outcome:
  - TaskStatus.COMPLETED
  - result_data.status == success
  - result_data.issue_number is non-empty
  - result_data.title is non-empty
observation_policy:
  bounded_drift: true
  drift_time_budget_seconds: 90
  repeated_action_threshold: 3
  repeated_failure_threshold: 2
stop_policy:
  approval_required_on:
    - captcha
    - mfa
    - destructive_out_of_scope_action
danger_flags:
  - credential_entry
  - account_mutation
artifact_checks:
  - flight_report_present
  - prompts_captured
  - responses_captured
  - screenshots_captured
postmortem_questions:
  - Did the agent apply the correct bug filter?
  - Did it extract both the issue number and title structurally?
  - Did it stop on the correct issue rather than a sidebar or related item?
env_vars_required:
  - LIVE_GEMINI_SMOKE=1
  - RUN_BROWSER_INTEGRATION=1
  - GEMINI_API_KEY
platform: Windows
---

# TC-BROWSER-01 - GitHub Bug Issue Lookup

## Context

Site: `https://github.com` (public, no login required).

## Why It's Hard

- The agent must map vague intent to a specific issue-filter sequence.
- The label filter is dynamic and requires click plus wait, not just raw text extraction.
- The task crosses multiple GitHub page states before the data is visible.
- The result must return structured values, not only prose.

## Expected Execution Trace

1. Open `https://github.com/microsoft/vscode`.
2. Navigate to the Issues tab.
3. Apply the `bug` label filter.
4. Open the first listed issue.
5. Read the title and issue number.
6. Return both in `result_data`.

## Failure Modes to Watch

| Symptom | Root cause |
|---|---|
| Lands on search results page | Agent searched instead of navigating directly |
| No issues shown | Label filter not applied |
| Title is a sidebar or related item | Agent read the wrong DOM element |
| result_data missing keys | Agent described the result in text instead of structured output |
