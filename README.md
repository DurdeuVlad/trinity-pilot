# Trinity Pilot

LLM-orchestrated desktop automation agent. Accepts a natural-language task, decomposes it into typed objectives, executes them via browser/terminal/desktop workers, reviews each result, and retries on failure — all orchestrated by Temporal for durability.

## Architecture

```
PySide6 UI  →  WorkflowBridge  →  Temporal TaskWorkflow
                                       │
                              ObjectivePlanner (Gemini)
                                       │
                              ObjectiveSpec DAG (typed)
                                       │
                    ┌──────────────────┼──────────────────┐
               BrowserWorker    TerminalWorker    DesktopWorker
               (Playwright)     (asyncio exec)   (pywinauto UIA)
                                       │
                              ObjectiveReviewer (Gemini)
                                       │
                              SQLite evidence + reflection store
```

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- [Temporal CLI](https://docs.temporal.io/cli) (for workflow execution)
- Gemini API key (get one at [aistudio.google.com](https://aistudio.google.com))
- Playwright browsers (installed via CLI, see below)

## Setup

```bash
# Install dependencies (including dev extras for testing)
uv sync --extra dev

# Install Playwright browsers
uv run playwright install chromium

# Copy env template and fill in your API key
cp .env.example .env
# Edit .env — set GEMINI_API_KEY at minimum

# Start Temporal dev server
temporal server start-dev
```

### .env.example

```dotenv
GEMINI_API_KEY=your-key-here
GEMINI_PLANNER_MODEL=gemini-2.0-flash
GEMINI_WORKER_MODEL=gemini-2.0-flash
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
DB_PATH=trinity_pilot.db
```

## Run

```bash
# Launch the desktop UI
uv run python -m trinity_pilot

# Start the Temporal worker (separate terminal)
uv run python -m trinity_pilot --worker
```

## Tests

```bash
# Unit + integration (no external services required)
uv run pytest tests/unit tests/integration -v

# With coverage
uv run pytest tests/unit tests/integration --cov=trinity_pilot --cov-report=term-missing

# Real tests (require GEMINI_API_KEY in env or .env)
uv run pytest tests/real -v -m real
```

Current test count: 127 unit/integration + 10 real tests.

## Project layout

```
trinity_pilot/
  core/types.py          ObjectiveSpec, enums, ReviewResult, AttemptLog
  llm/                   LLMProvider ABC + GeminiProvider (gemini-2.0-flash)
  planner/               ObjectivePlanner — JSON plan → ObjectiveSpec list
  reviewer/              ObjectiveReviewer — evidence → ReviewResult
  workers/
    browser_worker.py    Playwright automation, timeout guard, evidence validation
    terminal_worker.py   asyncio subprocess, timeout guard, evidence validation
    desktop_worker.py    pywinauto UIA, timeout guard, evidence validation
    worker_router.py     Domain → worker dispatch
    evidence_schema.py   Per-domain required-key validation
  memory/
    store.py             TaskStore — task + attempt SQLite records
    evidence_store.py    EvidenceStore — JSON evidence files, injectable base_dir
    reflection.py        ReflectionStore — reflections SQLite table
  workflow/
    task_workflow.py     Temporal TaskWorkflow — plan, execute, retry, review
    activities.py        Temporal activities wrapping workers + planner
  mcp/                   FastMCP boundary servers (browser, terminal, desktop)
  ui/                    PySide6 MainWindow + WorkflowBridge (lazy import)
  config.py              Settings dataclass + from_env()
  worker_runner.py       Temporal worker entry point (lazy temporalio import)
  __main__.py            CLI entry: --worker flag, --version, --help
```

## Key design decisions

- **Temporal for durability**: workflow state survives crashes; workers are stateless activities
- **Lazy imports**: PySide6 and temporalio are imported only at runtime to keep tests fast
- **Evidence schema validation**: every worker validates its output dict before returning
- **Reflections**: failed attempts produce structured reflections used in retry prompts
- **Injectable stores**: `EvidenceStore(base_dir=...)` and `ReflectionStore(db_path=...)` for clean test isolation

## License

MIT
