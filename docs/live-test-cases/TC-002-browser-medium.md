---
tc_id:       "TC-002"
title:       "Search GitHub and navigate to first result"
domain:      "browser"
difficulty:  "medium"
requires:    ["browser_navigation", "dom_interaction"]
risk_class:  "low"
---

## user_request
Go to https://github.com, search for "fastmcp", click the first repository result,
and confirm the repository page loaded.

## objectives

```yaml
objective_id:           "obj-001"
goal:                   "Navigate to https://github.com and confirm the page loaded"
dependencies:           []
domain:                 "browser"
required_capabilities:  ["browser_navigation"]
risk_class:             "low"
preconditions:          ["internet connection available"]
success_tests:
  - "page_url contains 'github.com'"
  - "dom_snapshot contains 'search' input element"
evidence_bundle:        ["screenshot", "page_title", "page_url", "dom_snapshot"]
max_attempts:           2
rollback_or_abort_rule: "abort"
```

```yaml
objective_id:           "obj-002"
goal:                   "Type 'fastmcp' into GitHub search box and submit"
dependencies:           ["obj-001"]
domain:                 "browser"
required_capabilities:  ["browser_navigation", "dom_interaction"]
risk_class:             "low"
preconditions:          ["browser is on github.com homepage"]
success_tests:
  - "page_url contains 'search' or 'q=fastmcp'"
  - "dom_snapshot contains at least one repository result"
evidence_bundle:        ["screenshot", "page_url", "dom_snapshot"]
max_attempts:           3
rollback_or_abort_rule: "abort"
```

```yaml
objective_id:           "obj-003"
goal:                   "Click the first repository result and confirm repository page loaded"
dependencies:           ["obj-002"]
domain:                 "browser"
required_capabilities:  ["browser_navigation", "dom_interaction"]
risk_class:             "low"
preconditions:          ["search results page is showing fastmcp results"]
success_tests:
  - "page_url contains 'github.com/' and contains at least one '/' after domain"
  - "dom_snapshot contains 'README' or 'Code' tab"
evidence_bundle:        ["screenshot", "page_title", "page_url", "dom_snapshot"]
max_attempts:           2
rollback_or_abort_rule: "abort"
```

## expected_outcome
Browser is on a GitHub repository page for a fastmcp-related project. Three objectives all pass.

## assertions
- artifact_bundle.summary.total_objectives == 3
- artifact_bundle.summary.overall_passed == true
- attempts[-1].evidence["page_url"] matches github.com/<user>/<repo> pattern
- all attempt statuses are "passed"

## post_mortem_hints
If obj-002 fails: GitHub may have changed search UI. Check dom_snapshot for search input selector.
If obj-003 fails: Search returned no results -- fastmcp may have been renamed.
