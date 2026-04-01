# TrinityPilot

An AI-powered desktop automation orchestrator that controls **desktop**, **browser**, and **CLI** environments through a unified GUI.

Give it a natural-language task like *"find the top search result and paste the title into Notepad"* — it breaks it into steps, routes each one to the right backend, and executes end-to-end.

## What it does

- **Desktop** — Windows UI automation via UIA/COM (click, type, read windows)
- **Browser** — Web automation via Playwright (navigate, interact, scrape)
- **CLI** — Shell/PowerShell automation (run commands, parse output)

Cross-domain tasks work too: the browser agent can scrape a page and hand the result to the desktop agent to paste into an app.

## Architecture

```
unified-app/          ← PyQt6 GUI + orchestrator (LLM plan→act→reflect loop)
    │
    └── trinity_core/ ← Unified adapter layer — routes tasks to the right backend
            ├── CLIAdapter     → cli-automation-poc/
            ├── DesktopAdapter → api-accessibility-poc/
            └── BrowserAdapter → browser-gui-automation/
```

| Module | Role |
|--------|------|
| `unified-app` | Orchestrator GUI — task input, live HUD, execution history |
| `trinity_core` | Adapter layer — dispatches tasks to the correct backend |
| `api-accessibility-poc` | Desktop automation backend (Windows UIA/COM) |
| `browser-gui-automation` | Browser automation backend (Playwright/Node.js) |
| `cli-automation-poc` | CLI/PowerShell automation backend |
| `audit-debugger` | Debugging and audit tooling |

## Requirements

- Python 3.10+
- Windows 10/11 (desktop automation requires Windows UIA)
- Node.js 18+ (browser automation)
- Gemini API key ([get one free](https://aistudio.google.com/apikey))

## Setup

```bash
git clone https://github.com/your-username/trinity-pilot.git
cd trinity-pilot

# Python dependencies
pip install -r unified-app/requirements.txt
pip install -r api-accessibility-poc/requirements.txt
pip install -r cli-automation-poc/requirements.txt

# Browser automation dependencies (Node.js)
cd browser-gui-automation && npm install && cd ..

# API key
cp .env.example .env
# Edit .env — add your GEMINI_API_KEY
```

## Run

```bash
python unified-app/main.py
```

## Tests

```bash
pytest unified-app/tests trinity_core/tests -q
```

## License

MIT
