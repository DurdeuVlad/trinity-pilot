# TrinityPilot Test Architecture Audit - 2026-05-06

Status: audit complete, no deletions performed.

Scope:
- Product repo only: `C:\Users\User\Documents\Github\trinity-pilot-wrapper\trinity-pilot`
- Focus: whether tests prove the current active flow:
  `User -> Trinity Unified Desktop -> finalized objective + selected MCP target -> Trinity Core -> visible MCP tools`
- Excluded from cleanup action: untracked runtime outputs already present before this audit.

## Executive Verdict

The current test suite is bloated, split across old silos, and partly dead.

The most important failure is not volume. It is that the live smoke tests do not test the product like a user. They mostly bypass the GUI prompt, plan review, Run click, and status/result UI. The tests can pass while the real app interaction path is broken.

The second failure is staleness. `unified-app/tests` currently has import-time failures against modules that no longer exist (`mcp_server`, `ui.panels`, `orchestrator.macro_planner`, `orchestrator.objectives_decomposer`, `orchestrator.service_manager`, and related old surfaces).

The third failure is smoke-test identity drift. The repo and instructions disagree on the canonical live suite:
- Project instructions mention nine live domain scenarios.
- `unified-app/tests/run_live_domain_scenarios.py` says 10 scenarios.
- The latest request refers to eight smoke tests.

This must be resolved before anyone can honestly say "the smoke suite passed."

## Test Inventory

| Area | Python test files | Test LOC | Collected tests | Collection status | Score |
|---|---:|---:|---:|---|---|
| `trinity_core/tests` | 31 | 4,609 | 209 | collects | A- |
| `cli-automation-poc/tests` | 19 | 2,265 | 155 | collects | B |
| `browser-gui-automation/tests` | 11 | 1,657 | 90 | collects | B |
| `api-accessibility-poc/tests` | 29 | 3,672 | 146 before 1 collection error | broken | C |
| `unified-app/tests` | 49 | 5,861 | 365 before 15 collection errors | broken | D |

Scores are product-value scores, not effort scores:
- A: protects the current product architecture.
- B: useful provider/tool primitive coverage, but not end-to-end product proof.
- C: mixed value; contains useful regressions plus stale/compatibility debt.
- D: blocks collection or mostly tests dead architecture.
- F: delete/archive candidate.

## Current User Flow Evidence

The real GUI path is:
- `app.py:57` wires `ChatPanel.task_submitted`.
- `app.py:94-96` receives the user prompt and starts planning.
- `app.py:99` shows the generated plan.
- `app.py:107` sets the suggested domain.
- `app.py:117` starts execution only after Run is clicked.
- `ui/chat_panel.py:145` emits the raw user prompt.
- `ui/plan_panel.py:99-108` renders editable sub-objectives.
- `ui/plan_panel.py:135-141` emits the accepted sub-objectives when Run is clicked.

The current smoke tests do not cover that full chain.

## Findings

### P0 - The live domain runner bypasses the user interface

Evidence:
- `tests/run_live_domain_scenarios.py:4` says it executes directly through `TrinityBridge`.
- `tests/run_live_domain_scenarios.py:385-392` calls `bridge.execute_task(...)` with pre-approved `sub_objectives`.

Impact:
This does not prove prompt entry, plan generation, plan display, user acceptance, Run click, busy states, result rendering, or GUI event wiring.

Disposition:
Keep only as Core/bridge live diagnostics. It should not be called "the smoke suite" for the desktop app.

### P0 - `unified-app/tests` has dead architecture tests

Collection result:
- 365 tests discovered before collection abort.
- 15 import-time errors.

