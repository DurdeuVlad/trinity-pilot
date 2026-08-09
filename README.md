<div align="center">

# Trinity Pilot

### The open-source desktop agent that finishes the job.

Type a task in plain English. Trinity Pilot decomposes it into typed objectives, drives your browser, terminal, and desktop apps to execute them, reviews each result with a separate AI pass, and retries on failure. Everything runs locally on your machine.

[![CI](https://github.com/DurdeuVlad/trinity-pilot/actions/workflows/ci.yml/badge.svg)](https://github.com/DurdeuVlad/trinity-pilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](https://www.python.org/downloads/)
[![Tests: 475](https://img.shields.io/badge/Tests-381U%209I%2085UI-brightgreen.svg)](#running-tests)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D6.svg)](#safety-and-data-handling)

</div>

## Why this exists

Every "AI desktop agent" demo you've seen either:
- Records a macro and replays it. Breaks the moment a window moves.
- Calls a single LLM loop with a screenshot. Hallucinates clicks, invents file paths, declares success on failure.
- Wraps a cloud service. Your screen, files, and terminal output leave your machine.

Trinity Pilot takes a different approach: a real orchestration engine that treats desktop automation as a typed, reviewable, retryable workflow. It was built as a bachelor's thesis project and validated against 56 evaluation scenarios across five suites (168 runs, 83% global pass rate).

<div align="center">

![Main window](docs/screenshots/app-startup.png)

*Main window at startup. Chat input at the bottom, status indicator top right.*

</div>

## What it does

You type something like:

> *"Open a browser, go to example.com, find the page title, and write it to a file on my Desktop."*

Trinity Pilot:

1. **Plans.** An `ObjectivePlanner` (Gemini) decomposes the request into a typed `ObjectiveSpec` DAG with dependencies, domains, risk classes, and success checklists.
2. **Dispatches.** An async orchestrator routes each objective to the right worker: `BrowserWorker` (Playwright), `TerminalWorker` (asyncio subprocess), or `DesktopWorker` (pywinauto UIA).
3. **Executes.** Each worker runs a ReAct loop with real tools: navigate, click, type, read DOM, run commands, drive UI elements. No screenshot-guessing.
4. **Reviews.** A separate `ObjectiveReviewer` (Gemini) examines the evidence (screenshots, stdout, DOM snapshots, file existence) and returns a typed `ReviewResult`: pass, or fail with a specific `FailureReason`.
5. **Retries.** Failed objectives get a recovery hint and retry with the failure context injected into the next attempt. Up to 3 attempts per objective.
6. **Persists.** Every task, attempt, evidence bundle, and reflection is stored in SQLite (WAL mode) for post-hoc analysis.

### The objective lifecycle

Each objective moves through a typed state machine. Reviews gate transitions. Budgets bound execution.

<div align="center">

![Task planning](docs/screenshots/task-planning.png)

*Generated plan with objective, domain label, and Approve/Reject/Edit buttons.*

</div>

## Architecture

```text
PySide6 UI → WorkflowBridge → AsyncTaskOrchestrator
                                   │
                          ObjectivePlanner (Gemini)
                                   │
                          ObjectiveSpec DAG (typed)
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                     ▼
       BrowserWorker       TerminalWorker        DesktopWorker
       (Playwright)        (asyncio exec)        (pywinauto UIA)
              │                    │                     │
              └────────────────────┼────────────────────┘
                                   ▼
                       ObjectiveReviewer (Gemini)
                                   │
                       SQLite WAL state + evidence stores
```

<div align="center">

| Layer | Technology |
|-------|-----------|
| Desktop shell | PySide6 (Qt for Python) |
| Control plane | Local asyncio orchestrator + typed FSM |
| Inner planner | ObjectiveSpec DAG (typed, not prose) |
| Capability boundary | FastMCP servers (MCP at boundary, direct calls in hot path) |
| Browser domain | Playwright Python: headful Chromium, fresh context per objective |
| Terminal domain | asyncio subprocess: structured commands, not raw shell |
| Desktop-app domain | pywinauto UIA backend → PyAutoGUI fallback |
| Memory/evidence | SQLite: WAL mode, JSON columns, FTS5 |
| LLM provider | Gemini 2.5 Flash (free tier), swappable via `LLMProvider` ABC |

</div>

## What's inside

### Typed objectives, not prose

Every objective is a frozen dataclass with 13 required fields. The planner must produce all of them or execution is refused.

```python
@dataclass(frozen=True, slots=True)
class ObjectiveSpec:
    objective_id: str
    goal: str
    dependencies: list[str]
    domain: DomainType              # BROWSER | TERMINAL | DESKTOP | MIXED
    required_capabilities: list[str]
    risk_class: RiskClass           # LOW | MEDIUM | HIGH
    preconditions: list[str]
    success_tests: list[str]
    evidence_bundle: list[str]
    max_attempts: int
    rollback_or_abort_rule: str
    metadata: dict[str, Any]
    verification_checklist: tuple[ChecklistItem, ...]
```

### Three real workers, not a screenshot loop

| Worker | Backend | What it does |
|--------|---------|-------------|
| `BrowserWorker` | Playwright | Navigate, click, fill, read DOM, read text, screenshot, inspect network |
| `TerminalWorker` | asyncio subprocess | Run commands, write files, read files, with created-file verification |
| `DesktopWorker` | pywinauto UIA | Launch apps, find windows, click elements, type text, read controls |

Each worker runs a ReAct loop: the LLM proposes a tool call, the worker executes it, the result feeds back. No guessing from pixels.

### Separate reviewer with typed failure reasons

The reviewer is a different agent with read-only tools. It doesn't trust the worker's self-report. It checks the evidence independently and returns one of:

- `missing_artifact`: expected file/output doesn't exist
- `failed_assertion`: checklist item didn't pass
- `ui_state_mismatch`: UI isn't in the expected state
- `wrong_output`: output exists but content is wrong
- `environment_divergence`: environment changed unexpectedly

### DAG with cross-domain parallelism

Objectives are sorted via Kahn's algorithm. Independent objectives in different domains run in parallel. Dependent objectives wait and receive forwarded evidence from their upstream nodes.

### MCP at the boundary

Domain capabilities are exposed as FastMCP servers (browser, terminal, sensor). The orchestrator dispatches through MCP for isolation, but workers call tools directly in the hot path for speed. Sensors (screenshot, OCR, window-list, process-list) are read-only and shared across all agents.

### Three kill paths

1. **In-app stop button**: clean cancellation through the signal bus
2. **Global hotkey** (Ctrl+Shift+Q): works even if the UI is frozen
3. **PyAutoGUI fail-safe**: enabled at app startup; slam mouse to screen corner to abort. Note: the desktop worker temporarily disables fail-safe during coordinate-based actions to prevent false triggers, then re-enables it.

## Evaluation results

Validated against 56 scenarios across five test suites on a Windows 11 VM. Each scenario was run 3 times (N=3) to separate systematic failures from LLM non-determinism. 168 total runs, 139 passed (83% global success rate).

| Suite | Scenarios | Runs | Passed | Pass Rate | What it tests |
|-------|-----------|------|--------|-----------|--------------|
| Happy Path | 20 | 60 | 51 | 85% | Normal task completion across all three domains |
| Fail Recovery | 10 | 30 | 30 | 100% | Agent handles missing files, bad URLs, app crashes, focus loss |
| Resourcefulness | 10 | 30 | 20 | 67% | Agent discovers environment info (disk usage, PIDs, install paths) |
| Session Continuity | 6 | 18 | 15 | 83% | Agent maintains context across multi-round conversations |
| Happy Hard | 10 | 30 | 23 | 77% | 5-10 objective chains with artifact verification at each step |

Notable results from Fail Recovery (100% pass):
- App crash mid-task (FR-05): 3/3. Agent detects the app is gone and doesn't hang.
- Network unreachable (FR-08): 3/3. Graceful failure, no infinite retry.
- Primary path blocked (FR-06): 3/3. Agent falls back to alternate paths.

Known systematic failures:
- T13 (write and run a Python script): 0/3. Agent writes the script but doesn't complete execution reporting.
- RS-04 (count .py files and total lines): 0/3. Agent produces the first value but fails before extracting the second (multi-command composition limit).
- SC-01 (vague prompt clarification): 0/3. Agent proceeds to planning instead of asking for clarification on maximally vague input.

Test suite: 381 unit tests, 9 integration tests, 85 UI tests (475 total), all passing. Ruff clean. Mypy clean across 72 source files.

<div align="center">

| | |
|---|---|
| ![Task executing](docs/screenshots/task-executing.png) | ![Task complete](docs/screenshots/task-complete.png) |
| *Execution in progress. Active objective shown in bottom panel.* | *Final result. Completed objective with green background.* |

</div>

## Quick start

### Option A: Download standalone executable (no Python setup required)

1. Download the latest `trinity-pilot-win64.zip` from [Releases](https://github.com/DurdeuVlad/trinity-pilot/releases).
2. Extract the archive and launch `trinity-pilot.exe`.
3. Enter your free Gemini API key in the startup configuration dialog (or set `GEMINI_API_KEY` in environment).

### Option B: Developer setup with `uv`

```bash
# 1. Clone repository
git clone https://github.com/DurdeuVlad/trinity-pilot.git
cd trinity-pilot

# 2. Sync dependencies
uv sync --extra dev
uv run playwright install chromium

# 3. Launch Trinity Pilot
uv run python -m trinity_pilot
```

If `GEMINI_API_KEY` is not present, Trinity Pilot will open a native setup wizard to save your key to `.env`.

### Get a free Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com)
2. Create a free API key
3. Paste it into the startup dialog or set `GEMINI_API_KEY` in your environment

The free tier is sufficient for personal use. No billing required.

## Example tasks

Trinity Pilot handles cross-domain tasks that span browser, terminal, and desktop:

```
# Browser + Terminal
"Open a browser, go to httpbin.org/uuid, extract the UUID, and save it to a file on my Desktop."

# Terminal only
"Write a Python script that prints the current system info and run it."

# Desktop only
"Open Calculator and compute 17 * 23."

# Cross-domain
"Open Notepad, type today's date, then read it back with a terminal command to verify it saved."
```

## Project layout

```text
trinity_pilot/
  core/types.py          ObjectiveSpec, enums, ReviewResult, AttemptLog
  llm/                   LLMProvider ABC + async GeminiProvider
  planner/               ObjectivePlanner: JSON plan → ObjectiveSpec list + DAG
  reviewer/              ObjectiveReviewer: evidence → typed ReviewResult
  orchestrator/
    engine.py            Local async task orchestration
    fsm.py               Objective state machine
    budget.py            Objective execution budget (steps + tokens + wall clock)
    signals.py           Typed orchestration signals
    analyser.py          Post-task reflection and success analysis
  workers/
    agentic_mixin.py     Shared ReAct loop for all domain workers
    browser_worker.py    Playwright-backed browser automation
    terminal_worker.py   asyncio subprocess terminal automation
    desktop_worker.py    pywinauto UIA desktop automation
  memory/                SQLite WAL: TaskStore, AttemptStore, ReflectionStore, EvidenceStore
  mcp/                   FastMCP boundary servers (browser, terminal, sensor)
  ui/                    PySide6 MainWindow, ApiKeyDialog, WorkflowBridge, ActivityPanel
  telemetry/             Error tracing and finish-reason logging
  audit/                 Preflight checks and recovery drills
  config.py              Settings dataclass + from_env()
  __main__.py            CLI entry with crash hooks (faulthandler + excepthook)
```

## Building standalone executable

To build a standalone Windows `.exe` release manually:

```bash
uv run python scripts/build_exe.py
```

The resulting standalone executable package is built under `dist/trinity-pilot/`.

## Running tests

```bash
# Run unit, integration, and UI tests (475 tests, ~20s)
uv run pytest tests/unit tests/integration tests/ui -v

# Run test coverage
uv run pytest tests/unit tests/integration --cov=trinity_pilot --cov-report=term-missing

# Lint and type check
uv run ruff check .
uv run mypy trinity_pilot
```

GUI, desktop, and real-model suites require a controlled Windows environment with `GEMINI_API_KEY`. They open real applications and drive the live desktop.

## Safety and data handling

Trinity Pilot is not sandboxed. Terminal workers execute local PowerShell commands with user permissions; browser and desktop workers act directly on the desktop. Review tasks before execution and use a VM or low-privilege account for untrusted work.

When Gemini is configured, task prompts and execution evidence (screenshots, terminal output, UI element text) are sent to Google's Gemini API. No data is stored remotely. All state is local SQLite.

See [SECURITY.md](SECURITY.md) and [docs/PRIVACY_AND_SAFETY.md](docs/PRIVACY_AND_SAFETY.md) for the full safety policy.

## Acknowledgements

Trinity Pilot was built as a bachelor's thesis project at the [Technical University of Cluj-Napoca](https://www.utcluj.ro/), Faculty of Automation and Computers, informed by research on prior desktop automation agents:

- **UFO/UFO2/UFO3** (Microsoft): UI automation via UIA tree
- **PC Agent**: desktop task decomposition
- **MobileAgent-v2**: multi-agent mobile automation
- **Agent-S**: self-contained computer use
- **Magentic-UI**: multi-agent browser/desktop orchestration

## License

[MIT](LICENSE). Do whatever you want, just don't blame me if your desktop agent deletes your files.
