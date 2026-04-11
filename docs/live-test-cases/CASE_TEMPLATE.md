---
id: TC-EXAMPLE-01
title: Short Human Title
domain: browser
difficulty: Hard
goal: One-sentence operator-facing goal.
user_prompt: >
  Exact prompt to send to the live system.
expected_outcome:
  - Concrete user-visible success condition 1
  - Concrete user-visible success condition 2
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
  - external_purchase
  - credential_entry
  - account_mutation
artifact_checks:
  - flight_report_present
  - prompts_captured
  - responses_captured
postmortem_questions:
  - What went right?
  - What went wrong?
  - What should be fixed next?
env_vars_required:
  - GEMINI_API_KEY
platform: Windows
---

# TC-EXAMPLE-01 - Short Human Title

## Context

Describe the setup and any test harness preconditions.

## Why It's Hard

- List the key coordination or reasoning challenges.

## Expected Execution Trace

1. Outline the expected major steps for validation.

## Failure Modes to Watch

| Symptom | Root cause |
|---|---|
| Example symptom | Example root cause |
