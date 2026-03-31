# Changelog

## 2026-03-14 - Requirements Package Drift Hardening

- Rewrote the requirements traceability and testing docs so they point at the current `tests/`, persistence, startup, and packaging surfaces instead of retired paths and frozen historical counts.
- Added `tests/test_requirements_docs.py` to catch stale requirements-package path references and retired pytest targets.
- Updated the requirements index count and traceability links to match the current documentation set.
- Restored `orchestrator/execution_runner.py::_execute_step()` and the desktop fallback validation step in `orchestrator/macro_planner.py` when sprint-close verification exposed those regressions.

## 2026-02-14 - Sprint 3 and Sprint 4 Completion

- Implemented persistent task history with SQLAlchemy.
- Implemented history browser and settings UI views.
- Integrated error handling and tabbed app layout.
- Added release artifacts (`orchestrator.spec`, `installer.nsi`, build/profile scripts).
- Added end-user docs (`USER_MANUAL.md`, `QUICK_START.md`, `FAQ.md`).
- Expanded tests to 26 passing cases with 86% coverage on orchestrator/UI modules.

## 2026-02-14 - Sprint 1 Complete and Sprint 2 Kickoff

- Implemented Sprint 1 core UI panels:
  - `task_input_panel.py`
  - `execution_plan_panel.py`
  - `status_log_panel.py`
- Implemented Sprint 1 orchestration backbone:
  - `event_bus.py`
  - `macro_planner.py`
  - `orchestrator_core.py`
  - `main.py` integration
- Added Sprint 1 and integration tests across UI, orchestrator, and workflow.
- Started Sprint 2 implementation:
  - `screenshot_watcher.py`
  - `frame_analyzer.py`
  - `glass_box_panel.py`
  - Main window live-view wiring
- Added sprint audit and completion reports.

## 2026-02-14 - Sprint 0 Foundation

- Added project skeleton for `unified-app`.
- Added initial `TrinityBridge` integration layer.
- Added deterministic unit tests for bridge lifecycle and execution contract.
- Added Sprint 0 completion report and module context seed.
