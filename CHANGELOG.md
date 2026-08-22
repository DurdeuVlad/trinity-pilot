# Changelog

## 2026-08-22: OSS README refresh

- **Open-source landing page.** Expanded the README with project status, capabilities, screenshots, release/source installation, provider configuration, workflow overview, verification table, safety guidance, known limitations, contribution instructions, and research context.
- **Documentation split.** Kept implementation detail in `docs/TECHNICAL_OVERVIEW.md` while making the README useful to both new users and contributors.
- **Documentation accuracy.** Fixed the README platform badge anchor, reconciled provider and database-path wording in `docs/PRIVACY_AND_SAFETY.md`, and ignored known local E2E artifacts at the repository root.

## 2026-08-22: README and technical overview

- **README.** Shortened the landing page, restored the four existing screenshots, and replaced stale test claims with the current 512-test collection and accepted 28/29 live GUI result.
- **Technical guide.** Moved architecture, execution, provider, safety, evaluation, and repository-layout detail to `docs/TECHNICAL_OVERVIEW.md`.

## 2026-08-22: E2E safety and provider hardening

- **Provider reliability.** OpenAI Responses tool continuations preserve the dispatched function-call item and reasoning context without replaying unrelated calls.
- **Desktop isolation.** GUI tests bind to the intended Trinity Pilot window, protect the local `.env` byte-for-byte, preserve target focus across dialogs, and normalize planner-emitted UIA locators and hotkeys.
- **Terminal evidence.** Command output is normalized and redacted, Python child processes use the worker runtime, and file/directory artifacts are recorded with independent readback evidence.
- **Reviewer evidence.** File readback and artifact paths remain available to downstream verification without allowing sanitized output to masquerade as raw stdout.
- **Verification.** Unit/integration/UI tests: 512 passed; Ruff, mypy, locked-dependency validation, and package build pass. The GUI happy suites report 28/29 (96.6%), above the accepted 85% gate; T9 remains a documented non-blocking E2E failure.
- **Release workflow.** Build attestation is conditional on repository visibility so private repositories can still publish their verified package and Windows ZIP assets.

## 2026-08-21: OpenAI provider switch

- **Provider selection.** Added a shared OpenAI Responses API provider and factory with `LLM_PROVIDER=openai|gemini`, preserving Gemini compatibility.
- **Default model.** The shipped `.env.example` selects OpenAI `gpt-5.6-luna`; the provider switch covers planning, workers, review, analysis, clarification, and streaming.
- **Tool and vision parity.** OpenAI function-call history preserves `call_id`, existing tool schemas are converted to Responses tools, and screenshots are sent as input images.
- **Reasoning continuity.** Responses reasoning and function-call output items are replayed in tool-call continuations so reasoning-capable models retain their required context.
- **Local setup.** The ignored local `.env` is prepared with the OpenAI provider and an empty `OPENAI_API_KEY` placeholder until the user supplies a real API key.
- **Verification.** 401 unit tests, focused OpenAI/config/factory/streaming/reasoning tests, Ruff, mypy, locked dependency validation, PyInstaller, ZIP integrity, and packaged `--version` smoke checks pass.

## 2026-08-21: Publish-readiness completion

- **Release archive.** The PyInstaller build now verifies `trinity-pilot.exe` and creates `dist/trinity-pilot-win64.zip` with the executable at the archive root; CI and release workflows upload the explicit archive asset.
- **Portable first-run setup.** Frozen builds persist the Gemini key under `%USERPROFILE%\\.trinity-pilot\\.env`, with an override for controlled environments; source checkouts continue using the working-directory `.env`.
- **Runtime version consistency.** CLI and MCP server manifests/resources use the installed package version instead of independent hardcoded copies.
- **Desktop safety fix.** Calculator typing protection now considers only the active or declared target window, preventing unrelated open windows from blocking input.
- **Verification.** 479 unit/integration/UI tests, Ruff, mypy, locked dependency validation, Python package build, and Windows PyInstaller + ZIP smoke checks pass.