Dead imports include:
- `tests/test_app_command_pipe.py:7` imports `mcp_server.app_command_pipe`.
- `tests/test_domain_selector.py:11` imports `ui.panels.task_input_panel`.
- `tests/test_execution_overlay.py:10` imports `ui.overlay.execution_overlay`.
- `tests/test_execution_plan_panel.py:10` imports `ui.panels.execution_plan_panel`.
- `tests/test_macro_planner.py:15-16` imports removed planner/decomposer modules.
- `tests/test_objectives_decomposer.py:10` imports removed decomposer module.
- `tests/test_service_manager.py:1` imports removed service manager.
- `tests/test_status_transitions.py:11` imports removed status panel module.
- `tests/test_task_submission_pipe.py:5` imports `mcp_server.task_submission_pipe`.

Disposition:
Archive or delete these tests unless their target module is intentionally restored. Do not keep them in the active suite.

### P0 - Handoff scenario tests mostly test mocks, not behavior

Evidence:
- `tests/integration/base_orchestrator_scenarios.py:144-166` defines a fake `RecordingBridge`.
- `tests/integration/base_orchestrator_scenarios.py:226` patches `TrinityBridge` to the fake class.
- `tests/integration/test_domain_scenarios.py:11` advertises 9 scenarios x 15 assertions.

Impact:
These tests prove that hardcoded inputs are forwarded to a fake bridge. That is useful as a contract test, but it does not prove the app can plan, execute, or verify any user task.

Disposition:
Keep a smaller version as unit/contract coverage. Do not count it as smoke coverage.

### P1 - Some "live" pytest smoke tests start below the user boundary

Evidence:
- `tests/integration/test_live_cli_smoke.py:36-40` instantiates `UnifiedAppObjectiveRunner` directly.
- `tests/integration/test_live_browser_smoke.py:39-43` does the same.
- `tests/integration/test_live_desktop_smoke.py:42-46` does the same.
- `tests/integration/test_live_cross_domain_smoke.py:65-73` does the same for one cross-domain test.

Impact:
These are better than pure bridge tests because they hit the desktop-to-Core runner, but they still bypass GUI prompt submission, plan review, and Run acceptance.

Disposition:
Keep as runner-level live tests. Rename/document them as runner smoke, not user smoke.

### P1 - Cross-domain assumptions are inconsistent with the cleaned architecture

Evidence:
- `tests/integration/test_domain_scenarios.py:176` says `browser_mcp` coordinates a cross-domain plan.
- `tests/integration/test_domain_scenarios.py:232` and `:269` expect `browser_mcp` for mixed scenarios.
- `tests/run_live_domain_scenarios.py:168-229` uses `domain="mixed"` with `target_server=None` for cross-domain live scenarios.

Impact:
The current architecture says the unified app selects the MCP target and Core routes visible tools. Tests still encode older "browser coordinates mixed work" assumptions in places.

Disposition:
Update tests to assert the current contract: user prompt -> selected/approved target/sub-objectives -> Core runtime visible tools. Do not hardcode browser as the mixed coordinator unless that is still a deliberate product decision.

### P1 - Some scenario fixtures are fantasy environments

Evidence:
- `tests/integration/test_domain_scenarios.py:225` requires a monitoring dashboard at `http://localhost:3000`.
- `tests/integration/test_domain_scenarios.py:259-263` requires `app.exe` and a local service on `localhost:8080`.

Impact:
These are not reliable smoke tests for this product unless the suite provisions those services. They are scenario ideas, not runnable product proof.

Disposition:
Archive as scenario design notes or replace with self-contained fixtures.

### P1 - `api-accessibility-poc/tests` imports from an external stale path

Collection result:
- 146 tests discovered before abort.
- 1 collection error: `tests/test_artifact_manifest.py` imports `generic_backend` from `C:\Users\User\Documents\Github\desktop-ai-poc-modules\api-accessibility-poc\generic_backend.py`, not this repo.

Impact:
The suite can silently test the wrong checkout.

Disposition:
Fix path isolation before trusting results. Any test importing from `desktop-ai-poc-modules` is invalid for product health.

## Keep / Rewrite / Archive

### Keep Active

