# Changelog

## Model Limitations (Not Fixed, By Design) — 2026-06-29

- **SC-01 re-asked for clarification more than the test's existing 2-retry tolerance allows.** `test_SC01_vague_clarify_complete` already documents and absorbs this exact behavior ("the lite intent-classifier model occasionally re-asks for clarification even on an unambiguous concrete task") with a 2-round retry loop — this run exceeded even that. This is pure model non-determinism on the lite intent classifier, already acknowledged as expected in the test itself. Left alone per directive (model failures are not app bugs); not chasing further on a single occurrence.

## Fixes — 2026-06-29 (batch 8: HH07, HH09)

- **`whoami.exe` hangs the same way as `git.exe`/`hostname.exe`/`python.exe` (same Windows asyncio subprocess-spawn bug, see earlier "Known Issues").** HH07's `capture-current-user` timed out 30s on a plain `whoami` call. Has a native equivalent (`$env:USERNAME`). Added it to the explicit example list in `terminal_worker.py`'s `_TERMINAL_SYSTEM` prompt (previously only listed `hostname.exe`/`--version` examples). Confirmed fixed via re-run.
- **Planner under-specified an objective's goal, so the worker wrote a placeholder instead of real content.** HH09 — `create-input-json`'s goal abbreviated the user's literal request ("create the file with the specified content") instead of inlining the actual keys/values, so the worker wrote `{}` and the rest of the pipeline cascaded into failure (`write-report-file` correctly called `report_blocking` rather than fabricate stats from empty data). Added planner guidance: inline literal user-specified content verbatim into goal text, don't abbreviate.
- **Planner routed a parse/compute/write objective to the `desktop` domain instead of `terminal`.** Same HH09 plan, second bug — `parse-json-and-compute-stats` got domain `desktop`, so the worker tried to manually drive a PowerShell GUI window (launch_app → focus_window → type) instead of just calling `run_command`, and the whole objective timed out after 180s. Added planner guidance: prefer `terminal` over `desktop` whenever the goal is achievable via command-line/scripting; `desktop` is for GUI-only interactions with no CLI equivalent.
- **Planner wrote a checklist item with a field NAME as if it were the field's runtime VALUE.** Same HH09 plan, third bug (after the first two were fixed) — `format-report-content`'s checklist demanded stdout contain the literal string `"Version: version"`, where "version" was the JSON field name, not its actual value (which the planner couldn't know at plan time). Added planner guidance: never hardcode a literal value you don't actually know at plan time; phrase the check around the field being present, not an invented literal.
- All three planner-prompt fixes for HH09 needed to land together before it passed end-to-end (confirmed via stepwise re-runs after each fix, then a final clean pass). HH07 and HH09 both confirmed passing. Unit suite 389/389 throughout.

## Fixes — 2026-06-29 (batches 7+: HH04, HH06)

- **`created_files` recurring false-veto (3rd occurrence), fixed at the engine level this time instead of relying on planner prompt compliance.** HH04 hit the exact same bug as T6 (`created_files` checked but only `write_file` populates it) despite the planner guidance added for T6 — the model doesn't follow checklist-authoring guidance 100% of the time (same non-determinism already seen with RS-02's command choice). Added `_record_created_files_from_command()` to `trinity_pilot/workers/terminal_worker.py`: after any successful `run_command`, heuristically scans the command text for quoted absolute Windows paths and appends any that now exist on disk to `created_files`. This is deterministic and doesn't depend on the model following prompt instructions.
- **Genuine crash: `'NoneType' object has no attribute 'parts'` in desktop-domain LLM calls.** `trinity_pilot/llm/gemini.py` accessed `response.candidates[0].content.parts` without checking whether `content` itself is `None` (which the Gemini API can legitimately return for a candidate with no content, e.g. blocked or empty finish). Found via HH06 (3/3 attempts crashed identically). Added a `None` guard. Confirmed via unit suite (388/388 pass).
- **Planner dependency graph dropped computed values it needed.** HH04 — `write-metrics-to-file` only depended on `create-metrics-file` (a trivial empty-file step), not on `compute-sum-average`/`compute-max-min`, so the dependency evidence it received contained no actual numbers — the model correctly called `report_blocking` rather than hallucinate values ("I need the list of numbers... current context only indicates the file was created"). Added planner guidance: an objective needing a value computed earlier must depend on every objective that computed it, not just the most recent file-creation step.
- **Test bug, not app bug: `must_have=("HH04_OK", "sum", "avg", "min", "max")` demanded the literal abbreviation "avg", but the prompt's own step 2 says "Compute sum and average" — a reasonable model writes "Average: 10", which doesn't substring-match "avg".** ("min"/"max" happened to work by accident: "Minimum"/"Maximum" contain those as substrings; "average" does not contain "avg".) HH09 already uses the full word "average" for the same kind of check — HH04 was just inconsistent. Fixed `tests/e2e/test_gui_happy_path_hard.py`: changed the prompt to say "average" and `must_have` to match.
- **Added diagnostic logging for the two open issues below** (`trinity_pilot/llm/gemini.py`): `complete()` now logs `finish_reason`/text length whenever the finish reason isn't `STOP`; `complete_with_tools()` logs `finish_reason`/`safety_ratings` whenever a response comes back with no text and no tool calls. Doesn't fix either issue, but the next occurrence will have real diagnostic data instead of a guess.
- **HH04 fully resolved end-to-end** combining the three fixes above (engine `created_files` heuristic, planner dependency-completeness guidance, test assertion fix) — confirmed passing after re-test.

