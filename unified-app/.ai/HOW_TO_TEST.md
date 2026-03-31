# How to Test: unified-app

## Run Tests

```powershell
cd unified-app
pip install -r requirements.txt
$env:PYTHONPATH='..'
pytest tests/ -v
```

## Coverage

```powershell
$env:PYTHONPATH='..'
pytest tests/ -v --cov=. --cov-report=term-missing
```

Target: keep the mocked orchestrator suite green while covering startup and live-failure behavior.

## Test Categories

The test suite covers:
- UI panels (task input, execution plan, status log, glass-box)
- Orchestrator core (event bus, macro planner, core coordinator)
- Database layer (models, manager, history)
- Watcher and frame analyzer
- Settings manager, error handler
- Startup runtime config and readiness gating

## Sprint 1 Startup Tests

```powershell
cd ..
$env:PYTHONPATH='.'
pytest unified-app/tests/test_startup_runtime.py -q
pytest unified-app/tests/ui/test_task_input_panel.py -q
pytest unified-app/tests/orchestrator/test_orchestrator_core.py -q
pytest unified-app/tests/orchestrator/test_macro_planner.py -q
```

These cover:

- `.env` loading with shell-env precedence
- live-mode preflight against both Gemini caller paths
- startup UI blocking when live readiness fails
- current Gemini model selection for the unified-app planner

## Sprint 2 Live-Failure Tests

```powershell
cd ..
$env:PYTHONPATH='.'
pytest cli-automation-poc/tests/test_planner.py -q
pytest cli-automation-poc/tests/test_integration.py -q
pytest trinity_core/tests/test_adapters.py -q
pytest unified-app/tests/orchestrator/test_error_handler.py -q unified-app/tests/integration/test_full_loop_integration.py -q
```

These cover:

- explicit auth, quota, network, and malformed-response categories
- live planner fail-fast behavior vs mock fallback behavior
- backend and adapter propagation of user-safe failure messages
- worker/UI failure handling without raw traceback leakage

## Optional Live CLI Smoke Test

```powershell
cd ..
$env:PYTHONPATH='.'
Remove-Item Env:GEMINI_MOCK -ErrorAction SilentlyContinue
$env:LIVE_GEMINI_SMOKE='1'
pytest unified-app/tests/integration/test_live_cli_smoke.py -q
```

Notes:

- The test loads `unified-app/.env` if present.
- It uses the real Gemini API and is bounded to 60 seconds.
- It skips automatically if `LIVE_GEMINI_SMOKE=1` is not set or no live key is available.

## Manual Smoke Test

### Live mode

1. Set `GEMINI_API_KEY` in `unified-app/.env` or the shell.
2. From `unified-app/`, run `python main.py` with `$env:PYTHONPATH='..'`.
3. Verify the Task Input panel reports `live Gemini ready`.
4. Submit `list files in current directory` in the `cli` domain.
5. If the task is not terminal within 60 seconds, switch to mock mode.

### Mock mode fallback

1. Set `$env:GEMINI_MOCK='1'` and `$env:GEMINI_API_KEY='mock'`.
2. Run `python main.py` with `$env:PYTHONPATH='..'`.
3. Verify the Task Input panel reports mock fallback mode.
4. Submit the mocked demo task and verify progress/history update without a real API call.
5. Use [PoC_ACCEPTANCE.md](../../docs/plans/epics/2026-03-09_poc-stabilization-full-loop/PoC_ACCEPTANCE.md) as the fallback evidence pack.

## Bounded Demo Verification

Use this short sequence before the meeting instead of the larger suite:

```powershell
cd ..
$env:PYTHONPATH='.'
$env:GEMINI_MOCK='1'
$env:GEMINI_API_KEY='mock'
pytest unified-app/tests/orchestrator/test_macro_planner.py -q
pytest unified-app/tests/orchestrator/test_orchestrator_core.py -q
pytest unified-app/tests/integration/test_full_loop_integration.py -q -k "teacher_workflow_web_to_notepad"
python unified-app/test_live_execution.py
```

Expected outcome:

- the focused pytest commands pass quickly
- the teacher-workflow regression passes in mock mode
- the smoke helper prints ASCII-safe `[PASS]` / `[FAIL]` markers on Windows
