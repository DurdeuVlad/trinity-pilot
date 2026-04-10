# Trinity Pilot

Trinity Pilot is a Windows desktop app that accepts a plain-language task, decides whether the work belongs in the browser, desktop UI, or terminal, and runs it through the matching backend.

The fastest way to use it is through the unified desktop in [`unified-app/`](unified-app/README.md). The other folders are the individual automation backends and support tooling.

## Repository Layout

- `unified-app/` - PyQt6 desktop shell, orchestration loop, history, settings, and live execution views
- `trinity_core/` - shared adapter layer that routes tasks to the correct backend
- `api-accessibility-poc/` - Windows desktop automation backend built on UI Automation
- `browser-gui-automation/` - browser automation backend built on Playwright
- `cli-automation-poc/` - terminal and PowerShell automation backend
- `audit-debugger/` - flight-report capture and inspection tools

## How It Works

1. The desktop app collects the objective and loads local settings and API credentials.
2. The orchestrator picks a domain from the task text and sends the work through `trinity_core`.
3. The selected backend plans actions, executes them, and reports progress back to the UI.
4. Screenshots, logs, and flight reports can be reviewed after the run.

## Run The Full Application

From the repository root:

```powershell
pip install -r unified-app/requirements.txt
pip install -r api-accessibility-poc/requirements.txt
pip install -r cli-automation-poc/requirements.txt
pip install -r browser-gui-automation/requirements.txt
playwright install chromium
```

Create `unified-app/.env` with a valid Gemini API key:

```env
GEMINI_API_KEY=your_key_here
```

Optional sanity check:

```powershell
python verify_installation.py
```

Start the desktop app:

```powershell
cd unified-app
python main.py
```

## What To Expect In The UI

- The main task view is where you enter objectives and watch status updates.
- History stores prior runs and their outcomes.
- Settings controls provider and runtime options.
- Glass-box style panels surface intermediate execution details while a task is running.

## Module Docs

- [`unified-app/README.md`](unified-app/README.md)
- [`api-accessibility-poc/README.md`](api-accessibility-poc/README.md)
- [`browser-gui-automation/README.md`](browser-gui-automation/README.md)
- [`cli-automation-poc/README.md`](cli-automation-poc/README.md)
- [`audit-debugger/README.md`](audit-debugger/README.md)

## Verification

```powershell
pytest unified-app/tests -v
pytest unified-app/tests -v -m integration
pytest unified-app/tests -v -m live
```
