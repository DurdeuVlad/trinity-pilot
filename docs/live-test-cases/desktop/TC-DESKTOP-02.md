---
id: TC-DESKTOP-02
title: Multi-App Data Pipeline
domain: desktop
difficulty: Very Hard
goal: Use Notepad and Calculator together to compute a sum, save the total to a file, then verify it in Notepad.
user_prompt: >
  Open Notepad and write a list of five numbers, one per line: 47, 82, 13, 56, 29. Then use Calculator to add them all up. Save the total to a new file called result.txt in C:\Temp, and finally reopen result.txt in Notepad to confirm the number is correct.
expected_outcome:
  - TaskStatus.COMPLETED
  - result_data.status == success
  - result_data.sum == 227
  - result_data.verified == true
observation_policy:
  bounded_drift: true
  drift_time_budget_seconds: 120
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
  - Did the agent preserve the correct numbers and sum?
  - Did it adapt to the Calculator UI variant it found?
  - Did it verify the reopened file rather than stopping after save?
env_vars_required:
  - LIVE_GEMINI_SMOKE=1
  - RUN_DESKTOP_INTEGRATION=1
  - GEMINI_API_KEY
platform: Windows
---

# TC-DESKTOP-02 - Multi-App Data Pipeline

## Context

No special setup. `C:\Temp` may or may not exist.

## Why It's Hard

- Requires coordination between two desktop apps.
- Calculator UI labels vary between versions.
- The agent must carry staged state from Notepad into Calculator and then back into a saved file.
- Verification happens in a later app lifecycle after the calculation is already complete.

## Expected Execution Trace

1. Open Notepad and write the five numbers.
2. Open Calculator and enter the addition sequence.
3. Read the result and confirm it is 227.
4. Save `C:\Temp\result.txt`.
5. Reopen the file in Notepad and verify it contains 227.

## Failure Modes to Watch

| Symptom | Root cause |
|---|---|
| sum is not 227 | Operand or operator sequence was wrong |
| File not found on reopen | Save path was wrong |
| verified missing or false | Agent opened the file but did not read and confirm it |
| Calculator reused stale state | Agent failed to clear Calculator before starting |
| Two Notepad windows confused | Agent interacted with the wrong editor instance |
