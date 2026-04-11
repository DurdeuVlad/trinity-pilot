---
id: TC-DESKTOP-01
title: Write a Note and Save It
domain: desktop
difficulty: Hard
goal: Use Notepad to write a note, save it to C:\Temp, reopen it, and confirm the content.
user_prompt: >
  Open Notepad, write 'Meeting notes: unique-marker-XK92' in it, save it to the Temp folder as meeting_notes.txt, then reopen the file and confirm the text is still there.
expected_outcome:
  - TaskStatus.COMPLETED
  - result_data.status == success
observation_policy:
  bounded_drift: true
  drift_time_budget_seconds: 90
  repeated_action_threshold: 3
  repeated_failure_threshold: 2
stop_policy:
  approval_required_on:
    - destructive_out_of_scope_action
danger_flags:
  - destructive_out_of_scope_action
artifact_checks:
  - flight_report_present
  - prompts_captured
  - responses_captured
  - screenshots_captured
postmortem_questions:
  - Did the agent infer the correct Temp path?
  - Did it handle the Save As dialog correctly?
  - Did it confirm content after reopening, not just after typing?
env_vars_required:
  - LIVE_GEMINI_SMOKE=1
  - RUN_DESKTOP_INTEGRATION=1
  - GEMINI_API_KEY
platform: Windows
---

# TC-DESKTOP-01 - Write a Note and Save It

## Context

Windows desktop automation through native UIA and dialog handling.

## Why It's Hard

- The Save As dialog is a separate UI tree from the main Notepad editor.
- The agent must infer `C:\Temp\` from “Temp folder”.
- The task requires two Notepad lifecycles plus verification.

## Expected Execution Trace

1. Launch Notepad.
2. Type the requested text.
3. Save to `C:\Temp\meeting_notes.txt`.
4. Close Notepad.
5. Reopen the saved file.
6. Read the content and confirm the marker is present.

## Failure Modes to Watch

| Symptom | Root cause |
|---|---|
| Save dialog never closes | Confirm action not sent or dialog not handled |
| File not found on reopen | Wrong directory or malformed path |
| Verification fails | Agent read before the file was fully written |
| Reopened Notepad is blank | Relaunch path was malformed |
