---
id: TC-BROWSER-02
title: Multi-Site Research and Structured Comparison
domain: browser
difficulty: Very Hard
goal: Compare GitHub and PyPI data across three frameworks and return the framework with the most recent PyPI release date.
user_prompt: >
  Find the three most-starred Python web frameworks on GitHub (excluding Django and Flask), then look each one up on PyPI and tell me which of the three has the most recent release date. Give me the winner's name, its GitHub star count, and its PyPI release date.
expected_outcome:
  - TaskStatus.COMPLETED
  - result_data.status == success
  - result_data.name is non-empty and not django or flask
  - result_data.star_count is non-empty
  - result_data.release_date is non-empty
observation_policy:
  bounded_drift: true
  drift_time_budget_seconds: 120
  repeated_action_threshold: 3
  repeated_failure_threshold: 2
stop_policy:
  approval_required_on:
    - captcha
    - mfa
    - destructive_out_of_scope_action
danger_flags:
  - credential_entry
artifact_checks:
  - flight_report_present
  - prompts_captured
  - responses_captured
  - screenshots_captured
postmortem_questions:
  - Did the agent correctly exclude Django and Flask?
  - Did it compare absolute release dates rather than relative strings only?
  - Did it keep star counts and package identities aligned?
env_vars_required:
  - LIVE_GEMINI_SMOKE=1
  - RUN_BROWSER_INTEGRATION=1
  - GEMINI_API_KEY
platform: Windows
---

# TC-BROWSER-02 - Multi-Site Research and Structured Comparison

## Context

Sites: `https://github.com`, `https://pypi.org` (public, no login required).

## Why It's Hard

- Requires combining GitHub repository ranking with PyPI release data.
- Exclusion logic is active filtering, not passive reading.
- Package names and repository names may diverge.
- The agent must preserve state across 5+ pages before producing one comparison result.

## Expected Execution Trace

1. Open GitHub repository search for Python web frameworks.
2. Read top results and exclude Django and Flask.
3. Record names and star counts for the top three remaining frameworks.
4. Visit each framework’s PyPI page or release history.
5. Read and compare the latest release dates.
6. Return the winner with `name`, `star_count`, and `release_date`.

## Failure Modes to Watch

| Symptom | Root cause |
|---|---|
| Django or Flask returned as winner | Exclusion filter not applied |
| Only one PyPI page visited | Agent stopped after first framework lookup |
| release_date is only a relative string | Agent read a relative timestamp instead of an absolute date |
| name and star_count mismatch | Agent mixed data from two repositories |
| result_data has only name | Agent failed to populate all required keys |
