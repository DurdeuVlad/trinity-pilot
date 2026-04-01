# CLAUDE.md — trinity-pilot

> AI agent instructions for this repository.
> One file, root only. No per-module AI files.

## What this repo is

TrinityPilot is an AI-powered desktop automation orchestrator.
It controls desktop (Windows UIA), browser (Playwright), and CLI (PowerShell) via a unified GUI.

## Modules

| Module | Role |
|--------|------|
| `unified-app/` | Orchestrator GUI + execution engine (PyQt6) |
| `trinity_core/` | Unified adapter layer — dispatches tasks to the right backend |
| `api-accessibility-poc/` | Desktop automation backend (Windows UIA/COM) |
| `browser-gui-automation/` | Browser automation backend (Playwright/Node.js) |
| `cli-automation-poc/` | CLI/PowerShell automation backend |
| `audit-debugger/` | Debugging and audit tooling |

## Architecture

```
unified-app/orchestrator/
    └── OrchestratorCore → TrinityBridge → TrinityExecutor (trinity_core/)
                                                ├── CLIAdapter     → cli-automation-poc/
                                                ├── DesktopAdapter → api-accessibility-poc/
                                                └── BrowserAdapter → browser-gui-automation/
```

## File placement

| Type | Location |
|------|----------|
| Module source | `{module}/` |
| Tests | `{module}/tests/` |
| Docs | `docs/` |
| Temp / logs / output | `_runtime/` (not committed) |

**Never create files in the repo root.** Only `CLAUDE.md`, `README.md`, `.gitignore` belong here.

## Safety rules

- **Never `git clean`** — deletes untracked files permanently
- Gate order: `implement → test → fix → commit`

## Running the app

```bash
python unified-app/main.py
```

## Running tests

```bash
pytest unified-app/tests -q
pytest trinity_core/tests -q
pytest api-accessibility-poc/tests -q
pytest cli-automation-poc/tests -q
```
