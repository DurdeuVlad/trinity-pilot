# Changelog

## Fixes — 2026-06-29

- **`whoami.exe` hangs on Windows asyncio subprocess-spawn** (same class as `git.exe`, `hostname.exe`, `python.exe`). Added `$env:USERNAME` to the list of native-equivalent examples in the terminal worker system prompt. Confirmed fixed.
- **Planner under-specified goal text, worker wrote placeholder content.** Added planner guidance: inline literal user-specified content verbatim into goal text, never abbreviate.
- **Planner routed a compute/write task to `desktop` domain instead of `terminal`.** Worker tried to drive PowerShell GUI instead of calling `run_command`, timed out after 180s. Added planner guidance: prefer `terminal` for anything achievable via CLI.
- **Planner checklist used a JSON field name as if it were the runtime value.** Added guidance: never hardcode a literal value you cannot know at plan time; phrase checks around the fact, not an assumed format.
- **`created_files` false-veto when objective used `run_command` to create a file.** Only `write_file` populates `created_files`; `run_command`-created paths were invisible to the reviewer floor. Added `_record_created_files_from_command()` to `terminal_worker.py`: after a successful `run_command`, heuristically scans quoted absolute Windows paths in the command text and appends any that exist on disk.
- **`'NoneType' object has no attribute 'parts'` crash in desktop-domain LLM calls.** Gemini API can return a candidate with `content=None` on a blocked or empty finish. Added `None` guard in `gemini.py`.
- **Planner dependency graph missing computed values.** Objectives that needed earlier computed data only depended on the file-creation step, not the computation step. Added planner guidance: depend on every objective whose output you need, not just the most recent file step.
- **Test assertion bug: `must_have` used `"avg"` but model output writes `"average"`.** Fixed assertion to use the full word.
- **`agentic_mixin.py` hard-failed on empty response at step 0.** `MALFORMED_FUNCTION_CALL` finish reason produces no text and no tool calls; step 0 raised `WorkerError` immediately while step>0 had a nudge-retry path. Removed the step-0 special case so all steps use the same bounded retry.
- **Dependent objectives couldn't see a prior terminal objective's stdout.** `_PORTABLE_EVIDENCE_KEYS` only forwarded `worker_result_summary`, not `stdout`/`exit_code`/`workspace`. Added those three keys to the forwarded set.
- **Planner checklist demanded `.exe` suffix in `Get-Process` output** — PowerShell's `ProcessName` field never includes it. Added planner guidance: phrase checklist items around the underlying fact, not assumed text formatting.
- **Planner checklist checked for a UI state that the objective's own later step undoes** (e.g. text visible in Notepad after close-without-saving). Added guidance: do not assert visual state that later steps are expected to clear.
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