## 2026-08-09: Open-source publish readiness

- **Production hardening.** Orphan objective recovery (mark stale objectives failed on next run), per-objective token budget tracking with charge-on-completion, ReviewError propagation, MCP client pool lifecycle hardening, worker close guards, structured error telemetry (emit_error), Gemini SDK type fixes, config validation + preflight checks.
- **PyInstaller packaging.** `pyinstaller.spec` and `scripts/build_exe.py` for standalone Windows `.exe` distribution with hidden imports for pywinauto, Playwright, and PySide6.
- **API key dialog.** First-run Qt GUI modal (`ApiKeyDialog`) prompts user for `GEMINI_API_KEY` when missing, persists to `.env`. Wired into `__main__.py` startup.
- **UI components.** `action_overlay.py` (in-flight action visualization) and `activity_panel.py` (live orchestrator event feed).
- **README rewrite.** Architecture diagrams (FSM, layer stack, worker routing, LLM provider, objective sequence), 11 screenshot gallery, quick start for pip and standalone .exe, developer guide, evaluation methodology.
- **CI/release workflow fixes.** Restored `tests/ui` to pytest command and `--locked` flag to `uv sync` in both `ci.yml` and `release.yml`.
- **Smoke harness fix.** UTF-8 encoding for subprocess stdout, proper file-wait return value.
- **New test coverage.** `test_api_key_dialog.py` (14 assertions), `test_db_objective_states.py` and `test_memory.py` regression tests for orphan state marking.

## Fixes — 2026-06-29

- **`whoami.exe` hangs on Windows asyncio subprocess-spawn** (same class as `git.exe`, `hostname.exe`, `python.exe`). Added `$env:USERNAME` to the list of native-equivalent examples in the terminal worker system prompt.
- **Planner routed tasks to wrong domain; goal text lost user content.** Compute/write tasks went to `desktop` instead of `terminal`, timing out after 180s trying to drive PowerShell GUI. Goal text was summarized rather than preserving what the user specified. Fixed planner to default to `terminal` for any CLI-achievable task and to carry user-specified content verbatim in goal text.
- **Planner checklist failures across three cases.** (1) Checklist used a JSON field name as the expected runtime value. (2) Checklist demanded `.exe` suffix in `Get-Process` output — `ProcessName` never includes it. (3) Checklist asserted a UI state that a later step was about to clear. Fixed checklist generation to assert observable facts rather than assumed format strings or transient visual state.
- **`created_files` false-veto when objective used `run_command` to create a file.** Only `write_file` populates `created_files`; `run_command`-created paths were invisible to the reviewer floor. Added `_record_created_files_from_command()` to `terminal_worker.py`: after a successful `run_command`, heuristically scans quoted absolute Windows paths in the command text and appends any that exist on disk.
- **`'NoneType' object has no attribute 'parts'` crash in desktop-domain LLM calls.** Gemini API can return a candidate with `content=None` on a blocked or empty finish. Added `None` guard in `gemini.py`.
- **Planner DAG missing upstream dependencies.** Objectives consuming computed data only listed the file-creation step as a dependency, not the computation step. Fixed: objectives now depend on every upstream step whose output they use.
- **Test assertion bug: `must_have` used `"avg"` but model output writes `"average"`.** Fixed assertion to use the full word.
- **`agentic_mixin.py` hard-failed on empty response at step 0.** `MALFORMED_FUNCTION_CALL` finish reason produces no text and no tool calls; step 0 raised `WorkerError` immediately while step>0 had a nudge-retry path. Removed the step-0 special case so all steps use the same bounded retry.
- **Dependent objectives couldn't see a prior terminal objective's stdout.** `_PORTABLE_EVIDENCE_KEYS` only forwarded `worker_result_summary`, not `stdout`/`exit_code`/`workspace`. Added those three keys to the forwarded set.
- **Added telemetry for non-STOP finish reasons** in `gemini.py`: `complete()` logs `finish_reason`/text length; `complete_with_tools()` logs `finish_reason`/`safety_ratings` on empty response.

