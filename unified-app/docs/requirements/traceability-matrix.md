# Requirements Traceability Matrix - Orchestrator Desktop App

**Document ID:** TRACE-001  
**Version:** 2.0  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This matrix links the current top-level requirements in
`docs/requirements.md` to the real implementation files, documentation, and
test surfaces that exist in the repository today.

The goal is practical traceability. Historical test counts and retired file
paths are intentionally excluded.

---

## 2. Functional Requirements to Implementation

| Requirement | Current implementation evidence |
|-------------|--------------------------------|
| FR1 Task Submission and Execution | `ui/panels/task_input_panel.py`, `orchestrator/orchestrator_core.py`, `orchestrator/execution_runner.py` |
| FR2 Execution Planning | `orchestrator/macro_planner.py`, `ui/panels/execution_plan_panel.py` |
| FR3 Real-Time Monitoring | `ui/panels/status_log_panel.py`, `ui/panels/glass_box_panel.py`, `orchestrator/screenshot_watcher.py`, `orchestrator/frame_analyzer.py` |
| FR4 Task History | `ui/views/history_view.py`, `orchestrator/database/manager.py`, `orchestrator/database/models.py` |
| FR5 Settings Management | `ui/views/settings_view.py`, `orchestrator/settings_manager.py`, `main.py::_apply_runtime_settings()` |
| FR6 Startup Modes | `main.py`, `orchestrator/macro_planner.py`, module-local `.env`, `testing/gemini_mock/` |

---

## 3. Functional Requirements to Tests

| Requirement | Test evidence |
|-------------|---------------|
| FR1.1-FR1.5 | `tests/ui/test_task_input_panel.py`, `tests/orchestrator/test_orchestrator_core.py`, `tests/orchestrator/test_worker_contract.py`, `tests/integration/test_full_loop_integration.py` |
| FR2.1-FR2.4 | `tests/orchestrator/test_macro_planner.py`, `tests/orchestrator/test_macro_planner_mock.py`, `tests/ui/test_execution_plan_panel.py`, `tests/integration/test_full_workflow.py` |
| FR3.1-FR3.4 | `tests/ui/test_status_log_panel.py`, `tests/ui/test_glass_box_panel.py`, `tests/test_frame_analyzer.py`, `tests/orchestrator/test_screenshot_watcher.py` |
| FR4.1-FR4.5 | `tests/orchestrator/test_history_manager.py`, `tests/ui/test_history_view.py`, `tests/integration/test_full_loop_integration.py` |
| FR5.1-FR5.6 | `tests/orchestrator/test_settings_manager.py`, `tests/ui/test_settings_view.py` |
| FR6.1-FR6.6 | `tests/test_startup_runtime.py`, `tests/integration/test_live_cli_smoke.py`, `tests/integration/test_poc_acceptance.py` |

---

## 4. Non-Functional and Acceptance Evidence

| Requirement area | Evidence |
|------------------|----------|
| NFR1 Performance | `tests/performance/test_memory_usage.py`, startup/runtime tests, targeted manual smoke checks |
| NFR2 Reliability | `tests/orchestrator/test_execution_runner.py`, `tests/test_orchestrator_resource_cleanup.py`, history/settings persistence tests |
| NFR3 Usability | `tests/ui/`, `docs/USER_MANUAL.md`, `docs/QUICK_START.md`, `docs/FAQ.md` |
| NFR4 Maintainability | separated `orchestrator/` and `ui/` layers, `orchestrator/execution_runner.py`, focused seam tests |
| NFR5 Testability | current pytest topology under `tests/`, Gemini mock support, coverage command in `07-quality/` docs |
| AC3 Testing | `tests/`, `07-quality/test-strategy.md`, `07-quality/automated-testing-guide.md` |
| AC4 Documentation | `docs/USER_MANUAL.md`, `docs/QUICK_START.md`, `docs/FAQ.md`, requirements package |
| AC5 Packaging | `build.ps1`, `scripts/build.ps1`, `unified-app.spec`, `orchestrator.spec`, `installer.nsi`, `BUILD.md` |

---

## 5. File-Level Requirement Map

### FR1: Task Submission and Execution

- `ui/panels/task_input_panel.py`
  - task text input
  - input validation
  - domain selection
  - submit/cancel wiring
- `orchestrator/orchestrator_core.py`
  - worker lifecycle
  - cancellation entry point
- `orchestrator/execution_runner.py`
  - execution timeout/retry contract

### FR2: Execution Planning

- `orchestrator/macro_planner.py`
  - live/mock planning behavior
- `ui/panels/execution_plan_panel.py`
  - plan rendering
  - step-status updates

### FR3: Real-Time Monitoring

- `ui/panels/status_log_panel.py`
- `ui/panels/glass_box_panel.py`
- `orchestrator/screenshot_watcher.py`
- `orchestrator/frame_analyzer.py`

### FR4: Task History

- `ui/views/history_view.py`
  - search box
  - table rendering
  - detail formatting
- `orchestrator/database/manager.py`
  - SQLite CRUD/search operations
- `orchestrator/database/models.py`
  - durable history schema

### FR5: Settings Management

- `ui/views/settings_view.py`
  - API key, timeout, retries, domain default, frame-rate controls
- `orchestrator/settings_manager.py`
  - JSON-backed settings persistence
- `main.py`
  - applies saved settings to runtime UI/orchestrator state

### FR6: Startup Modes

- `main.py`
  - `.env` loading
  - startup readiness evaluation
  - live preflight
  - blocked/degraded/ready messaging
- `testing/gemini_mock/`
  - offline/demo path

---

## 6. Current Test Topology Reference

| Path | Role |
|------|------|
| `tests/orchestrator/` | isolated orchestrator, persistence, and startup-adjacent contracts |
| `tests/ui/` | widget/component behavior |
| `tests/integration/` | assembled in-process workflows |
| `tests/e2e/` | production-style workflow checks |
| `tests/performance/` | lightweight performance regression coverage |
| `tests/test_startup_runtime.py` | startup-mode contract coverage |
| `tests/test_frame_analyzer.py` | frame metadata seam coverage |
| `tests/test_trinity_bridge.py` | Trinity bridge contract coverage |

---

## 7. Drift Prevention

The requirements package must stay synchronized with the real file layout.
`tests/test_requirements_docs.py` exists to catch stale path references and
retired pytest targets in this package.
