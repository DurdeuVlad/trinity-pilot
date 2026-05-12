---
tc_id:       "TC-003"
title:       "Run echo command and capture output"
domain:      "terminal"
difficulty:  "easy"
requires:    ["terminal_execution"]
risk_class:  "low"
---

## user_request
Open a terminal and run: echo "trinity-pilot-test-marker-12345"
Confirm the output contains "trinity-pilot-test-marker-12345".

## objectives

```yaml
objective_id:           "obj-001"
goal:                   "Execute 'echo trinity-pilot-test-marker-12345' in terminal and capture output"
dependencies:           []
domain:                 "terminal"
required_capabilities:  ["terminal_execution"]
risk_class:             "low"
preconditions:          ["terminal is accessible"]
success_tests:
  - "stdout contains 'trinity-pilot-test-marker-12345'"
  - "exit_code == 0"
evidence_bundle:        ["stdout", "stderr", "exit_code", "screenshot"]
max_attempts:           2
rollback_or_abort_rule: "abort"
```

## expected_outcome
Terminal ran the echo command successfully. Evidence stdout contains the marker string.

## assertions
- artifact_bundle.summary.overall_passed == true
- attempts[0].evidence["stdout"] contains "trinity-pilot-test-marker-12345"
- attempts[0].evidence["exit_code"] == 0

## post_mortem_hints
If failed: Check if terminal worker can spawn a shell. Check stderr for permission errors.
