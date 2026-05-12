---
tc_id:       "TC-004"
title:       "Open Notepad and type a string"
domain:      "desktop"
difficulty:  "easy"
requires:    ["desktop_interaction", "keyboard_input"]
risk_class:  "low"
---

## user_request
Open Windows Notepad, type the text "trinity-pilot-desktop-test", and take a screenshot
confirming the text is visible in the Notepad window.

## objectives

```yaml
objective_id:           "obj-001"
goal:                   "Launch Windows Notepad application"
dependencies:           []
domain:                 "desktop"
required_capabilities:  ["desktop_interaction"]
risk_class:             "low"
preconditions:          ["Windows OS is running"]
success_tests:
  - "screenshot shows a Notepad window is open"
  - "window_title contains 'Notepad'"
evidence_bundle:        ["screenshot", "window_title"]
max_attempts:           2
rollback_or_abort_rule: "abort"
```

```yaml
objective_id:           "obj-002"
goal:                   "Type 'trinity-pilot-desktop-test' into the Notepad text area"
dependencies:           ["obj-001"]
domain:                 "desktop"
required_capabilities:  ["desktop_interaction", "keyboard_input"]
risk_class:             "low"
preconditions:          ["Notepad window is open and focused"]
success_tests:
  - "screenshot shows text 'trinity-pilot-desktop-test' visible in Notepad"
evidence_bundle:        ["screenshot", "window_title"]
max_attempts:           3
rollback_or_abort_rule: "abort"
```

## expected_outcome
Notepad is open and displays "trinity-pilot-desktop-test" in its text area.

## assertions
- artifact_bundle.summary.overall_passed == true
- artifact_bundle.summary.total_objectives == 2
- attempts[-1].evidence["screenshot"] is not null

## post_mortem_hints
If obj-001 fails: Check if Notepad is available (it may be replaced by Notepad++ or another app).
If obj-002 fails: Check screenshot to see if Notepad gained focus correctly before typing.
