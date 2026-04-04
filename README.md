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
| `browser-gui-automation` | Browser automation backend (Python Playwright) |
| `cli-automation-poc` | CLI/PowerShell automation backend |
| `audit-debugger` | Debugging and audit tooling |

## Requirements

- Python 3.10+
- Windows 10/11 (desktop automation requires Windows UIA)
- Gemini API key ([get one free](https://aistudio.google.com/apikey))

## Quick Start

### 1. Clone and Install

```bash
git clone https://github.com/your-username/trinity-pilot.git
cd trinity-pilot

# Install Python dependencies
pip install -r unified-app/requirements.txt
pip install -r api-accessibility-poc/requirements.txt
pip install -r cli-automation-poc/requirements.txt
pip install -r browser-gui-automation/requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. Configure API Key

```bash
# Copy the example config
cp .env.example unified-app/.env

# Edit unified-app/.env and add your Gemini API key
# Get a free key at: https://aistudio.google.com/apikey
```

Your `unified-app/.env` should look like:
```
GEMINI_API_KEY=your_actual_api_key_here
```

### 3. Run

```bash
cd unified-app
python main.py
```

The GUI will open maximized. Try a simple task like:
- *"list files in the current directory"* (CLI)
- *"open Notepad and type hello world"* (Desktop)
- *"navigate to example.com"* (Browser)

## Examples

**CLI Task:** *"show me the current directory and list its contents"*
- Routes to CLI backend
- Executes PowerShell commands
- Returns output in the status log

**Desktop Task:** *"open Calculator and type 5+5"*
- Uses Windows UIA to find and launch Calculator
- Simulates keyboard input
- Captures screenshots during execution

**Browser Task:** *"go to google.com and search for python"*
- Launches Chromium via Playwright
- Navigates and interacts with the page
- Returns search results

**Cross-Domain:** *"search google for 'AI news' and paste the first result title into Notepad"*
- Browser agent scrapes Google
- Desktop agent opens Notepad
- Data flows between domains

## Troubleshooting

**"No API key found"**
- Ensure `unified-app/.env` exists with `GEMINI_API_KEY=...`
- Verify the key is valid at https://aistudio.google.com/apikey

**"Browser automation failed"**
- Run `playwright install chromium` to install browser binaries
- Verify Playwright is installed: `pip list | grep playwright`

**"Desktop automation not working"**
- Windows 10/11 required (uses UIA)
- Run as administrator if accessing system apps

**GUI doesn't open**
- Check Python 3.10+ is installed
- Verify PyQt6 installed: `pip list | grep PyQt6`

## Tests

```bash
# Run all tests
pytest unified-app/tests trinity_core/tests -v

# Run with coverage
pytest unified-app/tests --cov=unified-app/orchestrator --cov=unified-app/ui
```

## License

MIT