- `trinity_core/tests`: keep. This is the strongest current coverage for runtime contracts, visible tools, verification, strategy routing, context propagation, and retry behavior.
- `cli-automation-poc/tests`: keep as provider primitive coverage.
- `browser-gui-automation/tests`: keep as provider primitive coverage.
- Useful `api-accessibility-poc/tests`: keep after path isolation is fixed.
- `unified-app/tests/test_trinity_bridge.py`, `test_main_entrypoint_preflight.py`, `test_event_bus.py`, and provider-prompt tests: keep if they still collect.

### Rewrite

- `unified-app/tests/run_live_domain_scenarios.py`: rewrite or demote. It should either become bridge diagnostics or be replaced by a GUI-driven smoke runner.
- `unified-app/tests/integration/test_live_*_smoke.py`: rename as runner smoke, then add real GUI smoke tests above them.
- `unified-app/tests/integration/test_domain_scenarios.py`: shrink and align with the current mixed-domain architecture.

### Archive/Delete Candidates

Delete or archive from active pytest collection:
- `unified-app/tests/test_app_command_pipe.py`
- `unified-app/tests/test_domain_selector.py`
- `unified-app/tests/test_error_unavailable.py`
- `unified-app/tests/test_execution_overlay.py`
- `unified-app/tests/test_execution_plan_panel.py`
- `unified-app/tests/test_live_test_cases.py`
- `unified-app/tests/test_macro_planner.py`
- `unified-app/tests/test_objectives_decomposer.py`
- `unified-app/tests/test_orchestrator_mcp_live_tools.py`
- `unified-app/tests/test_prompt_registry.py`
- `unified-app/tests/test_run_monitor.py`
- `unified-app/tests/test_service_manager.py`
- `unified-app/tests/test_status_transitions.py`
- `unified-app/tests/test_task_submission_pipe.py`
- `unified-app/tests/test_terminal_session_mcp.py`

These are not automatically bad historical artifacts. They are bad active tests because they fail collection against the current codebase.

## Correct Smoke Strategy

The canonical smoke suite should be GUI-driven:

1. Start the real unified app.
2. Enter a user prompt in `ChatPanel`.
3. Wait for generated sub-objectives in `PlanPanel`.
4. Accept by clicking Run.
5. Wait for completion in the real app.
6. Validate externally observable outcome:
   - CLI: file exists / command output persisted / manifest contents.
   - Web: browser state or extracted artifact, not model text alone.
   - Desktop: real window/file/UI evidence.
   - Cross-domain: artifact proves information moved across domains.

Recommended canonical suite:
- CLI easy
- CLI moderate
- Web easy
- Web moderate
- Desktop easy
- Desktop moderate
- Cross easy
- Cross moderate
- Cross complex

That is nine. If the product owner wants eight, explicitly cut one scenario and document why.

## Immediate Next Changes

1. Move dead `unified-app/tests` files out of active collection or delete them.
2. Fix `api-accessibility-poc` import isolation so it cannot import from `desktop-ai-poc-modules`.
3. Rename direct bridge/runner smoke tests so they stop pretending to be user smoke.
4. Add one GUI-driven smoke harness using PyQt/pytest-qt or a process-level UI driver.
5. Promote that harness to the only authoritative smoke suite.

## Follow-up Implemented

- Collection-broken unified-app legacy tests were moved to `tests/_archived_legacy/`.
- `pytest.ini` now excludes that archive from active collection.
- A first GUI-driven smoke test was added under `tests/smoke/`.

The new smoke test drives `MainWindow` through the real prompt, generated
sub-objective display, Run click, result rendering, and external artifact
verification. It uses deterministic stubs at the LLM/executor boundary, so it
proves the unified-app user-flow wiring. Full live domain execution remains the
next expansion layer.

No code deletion was done in this audit because the deletion set is large and touches historical compatibility surfaces. The next pass should be a cleanup pass with intentional file removals and a focused replacement smoke harness.
