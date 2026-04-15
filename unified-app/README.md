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

Create `unified-app/.env` based on `.env.example`:

```env
GEMINI_API_KEY=your_key_here

# Backend MCP Routing (optional)
USE_CLI_MCP=false
USE_BROWSER_MCP=false
USE_DESKTOP_MCP=false
```

From the repository root, you can verify the overall setup with:

```powershell
python verify_installation.py
```

### MCP Backend Integration

The unified app can route backend execution through MCP servers or legacy HTTP services using feature flags:

- **`USE_CLI_MCP=true`** - Route CLI tasks through `cli-automation-poc/cli_mcp_server.py`
- **`USE_BROWSER_MCP=true`** - Route browser tasks through `browser-gui-automation/browser_mcp_server.py`
- **`USE_DESKTOP_MCP=true`** - Route desktop tasks through `api-accessibility-poc/desktop_mcp_server.py`

**Default**: All flags are `false`, using legacy HTTP service routing.

**Mixed mode**: Each backend can be toggled independently. For example:
```env
USE_CLI_MCP=true
USE_BROWSER_MCP=false
USE_DESKTOP_MCP=true
```

This routes CLI and Desktop through MCP while Browser uses HTTP.

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
