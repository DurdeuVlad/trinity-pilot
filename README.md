# Trinity Pilot

LLM-orchestrated desktop automation agent. Accepts a natural-language task, decomposes it into typed objectives, executes them via browser/terminal/desktop workers, reviews each result, and retries on failure through a local asyncio orchestration engine.

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

Set at least `GEMINI_API_KEY` in `.env`.

### `.env.example`

```dotenv
GEMINI_API_KEY=your-key-here
GEMINI_PLANNER_MODEL=gemini-2.0-flash
GEMINI_WORKER_MODEL=gemini-2.0-flash
DB_PATH=trinity_pilot.db
```

## Run

```bash
uv run python -m trinity_pilot
```

## Tests

```bash
uv run pytest tests/unit tests/integration -v
uv run pytest tests/unit tests/integration --cov=trinity_pilot --cov-report=term-missing
uv run pytest tests/real -v -m real
```

Real tests require `GEMINI_API_KEY`.

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
  memory/                SQLite task, attempt, objective, evidence, reflection stores
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

## License

MIT
