---
id: TC-CLI-01
title: Scan Log Files and Summarize Errors
domain: cli
difficulty: Hard
goal: Recursively scan seeded log files, count error lines, write a report, verify it, and clean up the test directory.
user_prompt: >
  I have some log files in C:\Temp\trinity_cli_test. Can you scan all of them recursively, count how many lines contain the word 'error', write a short summary report next to them, and then clean everything up afterwards?
expected_outcome:
  - TaskStatus.COMPLETED
  - result_data.status == success
observation_policy:
  bounded_drift: true
  drift_time_budget_seconds: 60
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
postmortem_questions:
  - Did the agent search recursively?
  - Did it write and verify a report file?
  - Did it remove the seeded directory tree only after verification?
env_vars_required:
  - GEMINI_API_KEY
platform: Windows
---

# TC-CLI-01 - Scan Log Files and Summarize Errors

## Context

The harness seeds:

```text
C:\Temp\trinity_cli_test\
  subdir_a\file1.txt
  subdir_a\file2.txt
  subdir_b\file3.txt
```

The agent must discover the structure itself.

## Why It's Hard

- Recursive search is required for a correct count.
- The report format is intentionally underspecified.
- Cleanup is part of the user’s intent and is easy to skip.

## Expected Execution Trace

1. Search `C:\Temp\trinity_cli_test\` recursively for lines containing `error`.
2. Count 4 matching lines across 3 files.
3. Write `report.txt` with the file count and error count.
4. Read the report back to confirm it.
5. Delete the seeded directory tree.

## Failure Modes to Watch

| Symptom | Root cause |
|---|---|
| Count = 2 or 3 | Agent searched only one subdirectory |
| No report file written | Agent stopped after printing to stdout |
| Directory still exists after task | Cleanup skipped |
| Count = 5 | The match logic was too broad |
