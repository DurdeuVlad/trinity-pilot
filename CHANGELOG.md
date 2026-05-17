# Changelog

## Pass 22 - Automated E2E test harness with behavioral quality assertions (2026-05-17)

- Added `tests/e2e/` two-tier harness: infrastructure helpers (_scenario, _assertions, _runner, conftest) plus four test suites covering terminal, browser, desktop, and behavioral quality gates.
- BehavioralAssertions class enforces no-hallucinated-paths, no-stale-retries, tool-sequence-sane, and cancellation-contract policies across all scenarios.
- DirectOrchestrator fixture drives AsyncTaskOrchestrator headlessly, bypassing Qt WorkflowBridge for deterministic CI runs.
- Production fix in `trinity_pilot/ui/bridge.py`: added `signals_queue` parameter to `_WorkerThread` / `WorkflowBridge.run()` and switched `task_finished` connections to `Qt.ConnectionType.DirectConnection` to prevent missed signals on thread exit.
- Registered `e2e`, `desktop`, and `slow` pytest markers in `pyproject.toml`.
- 20+ E2E test functions across 4 suites.

## Pass 21 - Async orchestration redesign, Temporal removal (2026-05-13)

- Replaced Temporal workflow runtime with `AsyncTaskOrchestrator` using local asyncio execution.
- Added orchestrator FSM, queue-backed signals, objective budgets, and SQLite `objective_states`.
- Migrated Gemini provider to native `google.genai` async calls with timeout and token-count reporting.
- Rewired UI bridge and MCP orchestrator server to local task execution, status, and cancellation.
- Removed legacy worker runner, workflow activities, TaskWorkflow, and obsolete tests.
- 282 tests passed, 16 skipped.

## Pass 20 - Production glue hardening: provider env, reviewer JSON, DAG ids (2026-05-08)

- workflow activities: reviewer provider now uses `GEMINI_WORKER_MODEL`; planner provider remains on `GEMINI_PLANNER_MODEL`
- ObjectiveReviewer: fenced LLM JSON with trailing commas now parses like planner output
- DAG resolver: duplicate objective ids now raise `ValueError` before ordering
- 234 tests total

## Pass 19 - Final hardening: desktop fallback, DAG scale, provider/config/workflow edges (2026-05-08)

- DesktopWorker: degraded-mode evidence when pywinauto and PyAutoGUI imports fail
- ObjectivePlanner: five-objective reverse dependency chain reorders by DAG
- ReflectionStore and EvidenceStore: three-attempt ordering and exact five-key evidence round trip
- GeminiProvider and Settings: empty-system kwargs omitted; Temporal namespace and worker model env overrides covered
- TaskWorkflow: internal `_results` mirror populated on objective pass
- TerminalWorker: Windows command builtins run through `cmd.exe /c` while preserving non-shell subprocess execution
- 230 tests total

## Pass 18 — Evidence schema gaps, ObjectiveSpec whitespace validation, TaskRecord objectives (2026-05-08)

- validate_evidence: MIXED domain no-schema no-raise test; error message lists missing keys test
- ObjectiveSpec.validate(): whitespace-only goal now raises ValueError (strip before check); negative max_attempts raises ValueError
- TaskRecord: objectives field can be set; defaults to empty list
- EvidenceStore: dom_snapshot and trace_path binary fields written to separate .bin files
- 220 tests total

## Pass 17 — Test coverage: reviewer recovery_hint, browser timeout, gemini no-tool-calls (2026-05-08)

- ObjectiveReviewer: recovery_hint field in ReviewResult (3 tests: populated on failure, empty on pass, defaults to empty when missing)
- BrowserWorker: timeout raises WorkerError test (mocked _execute_inner with sleep)
- GeminiProvider.complete_with_tools: no function_call parts returns empty tool_calls list + content matches response text
- 212 tests total

## Pass 16 — Test coverage: CHANGELOG, created_files, evidence round-trip, reflection cross-task, validate, system_instruction (2026-05-08)

- TerminalWorker: created_files captured in evidence after shell_raw command
- EvidenceStore: load_attempt_evidence round-trip test
- ReflectionStore: cross-task isolation test (same obj_id, different task_ids)
- TaskStore.list_tasks: user_request field preserved in returned TaskRecord
- ObjectiveSpec.validate(): empty goal raises ValueError
- GeminiProvider.complete(): system_instruction passed to GenerativeModel
- CHANGELOG updated with Passes 5-15 history

