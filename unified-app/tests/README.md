# Unified-App Test Suite

## Overview

This directory contains the test suite for unified-app, organized into three layers:

1. **Unit tests** (`tests/unit/`) - Isolated tests with no I/O
2. **Integration tests** (`tests/integration/`) - Tests with in-process infrastructure
3. **Real tests** (`tests/real/`) - Tests requiring live servers and API keys

## Test Infrastructure

### MCP Test Client

The MCP test client (`mcp_server/mcp_test_client.py`) provides stdio-based communication with the orchestrator-control MCP server for automated testing.

**Usage:**
```python
from mcp_server.mcp_test_client import MCPTestClient

client = MCPTestClient()
await client.connect()
result = await client.submit_task("echo Hello", "cli")
await client.disconnect()
```

### Screenshot Analyzer

The screenshot analyzer (`tests/screenshot_analyzer_simple.py`) validates HUD overlay elements in captured screenshots.

**Capabilities:**
- Detects full-screen dark overlay
- Verifies control panel position (bottom-right, 420px wide)
- Checks transparency level (~33% opacity)
- Validates HUD elements (step list, narration, pulsing indicator)

### Desktop Isolation

The desktop isolation utility (`tests/desktop_isolation.py`) moves unified-app to a specific Windows virtual desktop for test isolation.

**Limitations:**
- Windows 10/11 only
- Uses keyboard shortcuts (may be fragile)
- Graceful fallback if isolation fails (runs on current desktop)

## Running Tests

### Unit Tests
```bash
pytest unified-app/tests/unit/ -v
```

### Integration Tests
```bash
# Requires unified-app running
python unified-app/main.py &
pytest unified-app/tests/integration/ -v
```

### Automated HUD Validation
```bash
# Full HP-01 through HP-05 test suite
python unified-app/tests/automated_hud_validation.py --desktop 2 --output reports/hud_validation.md
```

## Test Fixtures

Screenshot fixtures are stored in `tests/fixtures/screenshots/`:
- `hud_visible_*.png` - Screenshots with HUD overlay shown
- `hud_dismissed_*.png` - Screenshots without HUD overlay

To capture fixtures:
1. Start unified-app
2. Submit a test task
3. Capture screenshot when HUD is visible
4. Dismiss HUD and capture screenshot
5. Save to `tests/fixtures/screenshots/`

## Known Limitations

### Desktop Isolation
- May fail on some Windows versions
- Keyboard shortcuts (Win+Ctrl+Arrow) may not work reliably
- Tests will run on current desktop if isolation fails

### Screenshot Analysis
- Accuracy depends on screen resolution and wallpaper brightness
- Target accuracy: >= 80% on test fixtures
- May need threshold adjustments for different environments

### MCP Server
- Requires unified-app to be running
- Uses stdio protocol (subprocess communication)
- Server must be accessible at `mcp_server/orchestrator_mcp.py`

## Troubleshooting

### "Unified-app not running" error
Start unified-app before running integration tests:
```bash
python unified-app/main.py
```

### Desktop isolation fails
This is expected on some systems. Tests will run on current desktop with a warning.

### Screenshot analyzer accuracy < 80%
Adjust detection thresholds in `screenshot_analyzer_simple.py` based on your environment.

### MCP connection errors
Ensure MCP server script exists and Python `mcp` package is installed:
```bash
pip install mcp
```
