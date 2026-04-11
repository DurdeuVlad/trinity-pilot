---
id: TC-CROSS-01
title: Commit a Change, Check It in VS Code, Then Look It Up Online
domain: cross
difficulty: Very Hard
goal: Coordinate CLI, desktop, and browser work to create a commit, verify it in VS Code, and confirm commit history on GitHub.
user_prompt: >
  Create a quick test file in C:\Temp\trinity_cross_test, commit it to git with a message that includes today's date, then open that folder in VS Code and make sure the commit shows up in Source Control, and finally go to the trinity-pilot GitHub page and confirm there's a commit history there.
expected_outcome:
  - TaskStatus.COMPLETED
  - result_data.status == success
  - result_data.commit_hash is non-empty
  - result_data.desktop_confirmed == true
  - result_data.browser_confirmed == true
observation_policy:
  bounded_drift: true
  drift_time_budget_seconds: 150
  repeated_action_threshold: 3
  repeated_failure_threshold: 2
stop_policy:
  approval_required_on:
    - captcha
    - mfa
    - destructive_out_of_scope_action
danger_flags:
  - destructive_out_of_scope_action
  - credential_entry
artifact_checks:
  - flight_report_present
  - prompts_captured
  - responses_captured
  - screenshots_captured
postmortem_questions:
  - Did the orchestrator preserve CLI -> desktop -> browser ordering?
  - Did VS Code Source Control confirm the intended commit?
  - Was cleanup performed after verification rather than before?
env_vars_required:
  - LIVE_GEMINI_SMOKE=1
  - RUN_DESKTOP_INTEGRATION=1
  - RUN_BROWSER_INTEGRATION=1
  - GEMINI_API_KEY
platform: Windows
---

# TC-CROSS-01 - Commit a Change, Check It in VS Code, Then Look It Up Online

## Context

This is a cross-domain coordination case requiring CLI, desktop, and browser backends.

## Why It's Hard

- Ordering is implicit and must be inferred correctly.
- VS Code Source Control is a more complex desktop surface than a simple Windows dialog.
- The task spans three backends with one final coherent success condition.
- Cleanup is implied by the “quick test” framing and must happen last.

## Expected Execution Trace

1. CLI: create the repo, create a test file, and commit it with a dated message.
2. Desktop: open the folder in VS Code and confirm the commit appears in Source Control.
3. Browser: open the GitHub repository and confirm commit history is visible.
4. CLI: remove the temporary test directory.

## Failure Modes to Watch

| Symptom | Root cause |
|---|---|
| VS Code shows no changes or no commit | Desktop step started before CLI commit completed |
| Browser shows 404 | Wrong GitHub repository URL inferred |
| Commit message not found in Source Control | Agent read the wrong desktop element |
| Cleanup skipped | Agent stopped after browser confirmation |
