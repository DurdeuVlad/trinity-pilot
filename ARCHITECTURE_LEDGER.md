# Trinity Pilot Architecture Ledger

Status: evidence ledger for the 2026-05-06 cleanup.

Labels:
- `active`: current product path.
- `support`: useful primitive, diagnostic, fixture, or provider surface, but not architecture authority.
- `legacy`: compatibility or historical surface retained with caution.
- `dead`: generated, stale, broken, or deleted.

## Top-Level Folder Ledger

| Path | Class | Evidence | Rule |
|---|---|---|---|
| `unified-app/` | active | `main.py` launches PyQt app; `app.py` wires prompt -> plan -> Run -> execution. | Trust for desktop UX and Core handoff. |
| `trinity_core/` | active | README and tests define objective orchestration, sub-objective execution, visible tools. | Trust for execution and verification. |
| `api-accessibility-poc/` | support | Provider README classifies desktop primitives/support; tests exist under `tests/`. | Keep as desktop provider/support surface. |
| `browser-gui-automation/` | support | Provider README classifies browser primitives/support; tests exist under `tests/`. | Keep as browser provider/support surface. |
| `cli-automation-poc/` | support | Provider README classifies CLI primitives/support; tests exist under `tests/`. | Keep as CLI provider/support surface. |
| `.cache/` | dead | Generated/cache folder; ignored by `.gitignore`. | Do not trust or commit. |
| `.logs/` | dead | Generated log folder; ignored by `.gitignore`. | Do not trust or commit. |
| `.pytest_cache/` | dead | Test runner cache; ignored by `.gitignore`. | Do not trust or commit. |
| `.trinity/` | dead | Local runtime/session state. | Do not trust as source. |
| `_runtime/` | dead | Runtime output folder; ignored by `.gitignore`. | Do not trust or commit. |

## Root File Ledger

| Path | Class | Evidence | Rule |
|---|---|---|---|
| `README.md` | active | Top-level repo map. | Must link to this truth system. |
| `AGENTS.md` | support | Agent instructions and repo hygiene. | Keep unless it contradicts active truth. |
| `INTEGRATION_TESTING.md` | support | Rewritten as current test taxonomy. | Trust for test commands, not architecture design. |
| `CHANGELOG.md` | support | Project history. | Append only during ship. |
| `pyproject.toml` | active | Dependency and pytest metadata. | Modify only for real collection rules. |
| `uv.lock` | active | Dependency lock. | Do not edit in cleanup. |
| `check_last_error.py` | support | Root diagnostic script; no deletion evidence gathered. | Preserve until a focused support-script audit. |
| `run_task.py` | support | Root runner script; no deletion evidence gathered. | Preserve until a focused support-script audit. |
| `submit_and_check.py` | support | Root diagnostic script; no deletion evidence gathered. | Preserve until a focused support-script audit. |
| `verify_installation.py` | support | Listed support entrypoint. | Preserve. |
| root `*.png` and `cli_automation.log` | dead | Generated browser/runtime artifacts; ignored by `.gitignore`; no source role. | Deleted. |

## Unified-App Test Ledger

| Path | Class | Evidence | Rule |
|---|---|---|---|
| `unified-app/tests/smoke/` | active | Contains GUI-driven user-flow smoke coverage. | Trust as desktop user-flow smoke, within deterministic boundaries. |
| `unified-app/tests/integration/` | support | Runner/domain/live diagnostics and integration contracts. | Useful, but not equivalent to GUI smoke unless it drives `MainWindow`. |
| `unified-app/tests/unit/` | active | Deterministic routing and failure classification tests. | Keep as lower-level desktop contracts. |
| `unified-app/tests/fixtures/` | support | Test data. | Keep while referenced by active tests. |
| `unified-app/tests/_archived_legacy/` | dead | Tests imported removed modules such as `mcp_server`, `ui.panels`, `ui.overlay`, and stale orchestration surfaces. | Deleted after salvage scan. |
| `unified-app/tests/run_live_domain_scenarios.py` | support | Runs through `TrinityBridge`, not the GUI. | Keep as live bridge/domain diagnostics. |

## Core Test Ledger

| Path | Class | Evidence | Rule |
|---|---|---|---|
| `trinity_core/tests/` | active | Tests Core runtime contracts, objective orchestration, tool contracts, telemetry, verification. | Trust as Core health. |

## Provider Test Ledger

| Path | Class | Evidence | Rule |
|---|---|---|---|
| `api-accessibility-poc/tests/` | support | Desktop provider tests. Prior audit flagged path-isolation risk. | Run when desktop provider is touched; fix isolation in a separate pass. |
| `browser-gui-automation/tests/` | support | Browser provider tests. | Run when browser provider is touched. |
| `cli-automation-poc/tests/` | support | CLI provider tests. | Run when CLI provider is touched. |

## Deletion Evidence

| Deleted surface | Evidence signal 1 | Evidence signal 2 | Result |
|---|---|---|---|
| `unified-app/tests/_archived_legacy/*` | Archived files import removed modules or stale paths (`mcp_server`, `ui.panels`, `ui.overlay`, old prompt registry). | Active tests already cover current GUI flow, deterministic routing, bridge, and runner contracts. | Deleted. |
| root screenshots and `cli_automation.log` | Match generated artifact patterns in `.gitignore`. | They are runtime/browser captures, not source or documented diagrams. | Deleted. |
| `unified-app/framework_summary.txt` and `unified-app/latest_python_version.txt` | Pre-existing untracked generated outputs. | Not referenced by source/docs/tests and not part of source manifest. | Deleted. |
| `unified-app/docs/COMPLEXITY_INVESTIGATION_PROMPT.md` | Prompt/history document outside the central prompt policy. | References stale surfaces such as `mcp_server/` and removed UI overlay paths. | Deleted. |

## Preserved Legacy/Support Candidates

| Surface | Why preserved |
|---|---|
| root diagnostic scripts | Could still be useful local support tools. They need a focused script audit before deletion. |
| `cli-automation-poc/archive/` | Support archive under provider silo; not touched by this cleanup. |
| `cli-automation-poc/TestAudit`, `TestDemo`, `VisualDemo` | Demo/test artifacts may support provider development; not enough evidence for deletion in this pass. |
| `api-accessibility-poc/results/` | May contain generated result artifacts, but provider folder was not touched in this pass. |
