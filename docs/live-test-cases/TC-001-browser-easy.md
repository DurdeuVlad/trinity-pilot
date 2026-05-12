---
tc_id:       "TC-001"
title:       "Open Python docs homepage"
domain:      "browser"
difficulty:  "easy"
requires:    ["browser_navigation"]
risk_class:  "low"
---

## user_request
Navigate to https://docs.python.org and confirm the page title contains "Python".

## objectives

```yaml
objective_id:           "obj-001"
goal:                   "Navigate browser to https://docs.python.org and capture page title"
dependencies:           []
domain:                 "browser"
required_capabilities:  ["browser_navigation"]
risk_class:             "low"
preconditions:          ["internet connection available"]
success_tests:
  - "page_title contains 'Python'"
  - "page_url starts with 'https://docs.python.org'"
evidence_bundle:        ["screenshot", "page_title", "page_url", "dom_snapshot"]
max_attempts:           2
rollback_or_abort_rule: "abort"
```

## expected_outcome
Browser is on the Python docs homepage. Evidence contains a screenshot with the page
visible and page_title matches "Welcome to Python.org" or "Python Documentation".

## assertions
- artifact_bundle.summary.overall_passed == true
- attempts[0].evidence["page_title"] contains "Python"
- attempts[0].evidence["page_url"] starts with "https://docs.python.org"
- attempts[0].evidence["screenshot"] is not null

## post_mortem_hints
If failed: check browser worker can reach the internet. Check screenshot for error page.
