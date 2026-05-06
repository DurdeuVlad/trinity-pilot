# Trinity Pilot Architecture Truth

Status: authoritative as of 2026-05-06.

This file is the first document to trust when old tests, docs, or support folders disagree.

## Active Product Flow

```text
User -> Trinity Unified Desktop -> approved sub-objectives + selected target
     -> Trinity Core -> visible MCP/domain tools
```

The active user path starts in `unified-app/main.py`. The desktop UI collects the prompt, shows editable sub-objectives, waits for the user to click Run, then hands execution to `trinity_core` through `unified-app/orchestrator/trinity_bridge.py`.

`trinity_core` owns execution. It plans/runs/verifies domain-scoped sub-objectives through visible tools. Provider silos expose primitives and support wrappers; they do not own the global loop.

## Trusted Entrypoints

| Entrypoint | Role |
|---|---|
| `unified-app/main.py` | User-facing desktop app entrypoint. |
| `unified-app/app.py` | MainWindow wiring for prompt submission, plan review, Run acceptance, and result display. |
| `unified-app/orchestrator/trinity_bridge.py` | Explicit Desktop -> Core handoff. |
| `trinity_core/trinity.py` | Core objective orchestration. |
| `trinity_core/toolset_mcp_server.py` | Visible tool MCP surface used by the active runtime. |

## Trusted Tests

| Command | What it proves |
|---|---|
| `cd unified-app; python -m pytest -q tests` | Desktop app contracts, GUI user-flow wiring, bridge behavior, deterministic routing, and runner diagnostics. |
| `cd trinity_core; python -m pytest -q tests` | Core runtime contracts, objective orchestration, visible tools, verification, and telemetry. |
| `cd api-accessibility-poc; python -m pytest -q tests` | Desktop provider primitives and support behavior. |
| `cd browser-gui-automation; python -m pytest -q tests` | Browser provider primitives and support behavior. |
| `cd cli-automation-poc; python -m pytest -q tests` | CLI provider primitives and support behavior. |
| `cd unified-app; python tests/run_live_domain_scenarios.py` | Live bridge/domain diagnostics only. This is not the GUI smoke suite. |

The important product-health target remains the nine live domain scenarios, but this cleanup does not expand that suite. It removes false tests and makes current test roles explicit.

## Surface Classifications

| Surface | Classification | Trust rule |
|---|---|---|
| `unified-app/` | active | Trust for desktop UX, objective approval, target selection, and handoff. |
| `trinity_core/` | active | Trust for execution, visible tools, retries, and verification. |
| `api-accessibility-poc/` | support | Trust as desktop automation primitives/support, not product orchestration. |
| `browser-gui-automation/` | support | Trust as browser primitives/support, not product orchestration. |
| `cli-automation-poc/` | support | Trust as CLI primitives/support, not product orchestration. |
| root diagnostic scripts | support | Useful only when current docs or tests reference them. They are not architecture. |
| root screenshots/logs/cache/runtime folders | dead | Generated artifacts. Do not treat as source. |
| `unified-app/tests/_archived_legacy/` | dead | Removed. No permanent stale-test archive. |

Full evidence is in `ARCHITECTURE_LEDGER.md`.

## Banned Assumptions

- Do not call bridge-level or runner-level tests the GUI smoke suite.
- Do not say `mixed` work defaults to browser. Mixed work must split into domain-scoped sub-objectives or use an explicit target decision.
- Do not reintroduce desktop-side execution loops in `unified-app`.
- Do not move target selection back into `trinity_core`.
- Do not let provider silos grow hidden mini-agent orchestration.
- Do not treat generated screenshots, logs, `_runtime`, `sessions`, caches, or old archives as product source.
- Do not preserve broken tests in a permanent archive. Salvage current behavior or delete.

## Current Cleanup Result

This cleanup deletes the old archived unified-app tests and root generated artifacts. It preserves ambiguous support scripts and demo folders because they need stronger evidence before deletion.
