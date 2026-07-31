# Trinity Pilot

LLM-orchestrated desktop automation agent. Accepts a natural-language task, decomposes it into typed objectives, executes them via browser/terminal/desktop workers, reviews each result, and retries on failure through a local asyncio orchestration engine.

**Windows-only.** Desktop automation (`DesktopWorker`) is built on `pywinauto`/`pywin32` and raw Win32 API calls (`ctypes.windll`). Browser and terminal automation are cross-platform in principle, but the project as a whole targets Windows and is not tested elsewhere.

## Architecture

```text
PySide6 UI -> WorkflowBridge -> AsyncTaskOrchestrator
                                      |
                             ObjectivePlanner (Gemini)
                                      |
                             ObjectiveSpec DAG (typed)
                                      |
                 BrowserWorker  TerminalWorker  DesktopWorker
                 (Playwright)   (asyncio exec)  (pywinauto UIA)
                                      |
                             ObjectiveReviewer (Gemini)
                                      |
                             SQLite WAL state + evidence stores
```

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- Gemini API key from [Google AI Studio](https://aistudio.google.com)
- Playwright browsers

## Setup

```bash
uv sync --extra dev
uv run playwright install chromium
cp .env.example .env
```

On Windows, `uv sync` installs the desktop automation dependencies (`pywinauto` and
`pywin32`) automatically. They are not installed on non-Windows platforms.

`GEMINI_TIMEOUT_SECONDS` defaults to 120 seconds. Set it in `.env` when a different
timeout is needed.

Set at least `GEMINI_API_KEY` in `.env`.

### `.env.example`

```dotenv
GEMINI_API_KEY=your-key-here
GEMINI_PLANNER_MODEL=gemini-2.5-flash
GEMINI_WORKER_MODEL=gemini-2.5-flash
DB_PATH=trinity_pilot.db
```

## Run

```bash
uv run python -m trinity_pilot
```

## Tests

```bash
uv run pytest tests/unit tests/integration tests/ui -v
uv run pytest tests/unit tests/integration tests/ui --cov=trinity_pilot --cov-report=term-missing
uv run pytest tests/real -v -m real
```

Real tests require `GEMINI_API_KEY`.

## Internal tooling

`app_control_cli.py` at the repo root is a JSON-in/JSON-out control CLI (`start-ui`,
`submit-case`, `stream-events`, `get-artifact-bundle`, ...) used to drive the app
programmatically for the live-test/e2e harnesses in `tests/e2e/`. It talks to
`trinity_pilot.mcp.orchestrator_server` and `trinity_pilot.mcp.vm_bridge_server`
directly rather than through the `trinity-pilot` entrypoint — it's a test-automation
surface, not a user-facing CLI.

## Project Layout

```text
trinity_pilot/
  core/types.py          ObjectiveSpec, enums, ReviewResult, AttemptLog
  llm/                   LLMProvider ABC + async GeminiProvider
  planner/               ObjectivePlanner JSON plan to ObjectiveSpec list
  reviewer/              ObjectiveReviewer evidence to ReviewResult
  orchestrator/
    engine.py            Local async task orchestration
    fsm.py               Objective state machine
    budget.py            Objective execution budget
    signals.py           Typed orchestration signals
  workers/               Browser, terminal, and desktop execution backends
  memory/                SQLite task, attempt, objective, reflection stores
  mcp/                   FastMCP boundary servers
  ui/                    PySide6 MainWindow + WorkflowBridge
  config.py              Settings dataclass + from_env()
  __main__.py            CLI entry
```

## Key Design Decisions

- **Local async orchestration**: objective execution, review, retry, cancellation, and signals run in-process.
- **Async-only Gemini calls**: `google.genai` async client is used directly.
- **SQLite state**: WAL mode, task records, attempts, and objective state tracking.
- **Evidence schema validation**: workers validate output dicts before returning.
- **Reflections**: failed attempts produce structured reflections used in retry prompts.
- **NDJSON tracing**: unified NDJSON timeline for E2E/VM debugging; controlled via `TRINITY_TRACE=1` env var.

## Safety and data handling

Trinity Pilot is not sandboxed. Its terminal worker runs local PowerShell commands with the permissions of the user who starts the app; browser and desktop workers can also act on the local machine and network. Review tasks before running them and use a low-privilege account or VM for untrusted work.

When Gemini is configured, relevant task text and execution evidence (which can include browser content, screenshots, terminal output, UI text, and file paths) may be sent to Google's Gemini API. Task state and evidence are stored locally in SQLite (`DB_PATH`, default `trinity_pilot.db`); traces and crash reports can also contain sensitive data. See [Privacy and safety](docs/PRIVACY_AND_SAFETY.md) before use.

## License

[MIT](LICENSE)
