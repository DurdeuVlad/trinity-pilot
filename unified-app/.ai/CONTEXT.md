# unified-app Context

## Module Purpose

`unified-app` is the desktop orchestration UI layer on top of Trinity Core.

## Current Status (2026-03-14)

- Sprint 0 complete (framework and vertical slice)
- Sprint 1 complete (core UI + orchestration)
- Sprint 2 complete (glass-box live view + frame metadata)
- Sprint 3 complete (history/settings/error handling)
- Sprint 4 complete (tests, docs, packaging artifacts)
- **Requirements rewrite build complete** - legacy worker execution flow extracted into `orchestrator/execution_runner.py`; focused orchestrator and worker-backed integration suites green (`29 passed, 6 skipped`)
- **PoC Stabilization epic complete** — full orchestrator loop stabilized; 45 integration tests green; 3 live acceptance tests added (skip gracefully offline)

## Key Paths

- Entry point: `main.py`
- Bridge: `orchestrator/trinity_bridge.py`
- Event bus: `orchestrator/event_bus.py`
- Planner: `orchestrator/macro_planner.py`
- Orchestrator workflow: `orchestrator/orchestrator_core.py`
- Execution runner: `orchestrator/execution_runner.py`
- Screenshot watcher: `orchestrator/screenshot_watcher.py`
- UI panels: `ui/panels/`
- Tests: `tests/`
- Module docs: `docs/`

## Development Commands

```bash
# Run from repo root (required — testing/gemini_mock must be importable)
PYTHONPATH=. GEMINI_MOCK=1 GEMINI_API_KEY=mock pytest unified-app/tests/ -v
python unified-app/main.py
```

## Next Priorities

1. Browser adapter integration — `browser-gui-automation` module deferred from PoC Stabilization epic
2. Desktop adapter integration — `desktop-ai-agent` module deferred
3. Real `GEMINI_API_KEY` production configuration and CI secrets setup
4. Run live acceptance tests end-to-end: `POC_LIVE_TEST=1 PYTHONPATH=. GEMINI_MOCK=1 pytest unified-app/tests/integration/test_poc_acceptance.py -v`