## Known Issues — 2026-06-29

- **Planner JSON response intermittently truncated mid-object on large plans.** Seen as `"Expecting ',' delimiter"` at varying offsets; not correlated with token ceiling. `max_output_tokens=16384` set in `complete()` did not stop recurrence. Telemetry added — next occurrence will capture the real `finish_reason`.
- **`run_command` hangs ~30s when PowerShell spawns a standalone `.exe`**, but not with built-in cmdlets. Confirmed across `git.exe`, `python.exe <script>`, `hostname.exe`. Not reproducible in isolation. Mitigated by prompting the model to prefer native cmdlets/variables where an equivalent exists. Running `.py` scripts remains unresolved since there is no native substitute.
- **Session continuity (SC-01): system does not ask for clarification on very vague prompts.** The intent classifier occasionally skips the clarification step on ambiguous input and proceeds with assumptions. Treated as model behaviour, not a code bug.

## Pass 22 — E2E test harness (2026-05-17)

- Added `tests/e2e/` harness: scenario runner, assertions, conftest, and four suites covering terminal, browser, desktop, and behavioral quality gates.
- `BehavioralAssertions` class enforces no-hallucinated-paths, no-stale-retries, tool-sequence sanity, and cancellation-contract policies.
- Fixed `trinity_pilot/ui/bridge.py`: added `signals_queue` parameter to `_WorkerThread` / `WorkflowBridge.run()`; switched `task_finished` connections to `Qt.ConnectionType.DirectConnection` to prevent missed signals on thread exit.
- Registered `e2e`, `desktop`, and `slow` pytest markers.

## Pass 21 — Async orchestration, Temporal removal (2026-05-13)

- Replaced Temporal workflow runtime with `AsyncTaskOrchestrator` using local asyncio.
- Added orchestrator FSM, queue-backed signals, objective budgets, SQLite `objective_states`.
- Migrated Gemini provider to native `google.genai` calls with timeout and token-count reporting.
- Removed legacy workflow activities, TaskWorkflow, and obsolete tests.

## Pass 20 — Provider env, reviewer JSON, DAG ids (2026-05-08)

- Reviewer provider uses `GEMINI_WORKER_MODEL`; planner stays on `GEMINI_PLANNER_MODEL`.
- `ObjectiveReviewer`: fenced LLM JSON with trailing commas now parses correctly.
- DAG resolver: duplicate objective ids raise `ValueError` before ordering.

## Passes 1–19 — Initial build (2026-05-08)

- Foundation: `ObjectiveSpec` with 11 required fields, `DomainType`, `RiskClass`, `FailureReason`, `TaskRecord`, `AttemptLog`, `ReviewResult`.
- `LLMProvider` ABC + `GeminiProvider`.
- SQLite memory layer: WAL mode, `TaskStore`, `AttemptStore`, `ReflectionStore`, `EvidenceStore`.
- `ObjectivePlanner`: Gemini → JSON ObjectiveSpec list, Kahn DAG sort.
- `ObjectiveReviewer`: separate Gemini call, typed `FailureReason`, `recovery_hint`.
- Domain workers: `BrowserWorker` (Playwright), `TerminalWorker` (asyncio subprocess), `DesktopWorker` (pywinauto UIA → PyAutoGUI fallback).
- `WorkerRouter`, `AsyncTaskOrchestrator` FSM, `DAGScheduler`.
- PySide6 UI with `WorkflowBridge` QThread, `SignalBus`, chat widget, objective chips, status bar.
- Three kill paths: stop button, Ctrl+Shift+Q, PyAutoGUI fail-safe.
- MCP servers: browser, terminal, desktop, sensor, orchestrator, desktop-automation.
- 389 unit tests, 8 integration tests.
