# Trinity Pilot

LLM-orchestrated desktop automation agent. Accepts a natural-language task, decomposes it into typed objectives, executes them via browser/terminal/desktop workers, reviews each result, and retries on failure — all orchestrated by Temporal for durability.

## Architecture

```
PySide6 UI  →  WorkflowBridge  →  Temporal TaskWorkflow
                                       │
                              ObjectivePlanner (Gemini Pro)
                                       │
                              ObjectiveSpec DAG (typed)
                                       │
                    ┌──────────────────┼──────────────────┐
               BrowserWorker    TerminalWorker    DesktopWorker
               (Playwright)     (asyncio exec)   (pywinauto UIA)
                                       │
                              ObjectiveReviewer (Gemini Pro)
                                       │
                              SQLite evidence + reflection store
```

## Setup

```bash
# Install dependencies
uv sync --extra dev

# Install Playwright browsers
uv run playwright install chromium

# Start Temporal dev server (requires temporal CLI)
temporal server start-dev

# Copy and fill env
cp .env.example .env
# Set GEMINI_API_KEY in .env
```

## Run

```bash
# Start the UI
uv run python -m trinity_pilot

# Start the Temporal worker (separate terminal)
uv run python -m trinity_pilot.worker_runner

# MCP servers (optional, for external tool access)
uv run python -m trinity_pilot.mcp.browser_server
uv run python -m trinity_pilot.mcp.terminal_server
uv run python -m trinity_pilot.mcp.desktop_server
```

## Tests

```bash
# Unit tests (no external deps)
uv run pytest tests/unit/ -v

# Integration tests (mocked Temporal)
uv run pytest tests/integration/ -v

# All tests
uv run pytest tests/ -v --cov=trinity_pilot
```

## Project layout

```
trinity_pilot/
  core/types.py          ObjectiveSpec, enums, ReviewResult
  llm/                   LLMProvider ABC + GeminiProvider
  planner/               ObjectivePlanner + DAG topological sort
  reviewer/              ObjectiveReviewer (typed failure reasons + recovery hints)
  workers/               BrowserWorker, TerminalWorker, DesktopWorker, WorkerRouter
  memory/                SQLite stores: tasks, attempts, evidence files, reflections
  workflow/              Temporal TaskWorkflow + activities
  mcp/                   FastMCP boundary servers (browser, terminal, desktop)
  ui/                    PySide6 MainWindow + WorkflowBridge
  config.py              Settings from .env
  worker_runner.py       Temporal worker entry point
```
