Status: Active
Owns: Desktop-side clarification, objective shaping, domain normalization, target selection, and handoff into Trinity Core.
Does Not Own: The execution loop itself, backend-local orchestration, or hidden adapter-era routing.

# Unified App Orchestrator

## What This Is
`unified-app/orchestrator/` contains the desktop-side logic that turns a user request into a finalized, approved execution payload for Trinity Core.

After the cleanup, this folder is intentionally narrower than before. It is no longer the home of the product execution loop.

## Responsibility
- Owns:
  - clarification flow
  - objective preview generation and modification
  - domain normalization
  - target selection
  - Desktop -> Core handoff
  - local history, events, and desktop-facing status flow
- Does Not Own:
  - execution retries or plan/act/replan loops
  - backend routing around Core
  - hidden module-service orchestration

## How It Fits The Product
This folder is the bridge between user-facing desktop UX and Core execution.

`User -> unified-app UI -> orchestrator/ -> TrinityBridge -> Trinity Core`

- Input: natural-language task plus user edits/approval
- Output: finalized `TaskInput`-like handoff to Core
- Upstream dependency: UI events and settings
- Downstream dependency: [../../trinity_core/README.md](../../trinity_core/README.md)

## Folder Map
- `orchestrator_core.py` - main desktop workflow coordination and worker lifecycle
- `trinity_bridge.py` - explicit Desktop -> Core handoff layer
- `service_manager.py` - Core-health compatibility shim, not a subprocess launcher anymore
- `clarification_engine.py` - conversation and clarification logic
- `macro_planner.py` - objective preview generation, not the execution loop
- `objectives_decomposer.py` - objective editing and decomposition helpers
- `event_bus.py` - desktop event plumbing
- `database/` - local history persistence
- `providers/` - desktop-side provider wiring for clarification/objective generation

## Entry Points
Indirect entrypoints used by the desktop app:
- `orchestrator_core.py`
- `trinity_bridge.py`
- `service_manager.py`

Authoritative checks:
- `pytest ../tests -q`

## Contracts
Important internal contracts:
- clarification produces either follow-up questions or a ready task summary
- objective preview produces editable objective steps
- target selection maps domain to a specific MCP target server
- `TrinityBridge` converts the finalized desktop state into Core's task contract

`ServiceManager` is no longer allowed to imply that the desktop launches the old module-service subprocesses as the product path.

## Configuration
This folder depends on:
- desktop runtime settings from `SettingsManager`
- `GEMINI_API_KEY` for objective generation paths
- `OPENAI_API_KEY` indirectly because `TrinityBridge` initializes Core

## Development Workflow
Read this folder in this order:
1. `orchestrator_core.py`
2. `trinity_bridge.py`
3. `service_manager.py`
4. objective generation helpers such as `macro_planner.py`

If you find yourself adding step execution, retries, or tool selection here, you are likely putting code in the wrong silo.

## Testing
The most important tests for this folder are in `../tests/`:
- bridge tests
- service-manager tests
- integration tests for the full desktop handoff

Use live tests only when the change touches a real provider or support wrapper.

## Known Architectural Boundaries
- This folder owns task shaping, not execution.
- `TrinityBridge` owns handoff, not UI.
- `ServiceManager` reports Core-side readiness, not backend subprocess lifecycle.
- Live/domain diagnostics under `../tests/` are adjacent but not authoritative for the GUI path.

## Legacy / Compatibility Debt
This folder still contains historical names like `macro_planner` and compatibility-focused status plumbing. Keep them only if they still serve the cleaned desktop role. Do not use them as a reason to reintroduce old execution-runner behavior.

## Common Failure Modes
- Clarification loop never reaches a ready task
  - Symptom: user cannot get to objective approval
  - First check: provider config and clarification engine behavior
- Target selection is wrong
  - Symptom: valid task gets handed to the wrong server
  - First check: domain normalization and target-selection helpers in `orchestrator_core.py`
- Core handoff fails on startup
  - Symptom: service health and execution start both fail
  - First check: `OPENAI_API_KEY` and `TrinityBridge.initialize()`

## Change Rules
- Do not add `AgentLoop`-style execution back here.
- Do not add hidden routing adapters.
- Keep `TrinityBridge` explicit and narrow.
- Update this README when ownership changes inside this folder.

## Related Docs
- [../README.md](../README.md)
- [../../trinity_core/README.md](../../trinity_core/README.md)
