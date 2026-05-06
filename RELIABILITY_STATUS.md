# Reliability Status

Status: current as of 2026-05-06.

## Live Domain Scenarios

Command:

```powershell
cd unified-app
python tests/run_live_domain_scenarios.py
```

Full live run:

```powershell
python tests/run_live_domain_scenarios.py
```

Result from `2026-05-06 12:22`:

| Scenario | Status | Evidence |
|---|---|---|
| CLI easy health check | fail | `Sub-objective failed`; 0 completed steps. |
| CLI moderate organize downloads | pass | Files were organized and manifest validation passed. |
| Web easy docs navigation | pass | Python docs opened and page content was extracted. |
| Web moderate GitHub search | pass | GitHub search results were collected and summarized. |
| Desktop easy open Notepad | fail | `Sub-objective failed`; 0 completed steps. |
| Desktop moderate create note | fail | Scenario failed before visible tool evidence. |
| Cross easy research and save | pass | Python version was researched and saved. |
| Cross moderate research and draft | pass | Web framework summary file was written and verified. |
| Cross complex repo summary | fail | Scenario failed before visible tool evidence. |

Summary: 5 pass, 4 fail, 0 error, 0 timeout, 0 skip.

Interpretation: the unified live path is partially working. CLI and web can execute non-trivial flows, but simple one-step CLI/desktop and the complex cross-domain case still fail before recording visible tool evidence. This is product reliability debt, not stale test noise.

## GUI Smoke

`unified-app/tests/smoke/test_user_flow_smoke.py` now drives `MainWindow` through:

- prompt submission
- generated plan display
- Run acceptance
- result rendering
- artifact verification

It covers CLI, web, desktop, and mixed prompts with deterministic executor stubs. This is GUI smoke, not live domain execution.

## Core Verification

Fast Core command:

```powershell
cd trinity_core
python -m pytest -q tests -m "not live_desktop"
```

Live desktop Core command:

```powershell
cd trinity_core
python -m pytest -q tests -m live_desktop
```

`live_desktop` tests require real Windows UI automation and should not block fast Core verification.

## Provider Isolation

`api-accessibility-poc` had stale tests importing deleted generic backend/planner/orchestrator modules. Python resolved those imports from `C:\Users\User\Documents\Github\desktop-ai-poc-modules`, which made the suite test the wrong checkout.

Cleanup result:

- stale generic backend/planner/orchestrator tests deleted
- artifact manifest tests trimmed to existing modules
- `test_repo_import_isolation.py` added to fail if active provider modules resolve outside this repo

## Remaining Work

- Fix zero-tool-call live failures:
  - CLI easy health check
  - desktop easy open Notepad
  - desktop moderate create note
  - cross-domain complex repo summary
- Rerun the full nine live domain scenarios after each reliability fix.
- Decide whether `--include-extra` cross-domain three-domain chain should become canonical later.
