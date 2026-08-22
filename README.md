<div align="center">

# Trinity Pilot

### A Windows desktop agent that finishes real tasks.

Type a goal in plain English. Trinity Pilot turns it into a typed workflow, operates your browser, terminal, and desktop apps, checks the evidence, and retries when a step fails.

[![CI](https://github.com/DurdeuVlad/trinity-pilot/actions/workflows/ci.yml/badge.svg)](https://github.com/DurdeuVlad/trinity-pilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests: 512](https://img.shields.io/badge/Tests-512-brightgreen.svg)](#verification)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D6.svg)](#safety-and-privacy)

</div>

> **Project status:** early-stage, Windows-first open-source software. It is useful for controlled local automation, but it is not a sandbox and should not be pointed at systems or data you cannot afford to change.

## Why Trinity Pilot

Most desktop-agent demos stop at “the model clicked something.” Trinity Pilot treats a task as work that needs to finish:

- The planner creates typed objectives with dependencies, risk classes, and success checks.
- Domain workers use real browser, terminal, and Windows UI controls instead of guessing from pixels.
- A separate reviewer checks evidence such as screenshots, DOM state, stdout, and file contents.
- Failed objectives receive recovery context and bounded retries instead of an untracked second attempt.
- Task state, attempts, reflections, and evidence stay in a local SQLite store.

The tradeoff is deliberate: the system is more structured than a single prompt-to-click loop, but it needs a configured model provider and a controlled Windows environment.

## What it can do

Trinity Pilot handles workflows such as:

- opening a browser, reading a page, and saving a result to a file;
- creating folders and files with PowerShell or Python, then verifying their contents;
- launching Windows applications, entering data, reading controls, and closing them safely;
- combining browser, terminal, and desktop steps in one dependency-aware task;
- stopping or reviewing a task before high-risk actions continue.

Example:

```text
Open Notepad, type today's date, save it to my Desktop, then verify the file with a terminal command.
```

## See it in action

| Startup | Planning |
|---|---|
| ![Trinity Pilot startup](docs/screenshots/app-startup.png) | ![Generated task plan](docs/screenshots/task-planning.png) |

| Executing | Complete |
|---|---|
| ![Task executing](docs/screenshots/task-executing.png) | ![Task complete](docs/screenshots/task-complete.png) |

## Install and run

### Option 1: Windows release

1. Download [`trinity-pilot-win64.zip`](https://github.com/DurdeuVlad/trinity-pilot/releases) from Releases.
2. Extract it and launch `trinity-pilot.exe`.
3. Enter an API key in the setup dialog.

The standalone build is the fastest way to try the application. It still controls the real desktop, so use a disposable Windows account or VM for untrusted tasks.

### Option 2: Run from source

Requirements: Windows, Python 3.11+, [uv](https://docs.astral.sh/uv/), and a provider API key.

```bash
git clone https://github.com/DurdeuVlad/trinity-pilot.git
cd trinity-pilot
uv sync --extra dev
uv run playwright install chromium
uv run python -m trinity_pilot
```

The repository example uses OpenAI:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-5.6-luna
```

Gemini remains supported:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
```

The provider switch covers planning, worker execution, review, analysis, clarification, and streaming. Never commit `.env` files or API keys.

## How a task moves through the system

```text
Request → typed plan → domain workers → evidence review → pass or bounded retry
```

The UI and orchestrator stay local. Browser objectives use Playwright, terminal objectives use structured subprocess execution, and desktop objectives use pywinauto UIA with a PyAutoGUI fallback. The reviewer does not accept a worker's success claim without checking the available evidence.

For the full architecture, component map, provider contract, persistence model, safety boundaries, and repository layout, read [Technical overview](docs/TECHNICAL_OVERVIEW.md).

## Verification

The current deterministic suite collects 512 tests:

| Layer | Tests | Scope |
|---|---:|---|
| Unit | 418 | typed contracts, workers, providers, orchestration, persistence |
| Integration | 9 | local pipeline and capability boundaries |
| UI | 85 | PySide6 widgets and interaction state |

The latest accepted live Windows run covered the two GUI happy suites: 28 of 29 cases passed (96.6%). One Save-dialog case remains a documented, non-blocking E2E failure. Live tests require a visible Windows desktop and a configured provider key.

Run the deterministic checks with:

```bash
uv run --extra dev pytest tests/unit tests/integration tests/ui -v
uv run ruff check .
uv run mypy trinity_pilot
```

## Safety and privacy

Trinity Pilot is not sandboxed. Terminal commands run with the current user's permissions and can read, modify, delete, or create accessible files. Browser and desktop workers can interact with real windows, processes, and network resources. Review the generated plan before approving it.

Prompts and execution evidence can be sent to the configured LLM provider. Trinity Pilot stores task state and evidence locally in SQLite; it is not a hosted control plane. Do not use it with credentials, private data, or production systems unless you understand the provider and local-permission risks.

Read [SECURITY.md](SECURITY.md) and [Privacy and safety](docs/PRIVACY_AND_SAFETY.md) before running live tasks.

## Known limitations

- Windows is the supported desktop platform; GUI tests require a controlled visible desktop.
- Live model behavior is probabilistic, so passing deterministic tests does not guarantee every task will succeed.
- The current accepted happy-suite result is 28/29; the remaining failure is an order-sensitive Notepad Save-dialog path.
- Provider keys and network access are required for live model runs. Unit and most integration tests use stubs and do not need a real key.
- This project is a local desktop application, not a hosted multi-user service or security sandbox.

## Contributing

Contributions are welcome, especially fixes that improve evidence quality, Windows reliability, provider parity, and test isolation.

Before opening a pull request:

1. Keep the change focused and explain the problem it solves.
2. Add or update tests for behavior changes.
3. Run the deterministic test, lint, and type checks above.
4. Do not commit API keys, `.env` files, databases, private screenshots, or generated runtime artifacts.
5. Update user-facing documentation when permissions, data flow, or setup changes.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the project workflow and [SECURITY.md](SECURITY.md) for vulnerability reports. The [technical overview](docs/TECHNICAL_OVERVIEW.md) explains where a change belongs.

## License and research context

Trinity Pilot is released under the [MIT License](LICENSE). It was built as a bachelor's thesis project at the [Technical University of Cluj-Napoca](https://www.utcluj.ro/), Faculty of Automation and Computers.
