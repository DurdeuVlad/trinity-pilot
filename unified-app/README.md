# Unified App

This module is the desktop front end for Trinity Pilot. It owns the PyQt6 window, task input flow, orchestration loop, execution history, settings, and the live panels that show what each backend is doing.

## Run It

From `trinity-pilot/unified-app/`:

```powershell
pip install -r requirements.txt
python main.py
```

If you are starting from a clean clone, install the backend requirements from the repository root as well, because `main.py` imports the desktop, browser, CLI, and audit modules directly.

## Required Config

Create `unified-app/.env` and add:

```env
GEMINI_API_KEY=your_key_here
```

From the repository root, you can verify the overall setup with:

```powershell
python verify_installation.py
```

## What This Module Does

- boots the Qt application and loads local `.env` settings
- builds the provider, orchestrator core, and event bus
- routes objectives into the Trinity backends
- shows live status, plans, screenshots, and past runs

## Main Areas

- `main.py` - application bootstrap and window wiring
- `orchestrator/` - execution loop, persistence, providers, and runtime coordination
- `ui/` - tabs, panels, overlays, and styling
- `tests/` - unit, integration, and live-marked tests

## Useful Commands

```powershell
pytest tests -v
python main.py
.\build.ps1 -Version 0.0.0-dev
```
