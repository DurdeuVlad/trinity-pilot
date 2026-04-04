# CLAUDE.md - trinity-pilot

This is the real tracked project.

## Non-negotiable rule

- Keep `trinity-pilot/` free of AI-workflow clutter.
- Do not create plans, handoffs, memory files, `.agents/`, scaffolding folders, or other AI-only artifacts here.
- Put that material in `../.ai/`.

## Code style

- Write code that looks like a normal human maintainer wrote it.
- Keep comments sparse and useful.
- Avoid obvious AI patterns, verbose boilerplate, and generated-looking structures.

## What this repo is

TrinityPilot is an AI-powered desktop automation orchestrator.
It controls desktop (Windows UIA), browser (Playwright), and CLI (PowerShell) via a unified GUI.

## Modules

| Module | Role |
|--------|------|
| `unified-app/` | Orchestrator GUI + execution engine (PyQt6) |
| `trinity_core/` | Unified adapter layer that dispatches tasks to the right backend |
| `api-accessibility-poc/` | Desktop automation backend (Windows UIA/COM) |
| `browser-gui-automation/` | Browser automation backend (Playwright/Node.js) |
| `cli-automation-poc/` | CLI/PowerShell automation backend |
| `audit-debugger/` | Debugging and audit tooling |

## File placement

| Type | Location |
|------|----------|
| Module source | `{module}/` |
| Tests | `{module}/tests/` |
| Docs | `docs/` |
| Temp / logs / output | `_runtime/` |

Never create root-level clutter here.

## Safety rules

- Never `git clean`
- Gate order: `implement -> test -> fix -> commit`
