# Integration Testing

Status: support doc. The architecture authority is `ARCHITECTURE_TRUTH.md`.

This guide describes the current test roles. It does not define the product architecture.

## Product Path

```text
User -> Trinity Unified Desktop -> approved sub-objectives + selected target
     -> Trinity Core -> visible MCP/domain tools
```

## Authoritative Commands

Run commands from the named folder.

| Folder | Command | Purpose |
|---|---|---|
| `unified-app/` | `python -m pytest -q tests` | Desktop app contracts, GUI user-flow smoke, bridge, routing, and runner diagnostics. |
| `trinity_core/` | `python -m pytest -q tests` | Core objective orchestration, visible tool contracts, verification, telemetry. |
| `api-accessibility-poc/` | `python -m pytest -q tests` | Desktop provider primitives and support behavior. |
| `browser-gui-automation/` | `python -m pytest -q tests` | Browser provider primitives and support behavior. |
| `cli-automation-poc/` | `python -m pytest -q tests` | CLI provider primitives and support behavior. |

## Test Taxonomy

| Test family | Authority |
|---|---|
| GUI smoke tests under `unified-app/tests/smoke/` | Product user-flow smoke. These should drive the unified app like a user: prompt, plan review, Run acceptance, result. |
| `unified-app/tests/integration/` | In-process contracts and runner/domain diagnostics. Useful, but not full GUI smoke unless the test drives `MainWindow`. |
| `unified-app/tests/run_live_domain_scenarios.py` | Live bridge/domain diagnostics. It bypasses the GUI, so do not call it the smoke suite. |
| `trinity_core/tests/` | Core runtime health. |
| Provider silo tests | Primitive/support health for the touched domain provider. |

## Live Domain Scenarios

The target product-health suite is nine live domain scenarios:

- CLI easy
- CLI moderate
- Web/browser easy
- Web/browser moderate
- Desktop easy
- Desktop moderate
- Cross-domain easy
- Cross-domain moderate
- Cross-domain complex

If the full suite is too expensive or blocked, run the relevant single scenario and state exactly which scenarios were not run.

## What Not To Trust

- Old module-service startup instructions using three local service windows as the product path.
- Bridge-only tests as proof that GUI prompt/review/Run works.
- Archived tests. Stale tests should be salvaged into current test families or deleted.
- Generated screenshots, logs, `_runtime`, `sessions`, and cache folders.

## Setup

Common dependency setup:

```powershell
pip install -r unified-app/requirements.txt
pip install -r api-accessibility-poc/requirements.txt
pip install -r cli-automation-poc/requirements.txt
pip install -r browser-gui-automation/requirements.txt
playwright install chromium
```

Common environment variables:

- `OPENAI_API_KEY` for Trinity Core execution.
- `GEMINI_API_KEY` for desktop-side objective generation and some support wrappers.
