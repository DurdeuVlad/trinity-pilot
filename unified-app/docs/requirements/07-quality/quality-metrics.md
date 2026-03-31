# Quality Metrics - Orchestrator Desktop App

**Document ID:** QUALITY-001  
**Version:** 2.0  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines the quality targets for `unified-app` and how those
targets are measured. It avoids freezing historical values that can drift away
from the current repository state.

---

## 2. Core Metrics

### 2.1 Coverage

- **Metric:** Automated coverage across the orchestrator and UI surfaces
- **Target:** `>= 85%`
- **Measurement command:**

```bash
pytest unified-app/tests/ -v --cov=unified-app/orchestrator --cov=unified-app/ui --cov-report=term-missing
```

- **Pass rule:** Do not close work if the measured result falls below target.

### 2.2 Test Pass Rate

- **Metric:** Relevant pytest commands exit successfully
- **Target:** `100%` for the chosen validation scope
- **Measurement:** pytest exit code plus reviewed failure output

### 2.3 Documentation Accuracy

- **Metric:** Requirements, user docs, and traceability references match current
  code and file layout
- **Target:** No stale file paths, retired commands, or contradictory claims
- **Measurement:** Manual review plus `tests/test_requirements_docs.py`

### 2.4 Packaging Readiness

- **Metric:** Packaging artifacts required by AC5 remain present and documented
- **Target artifacts:**
  - `build.ps1`
  - `unified-app.spec`
  - `orchestrator.spec`
  - `installer.nsi`
- **Measurement:** File existence review and packaging workflow validation when
  packaging scope changes

### 2.5 Maintainability

- **Metric:** Public seams introduced in rewrites are covered by focused tests
- **Target:** Every new high-risk seam has at least one direct regression test
- **Measurement:** PR/session review of changed code and tests

---

## 3. Performance and Reliability Targets

| Area | Target | Evidence |
|------|--------|----------|
| Startup preflight | Live-mode startup readiness completes within the requirement boundary | `tests/test_startup_runtime.py` plus targeted startup checks |
| History loading | Responsive behavior for the single-user desktop scope | `HistoryView` UI tests and manual smoke verification |
| Resource cleanup | No leaked watcher/worker state across normal teardown paths | cleanup regressions such as `tests/test_orchestrator_resource_cleanup.py` |
| Persistence | Failed task runs still record durable history and settings remain reloadable | history/settings tests under `tests/orchestrator/` |

---

## 4. Reporting Rules

When writing build reports, sprint close docs, or changelogs:

1. Report the commands that were actually run.
2. Report the measured results from that run.
3. Do not restate old percentages or historical test counts as if they were
   current guarantees.

---

## 5. Quality Gates

Every substantial change should finish with:

```bash
python ai-quality-checker/check_code.py
python ai-quality-checker/check_docs.py
python .ai/scripts/validate.py
```

If code changed, pair those checks with the smallest meaningful pytest scope and
the full-suite/coverage run when the risk warrants it.