## Pass 15 — Behavioral contracts, threading fix (2026-05-08)

- save_reflection_activity: 2 unit tests (correct args, null failure_reason)
- TerminalWorker._extract_command: backtick-wins-over-run, empty backtick edge cases
- EvidenceStore.list_attempts: type check (returns AttemptLog instances)
- ObjectivePlanner.plan(): dependency reorder test (LLM returns [B,A] -> plan returns [A,B])
- GeminiProvider.complete(): empty messages raises ValueError
- WorkerError: issubclass, message preserved, raise/catch tests
- AttemptLog: default evidence={}, default failure_reason=None
- BUG FIX: AttemptStore.log_attempt threading.Lock prevents SQLite WAL concurrent write race
- 202 tests total

## Pass 14 — Desktop MCP tests, persist_attempt activity test, tool_calls, update_status (2026-05-08)

- test_mcp_desktop.py: desktop_screenshot + desktop_find_window mocked (4 tests)
- test_persist_activity.py: persist_attempt passed/failed status, AttemptLog fields (2 tests)
- GeminiProvider.complete_with_tools: tool_calls parsing + empty messages raises (2 tests)
- TaskStore.update_status: direct DB row assertion (2 tests)
- 190 tests total

## Pass 13 — Binary round-trip, cancel tests, worker_runner smoke, CLI tests, search tests (2026-05-08)

- EvidenceStore: binary field content round-trip (file bytes match original)
- TaskWorkflow: cancel flag tests (idempotent, sets _cancelled correctly)
- test_worker_runner.py: smoke import, callable checks, _TASK_QUEUE constant (4 tests)
- test_main.py: --help exit 0, --version exit 0 + version string, --worker in help (4 tests)
- TaskStore.search(): match found, no-match returns [] (2 tests)
- 180 tests total

## Pass 12 — list_tasks, metadata round-trip, MCP browser/review tests (2026-05-08)

- TaskStore.list_tasks(status=None): list all or filter by TaskStatus
- ObjectiveSpec to_dict/from_dict: metadata round-trip (3 tests)
- test_mcp_browser.py: browser_navigate mocked (2 tests)
- test_review_activity.py: review_objective passing/failing result (2 tests)
- Settings.validate: temporal_host empty raises ConfigError test
- AttemptStore.get_attempts: ordering test
- ReflectionStore.save_reflection: UUID validity test
- 167 tests total

## Pass 11 — Observability, ApplicationError, delete_task, model property, MCP terminal tests (2026-05-08)

- TaskWorkflow.completed_objectives() query: returns list of passed obj IDs, returns copy
- plan_objectives wraps PlanningError as ApplicationError("planning_failed", non_retryable=True)
- EvidenceStore.delete_task(task_id): removes DB rows + directory tree
- GeminiProvider.model property: exposes model name
- activities.py: fix stale gemini-1.5-pro defaults -> gemini-2.0-flash
- tests/unit/conftest.py created; temporalio stub pattern for unit tests
- 154 tests total

## Pass 10 — README, error context, cancellation record, reflection/attempt queries (2026-05-08)

- README.md: full project description, setup, run, test, layout docs
- PlanningError on JSON decode includes truncated user_request context (first 100 chars)
- TaskWorkflow: cancelled objective recorded as {"status": "cancelled"} in results
- ReflectionStore.get_all_reflections(task_id): all reflections for a task
- AttemptStore.get_attempts_by_task(task_id): all attempts for a task
- EvidenceStore.list_attempts(task_id): delegates to AttemptStore
- 136 tests total

## Pass 9 — Real Gemini tests, reviewer tests, pipeline smoke (2026-05-08)

- ObjectiveReviewer: full reviewer unit tests (6 tests)
- test_reviewer_real.py: passing + failing evidence against live Gemini
- test_pipeline_real.py: planner -> TerminalWorker -> reviewer round-trip
- Config: default models updated to gemini-2.0-flash
- tests/real/conftest.py: gemini_api_key fixture
- 127 CI tests + 10 real tests

