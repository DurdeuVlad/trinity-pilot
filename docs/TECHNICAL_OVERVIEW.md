# Trinity Pilot technical overview

Trinity Pilot is a local Windows desktop agent built around typed objectives, real application controls, independent evidence review, and bounded retries. This document keeps the implementation detail out of the landing page.

## Architecture

```text
PySide6 UI → WorkflowBridge → AsyncTaskOrchestrator
                                   │
                    ObjectivePlanner (OpenAI / Gemini)
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
                   ObjectiveReviewer (OpenAI / Gemini)
                                   │
                       SQLite WAL state + evidence
```

## Execution model

1. The planner turns a natural-language request into `ObjectiveSpec` records with domains, dependencies, risk classes, preconditions, and verification checklists.
2. The orchestrator resolves the DAG and sends each objective to the matching worker. Independent objectives can run in parallel; dependent objectives receive upstream evidence.
3. Workers use real tools rather than guessing from screenshots: Playwright for browsers, structured subprocess execution for terminals, and pywinauto UIA with PyAutoGUI fallback for desktop applications.
4. The reviewer independently checks screenshots, DOM state, stdout, file contents, and existence evidence. It returns a typed pass/fail result with a failure reason.
5. Failed objectives receive the reviewer's recovery hint and retry with the previous attempt context. Step, token, and wall-clock budgets bound the loop.
6. Tasks, attempts, evidence bundles, and reflections are persisted locally in SQLite using WAL mode.

## Main components

| Component | Responsibility |
|---|---|
| `trinity_pilot/core` | Typed objective, task, attempt, and review contracts |
| `trinity_pilot/planner` | Converts a request into a validated objective DAG |
| `trinity_pilot/orchestrator` | Schedules objectives, budgets work, and handles retries/cancellation |
| `trinity_pilot/workers` | Browser, terminal, and Windows desktop execution loops |
| `trinity_pilot/reviewer` | Evidence-backed review and typed failure classification |
| `trinity_pilot/mcp` | FastMCP capability boundary for browser, terminal, and sensor tools |
| `trinity_pilot/memory` | SQLite task, attempt, reflection, and evidence stores |
| `trinity_pilot/llm` | Provider interface plus OpenAI and Gemini implementations |
| `trinity_pilot/ui` | PySide6 desktop shell, setup dialog, activity panel, and bridge |

## Provider configuration

The repository example uses OpenAI:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-5.6-luna
```

Gemini remains available with `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, and the Gemini model settings. The provider abstraction is used by planning, worker execution, review, analysis, clarification, and streaming paths.

## Safety boundaries

The application is not a sandbox. Terminal commands run with the current user's permissions, and browser/desktop workers can affect real windows, files, and processes. The UI exposes approval and stop paths, workers enforce capability and risk gates, and evidence is retained for review. Use a disposable VM or low-privilege account for untrusted work. See [SECURITY.md](../SECURITY.md) and [Privacy and safety](PRIVACY_AND_SAFETY.md).

## Current verification

The deterministic test collection currently contains 512 tests:

- 418 unit tests
- 9 integration tests
- 85 UI tests

The latest accepted live Windows run covered the two GUI happy suites: 28 of 29 cases passed (96.6%). The remaining T9 Save-dialog failure is documented as non-blocking for the release gate. Live tests require a controlled Windows desktop and a configured provider key.

The original thesis benchmark is historical evidence, not a replacement for current checks: 56 scenarios were run three times each, with 139 of 168 runs passing (83%).

## Repository layout

```text
trinity_pilot/
  core/           typed contracts and enums
  llm/            provider interface and implementations
  planner/        objective planning and DAG construction
  orchestrator/   execution, state machine, budgets, and signals
  workers/        browser, terminal, and desktop workers
  reviewer/       evidence review and failure reasons
  mcp/            browser, terminal, and sensor servers
  memory/         SQLite persistence and evidence stores
  ui/              PySide6 application shell
tests/
  unit/           deterministic component tests
  integration/    local pipeline and boundary tests
  ui/             Qt widget tests
  e2e/            controlled live desktop suites
```
