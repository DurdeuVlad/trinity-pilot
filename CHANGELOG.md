# Changelog

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
