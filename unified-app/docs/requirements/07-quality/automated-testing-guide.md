# Automated Testing Guide - Orchestrator Desktop App

**Document ID:** TEST-AUTO-001  
**Version:** 2.0  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This guide documents the current automated test entry points for `unified-app`.
It is intentionally command-focused so an AI agent or developer can run the
right layer without relying on stale test counts or retired paths.

---

## 2. Preconditions

Run tests from the repository root so `testing.gemini_mock` is importable.

```bash
set GEMINI_MOCK=1
set GEMINI_API_KEY=mock
set PYTHONPATH=.
```

Use these variables for all non-live suites unless a test explicitly documents a
different setup.

---

## 3. Current Test Topology

| Layer | Paths | Purpose |
|------|-------|---------|
| Isolated orchestrator/component tests | `tests/orchestrator/`, `tests/test_frame_analyzer.py`, `tests/test_trinity_bridge.py`, `tests/test_startup_runtime.py` | Fast backend and startup contract coverage |
| UI component tests | `tests/ui/` | Qt widget behavior without a full packaged app run |
| Integration tests | `tests/integration/` | End-to-end orchestration flows inside the test process |
| Production-style app-session E2E | `tests/e2e/` | Higher-level workflows that exercise production seams |
| Performance checks | `tests/performance/` | Lightweight resource/regression coverage |

The suite is organized by responsibility rather than a retired unit-folder split.

---

## 4. Common Commands

### 4.1 Full Suite

```bash
pytest unified-app/tests/ -v --cov=unified-app/orchestrator --cov=unified-app/ui --cov-report=term-missing
```

Use this when you need the broadest signal for AC3.

### 4.2 Fast Backend and Startup Sweep

```bash
pytest unified-app/tests/orchestrator/ unified-app/tests/test_frame_analyzer.py unified-app/tests/test_trinity_bridge.py unified-app/tests/test_startup_runtime.py -v
```

Use this after changes to orchestrator logic, persistence, settings, or startup
mode handling.

### 4.3 UI Components

```bash
pytest unified-app/tests/ui/ -v
```

Use this after changes to panels, views, or widget wiring.

### 4.4 Integration Flows

```bash
pytest unified-app/tests/integration/ -v
```

Use this after changes that affect orchestration flow, persistence, or Gemini
mock/live startup behavior.

### 4.5 Production-style E2E

```bash
pytest unified-app/tests/e2e/ -v
```

Use this for acceptance-style checks around packaged/runtime-facing workflows.

### 4.6 Performance

```bash
pytest unified-app/tests/performance/ -v
```

Use this after changes that could affect runtime cost or memory behavior.

---

## 5. What Each Layer Covers

### Isolated orchestrator/component tests

- `tests/orchestrator/test_execution_runner.py` validates the extracted
  execution-runner seam.
- `tests/orchestrator/test_history_manager.py` validates SQLite-backed task
  persistence in `orchestrator/database/manager.py`.
- `tests/orchestrator/test_settings_manager.py` validates JSON-backed settings
  persistence in `orchestrator/settings_manager.py`.
- `tests/test_startup_runtime.py` validates `.env` loading, startup preflight,
  and mock/live readiness rules.

### UI tests

- `tests/ui/test_history_view.py` covers history rendering, search wiring, and
  details formatting.
- `tests/ui/test_settings_view.py` covers API key, timeout, retries, default
  domain, and frame-rate persistence wiring.
- Panel tests cover task submission, execution-plan display, status logging, and
  glass-box display behavior.

### Integration tests

- `tests/integration/test_full_loop_integration.py` covers the full in-process
  orchestration loop.
- `tests/integration/test_full_workflow.py` covers the assembled app workflow.
- `tests/integration/test_live_cli_smoke.py` and
  `tests/integration/test_poc_acceptance.py` cover smoke/acceptance seams.

### E2E tests

- `tests/e2e/test_cli_production_workflow.py`
- `tests/e2e/test_desktop_production_workflow.py`
- `tests/e2e/test_web_production_workflow.py`

These files cover production-style workflow expectations rather than isolated
widget behavior.

---

## 6. Coverage Guidance

Coverage is a moving measurement, not a hard-coded number in this document.
Use the current coverage command and compare the result against the requirements
target in `docs/requirements.md`:

- orchestrator + UI coverage target: `>= 85%`
- passing suite required for AC3

If coverage falls below target after a change, add or strengthen tests before
marking the work complete.

---

## 7. Failure Triage

| Symptom | First place to look |
|--------|----------------------|
| Import errors for Gemini mock | Repo-root working directory and `PYTHONPATH=.` |
| Startup-mode failures | `tests/test_startup_runtime.py` and `main.py` |
| History/settings persistence failures | `tests/orchestrator/test_history_manager.py`, `tests/orchestrator/test_settings_manager.py` |
| UI widget failures | `tests/ui/` plus the corresponding view/panel file |
| End-to-end workflow regressions | `tests/integration/` and `tests/e2e/` |

---

## 8. Acceptance Mapping

| Acceptance Area | Validation Surface |
|----------------|--------------------|
| AC3 Testing | Full suite, targeted layer runs, coverage command |
| AC4 Documentation | `docs/USER_MANUAL.md`, `docs/QUICK_START.md`, `docs/FAQ.md`, requirements package |
| AC5 Packaging | `build.ps1`, `unified-app.spec`, `orchestrator.spec`, `installer.nsi`, packaging docs |

---

## 9. Maintenance Rule

Do not hard-code historical pass counts in this guide. Update file paths,
commands, and coverage targets when the suite structure changes; let the
current pytest run produce the live numbers.
