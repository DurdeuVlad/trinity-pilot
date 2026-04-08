# CLAUDE.md - trinity-pilot

This is the real tracked project.

## Non-negotiable rule

- Keep `trinity-pilot/` free of AI-workflow clutter.
- Do not create plans, handoffs, memory files, `.agents/`, scaffolding folders, or other AI-only artifacts here.
- Put that material in `../.ai/`.

## AI changelog rule

- Every AI assistant must create and maintain a changelog entry in `../.ai/changelog/` while working.
- Use dated files with a short title: `YYYY-MM-DD-short-title.md`.
- Start from `../.ai/changelog/ENTRY_TEMPLATE.md` and keep sections updated as work progresses.
- Log key decisions, file edits, command executions, and validation outcomes.

## Bachelor's degree research documentation rule

- **CRITICAL**: All work on this repository must be documented in `../DesktopAI_Research/Arhitecture_History/` for bachelor's degree research.
- Document **every mistake, decision, architectural change, bug fix, and implementation detail**.
- Place documentation in:
  - An existing dated folder under `Arhitecture_History/` if the topic fits and the folder is recent (within 2 weeks).
  - A new dated folder named `YYYY-MM-DD-topic-name/` if starting a new architectural topic or analysis.
- Use descriptive Markdown files with clear titles that explain what was done, why, what failed, and what succeeded.
- This documentation is for academic research purposes and must capture the full development journey, including failures and pivots.

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