## Fixes — 2026-06-29 (HH06 root-caused)

- **Root cause found via diagnostic logging: `finish_reason: MALFORMED_FUNCTION_CALL`.** HH06's `write-tree-report` got an identical empty response 3/3 times — model emitted a structurally invalid function call, Gemini SDK returns no text and no tool_calls when that happens. `agentic_mixin.py::run_loop` had a special case that hard-failed (`raise WorkerError`) on an empty response at step 0 specifically, while step>0 already had a working nudge-and-retry path. Removed the step-0 special case so it uses the same bounded nudge-retry as every other step (still capped by `max_steps`). Rewrote `tests/unit/test_agentic_mixin.py`'s `test_loop_raises_on_fully_empty_llm_response` into a recovery test, added a new all-empty exhaustion test. Confirmed: unit suite 389/389 pass.

## Known Issues (Open) — 2026-06-29

- **Planner's JSON response intermittently truncated mid-object on a multi-objective plan (seen twice on HH04 before it started passing reliably).** "Planner returned invalid JSON: Expecting ',' delimiter" after the raw response cuts off mid-field, at two different truncation points (char 682 in a 53.75s/8942-char call, char 619 in a 16.97s/much-shorter call) — the second is far too short to be a token-ceiling issue. **Tried and ruled out as the fix:** setting `max_output_tokens=16384` explicitly in `complete()` (kept anyway, harmless, just didn't stop the recurrence). Diagnostic logging added — next occurrence will log the real `finish_reason` instead of leaving this a guess. Given HH06's empty-response bug turned out to be `MALFORMED_FUNCTION_CALL`, the planner's JSON-parsing path likely needs the same retry-on-bad-finish-reason treatment once a real occurrence is captured with the new logging.

## Fixes — 2026-06-29 (10-scenario expansion probe)

- **Dependent objectives couldn't see a prior terminal objective's actual output.** `_PORTABLE_EVIDENCE_KEYS` in `trinity_pilot/orchestrator/engine.py` only forwarded `worker_result_summary` (a vague self-summary) to dependency-evidence — never `stdout`, `exit_code`, or `workspace`. Found via HH05 (`count-python-processes` objective genuinely had no way to see what `list-python-processes` had listed, correctly called `report_blocking` instead of hallucinating). Added `"stdout"`, `"exit_code"`, `"workspace"` to the portable-keys tuple. Confirmed fixed: HH05 now passes (was failing 3/3 attempts).
- **Planner authored a checklist item demanding an unrealistic literal substring.** RS-07 ("is explorer.exe running") planned a checklist instruction "Check if 'explorer.exe' appears in the stdout" — but `Get-Process`'s `ProcessName` field never includes the `.exe` suffix, so the (correctly-functioning) checklist reviewer kept failing a genuinely-correct answer 3/3 attempts. Added planner guidance in `trinity_pilot/planner/prompts.py` (verification_checklist section): phrase checklist items around the underlying fact being verified, not assumptions about exact text formatting. Confirmed fixed: RS-07 now passes.
- Note: RS-04 also failed in this batch but is a genuine model reasoning failure (objective fabricated fake `.py` test files in its own sandbox tempdir instead of locating the real `trinity-pilot` project directory the prompt referred to) — left as-is per project policy of not chasing model competency issues.

