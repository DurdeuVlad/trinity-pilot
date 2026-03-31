# TrinityPilot

An AI-powered desktop automation orchestrator that controls **desktop**, **browser**, and **CLI** environments through a unified interface.

## What it does

TrinityPilot lets an AI agent execute multi-step tasks across three domains simultaneously:

- **Desktop** — Windows UI automation via UIA/COM (click, type, read windows)
- **Browser** — Web automation via Playwright (navigate, interact, scrape)
- **CLI** — Shell/PowerShell automation (run commands, parse output)

A single natural-language task like *"find the top result on Google and open it in Notepad"* gets broken into steps, routed to the right backend, and executed end-to-end.

## Modules

| Module | Description |
|--------|-------------|
| `unified-app` | Main orchestrator GUI — task input, live HUD, execution history |
| `api-accessibility-poc` | Desktop automation backend (Windows UIA/COM) |
| `browser-gui-automation` | Browser automation backend (Playwright/Node.js) |
| `cli-automation-poc` | CLI/PowerShell automation backend |
| `audit-debugger` | Debugging and audit tooling |

## Architecture

```
unified-app (orchestrator)
    │
    ├── api-accessibility-poc   ← Desktop domain
    ├── browser-gui-automation  ← Browser domain
    └── cli-automation-poc      ← CLI domain
```

The orchestrator receives a task, uses an LLM (Gemini) to plan steps, and dispatches each step to the appropriate backend. Results flow back through a shared `ExecutionContext`.

## Requirements

- Python 3.10+
- Windows 10/11 (desktop automation requires Windows UIA)
- Node.js 18+ (browser automation)
- Gemini API key

## Setup

```bash
# Clone the repo
git clone https://github.com/DurdeuVlad/trinity-pilot.git
cd trinity-pilot

# Install Python dependencies (per module)
pip install -r unified-app/requirements.txt
pip install -r api-accessibility-poc/requirements.txt
pip install -r cli-automation-poc/requirements.txt

# Install browser automation dependencies
cd browser-gui-automation && npm install

# Set your API key
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

## Running

```bash
python unified-app/main.py
```

## License

MIT