## Pass 8 — CLI, lazy PySide6, worker timeout, evidence schema (2026-05-08)

- __main__.py: --worker flag, --version, --help, lazy PySide6 import
- worker_runner.py: all temporalio imports lazy
- ui/__init__.py: lazy __getattr__ to avoid PySide6 at collection time
- BrowserWorker: _execute_inner() method, asyncio.wait_for timeout guard
- evidence_schema.py: per-domain required-key validation
- EvidenceStore: injectable base_dir for test isolation
- 127 CI tests

## Pass 7 — Integration pipeline smoke, metadata field, evidence validation (2026-05-08)

- ObjectiveSpec: metadata: dict[str, Any] field added
- workers: timeout guard via asyncio.wait_for + metadata["timeout_seconds"]
- evidence_schema.py: validate_evidence(domain, evidence) at worker boundary
- test_pipeline_smoke.py: MockLLMProvider, passing + failure+reflection persistence
- EvidenceStore: injectable base_dir
- All workers: explicit __init__, timeout, schema validation

## Pass 5 — Hardening, ruff/mypy clean (2026-05-08)

- ruff + mypy clean pass across all modules
- test_kill_paths.py: lazy PySide6/pyautogui imports
- Various type annotation fixes

## Pass 4 — Evidence persistence, reflection memory, hardening

- EvidenceStore: atomic writes to `~/.trinity-pilot/evidence/{task_id}/{obj_id}/attempt_N/`
- ReflectionStore: SQLite `reflections` table; failure notes + recovery hints persisted per attempt
- ReviewResult: `recovery_hint` field added; reviewer prompt updated
- TaskWorkflow: wires `persist_attempt` + `save_reflection_activity`; injects prior reflections as `retry_context` on subsequent attempts
- BrowserWorker: structured JSON action dispatch (`{"actions": [...]}` in goal); keyword fallback retained
- TerminalWorker: `shlex.split` by default (no `shell=True`); `shell_raw` capability required for unrestricted shell
- Desktop MCP server: `trinity_pilot.mcp.desktop_server` added
- README.md + CHANGELOG.md added

## Pass 3 — Domain workers, worker router, execute_objective wired

- `DomainWorker` ABC + `WorkerError`
- `BrowserWorker`: Playwright async, one context per attempt, trace + failure evidence, cleanup in finally
- `TerminalWorker`: asyncio subprocess, isolated tempdir, stdout/stderr/exit_code evidence
- `DesktopWorker`: pywinauto UIA → PyAutoGUI fallback, `degraded_mode` flag
- `WorkerRouter`: domain → worker class mapping; MIXED domain raises `WorkerError`
- `execute_objective` activity: last stub replaced; end-to-end wired
- FastMCP browser + terminal server scaffolds
- `workflow/__init__` made lazy to avoid hard `temporalio` import in test environments

## Pass 2 — Planner, reviewer, Temporal activity wiring, UI bridge

- `ObjectivePlanner`: Gemini → JSON ObjectiveSpec list, validates all fields, markdown fence strip
- DAG: Kahn's topological sort, `CyclicDependencyError`
- `ObjectiveReviewer`: separate Gemini call, typed `FailureReason`, unknown reason defaults to `failed_assertion`
- Temporal activities wired: `plan_objectives` + `review_objective`; `execute_objective` stubbed
- `Config`: `Settings` dataclass from `.env`
- `WorkflowBridge`: QThread async runner connecting UI to Temporal
- `worker_runner.py`: Temporal worker entry point

## Pass 1 — Foundation scaffold

- `ObjectiveSpec` with 11 required fields + `validate()`
- `DomainType`, `RiskClass`, `FailureReason`, `TaskRecord`, `AttemptLog`, `ReviewResult` enums and types
- `LLMProvider` ABC + `GeminiProvider` (google-generativeai, strategy pattern)
- SQLite memory layer: WAL mode, FTS5 full-text search, `TaskStore`, `AttemptStore`
- Temporal `TaskWorkflow`: cancel signal, status + current_objective queries, activity stubs
- PySide6 UI shell with all 3 kill paths (stop button, Ctrl+Shift+Q hotkey, PyAutoGUI fail-safe)