## Fixes — 2026-06-29 (batch 2: T2/T5/T6/T8/T9)

- **Planner checklist assumed `created_files` would be populated for a `run_command`-created directory.** T6 ("create folder with files") planned a checklist item "The created_files list contains the path to 'tp_test_dir'" — but the worker used `New-Item` via `run_command`, which never populates `created_files` (only `write_file` does — same root cause class as the very first VM bug found this session). Added planner guidance to check `stdout`/`exit_code` instead for run_command-creatable goals. Confirmed fixed: T6 now passes.
- **Planner split a simple "extract and report" task into a contrived self-messaging objective.** T8 (extract `origin` from httpbun.org, "say it in chat") planned a *second* desktop-domain objective whose job was to literally type the value into Trinity Pilot's own chat input and submit it — failed 3/3 attempts because the agent (correctly) couldn't demonstrate an actual "send" action distinct from its own `finish()` call. The first objective's `finish()` summary already surfaces the answer in the UI, which is what the test's own assertion checks. Added planner guidance: "report/say/tell in chat" is satisfied by the objective's own finish() summary, do not create a separate chat-typing objective. Confirmed fixed: T8 now passes.
- Also fixed in passing: a planner checklist item asserting `dom_snapshot` "is valid JSON" (it's raw HTML by definition) — wasted one retry on T8's first objective before self-correcting. Added the same "state what must be true, not assumed format" guidance for this sensor.

## Fixes — 2026-06-29 (batch 6: RS-05)

- **Planner checklist demanded visual proof of a state the objective's own next step deliberately undoes.** RS-05 ("type text into Notepad, then close without saving") planned a checklist item "the text is present within the Notepad editor" — but by the time final evidence is captured, the close-without-saving step may already be mid-dialog or finished, so the text is structurally unobservable from end-state evidence. Failed 3/3 attempts despite the worker doing exactly what was asked each time. Added planner guidance: don't check for UI/visual states the objective's own later steps are expected to undo before finishing. Confirmed fixed: RS-05 now passes.

## Known Issues (Open) — 2026-06-29

- **`run_command` (terminal worker) reliably hangs ~30s when PowerShell launches a standalone `.exe`, but never when it uses a built-in cmdlet — reproducible only inside the full GUI app process, not in any isolated repro.** Confirmed across three independent cases this session: `git.exe` (RS-02), `python.exe <script>.py` (T13), `hostname.exe` (T14). Built-in cmdlets (`Test-Path`, `Get-ChildItem`, `Get-Process`, `Get-Command`, `Get-Content`) never hang in the same context. This is now a clean, reproducible boundary even though the underlying Windows-internals mechanism is unconfirmed.
  - Ruled out as the cause: command content, env/PATH stripping, COM-STA-thread + new-event-loop combo (all reproduced standalone with no hang).
  - Ruled out as a fix: raising `_CMD_TIMEOUT` from 30s to 90s — re-tested with the higher value and it still failed, this time hitting the *outer* per-objective `timeout_seconds` (default 60s) before the inner command timeout was even reached. Not a "just needs more time" situation as far as could be determined within this session's budget; reverted to 30s rather than leave an untested, unjustified constant change in.
  - **Fix applied (generalizable mitigation, not a root-cause fix):** added a rule to the terminal worker's system prompt (`trinity_pilot/workers/terminal_worker.py`) telling the model to prefer PowerShell-native cmdlets/variables over spawning a standalone `.exe` when an equivalent exists (e.g. `$env:COMPUTERNAME` instead of `hostname.exe`, `(Get-Command x).Version` instead of `x --version`). Confirmed fixed: T14 (`hostname.exe` case) now passes.
  - **Still unresolved:** T13 (running a `.py` script) has no native-cmdlet substitute — running a script fundamentally requires spawning `python.exe`. This case remains a real, unavoidable-with-current-mitigation app bug. Whoever picks this up next: the process-tree-kill fix (`_kill_process_tree`, already in place) at least guarantees clean failure instead of a permanent zombie hang; the actual 30s block itself is still unexplained.

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
