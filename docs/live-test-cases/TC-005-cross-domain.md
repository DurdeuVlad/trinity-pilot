---
tc_id:       "TC-005"
title:       "Browser fetch + terminal verify file write"
domain:      "mixed"
difficulty:  "medium"
requires:    ["browser_navigation", "terminal_execution"]
risk_class:  "low"
---

## user_request
Navigate browser to https://httpbin.org/uuid to get a random UUID string.
Then run a terminal command to write that UUID to a temp file at C:\Temp\trinity_test_uuid.txt
and read it back, confirming the file contains a UUID-format string.

## objectives

```yaml
objective_id:           "obj-001"
goal:                   "Navigate to https://httpbin.org/uuid and extract the UUID value from the page"
dependencies:           []
domain:                 "browser"
required_capabilities:  ["browser_navigation"]
risk_class:             "low"
preconditions:          ["internet connection available"]
success_tests:
  - "page body contains a string matching UUID format (8-4-4-4-12 hex)"
  - "page_url contains 'httpbin.org'"
evidence_bundle:        ["screenshot", "page_url", "dom_snapshot", "extracted_uuid"]
max_attempts:           2
rollback_or_abort_rule: "abort"
```

```yaml
objective_id:           "obj-002"
goal:                   "Write the UUID from obj-001 evidence to C:\\Temp\\trinity_test_uuid.txt using terminal"
dependencies:           ["obj-001"]
domain:                 "terminal"
required_capabilities:  ["terminal_execution"]
risk_class:             "low"
preconditions:
  - "obj-001 passed and evidence contains extracted_uuid"
  - "C:\\Temp directory exists or can be created"
success_tests:
  - "exit_code == 0"
  - "stdout or confirmation shows file was written"
evidence_bundle:        ["stdout", "stderr", "exit_code", "screenshot"]
max_attempts:           2
rollback_or_abort_rule: "abort"
```

```yaml
objective_id:           "obj-003"
goal:                   "Read C:\\Temp\\trinity_test_uuid.txt and confirm it contains a UUID-format string"
dependencies:           ["obj-002"]
domain:                 "terminal"
required_capabilities:  ["terminal_execution"]
risk_class:             "low"
preconditions:          ["C:\\Temp\\trinity_test_uuid.txt was written in obj-002"]
success_tests:
  - "stdout matches UUID format"
  - "exit_code == 0"
evidence_bundle:        ["stdout", "stderr", "exit_code"]
max_attempts:           2
rollback_or_abort_rule: "abort"
```

## expected_outcome
A UUID was fetched from the internet via browser, written to disk via terminal, and read back
correctly. All 3 objectives pass. Cross-domain orchestration is proven to work.

## assertions
- artifact_bundle.summary.total_objectives == 3
- artifact_bundle.summary.overall_passed == true
- attempts[0].evidence["page_url"] contains "httpbin.org"
- attempts[2].evidence["stdout"] matches UUID regex pattern

## post_mortem_hints
If obj-001 fails: httpbin.org may be down. Try https://httpbin.org/get as fallback.
If obj-002 fails: Check if C:\Temp exists. Run `mkdir C:\Temp` in a separate terminal first.
If obj-003 fails: Check that obj-002 wrote the file at the exact expected path.
