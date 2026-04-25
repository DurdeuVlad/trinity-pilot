Status: Active
Owns: Execution orchestration, visible MCP tool usage, retries, and verification for finalized desktop objectives.
Does Not Own: User clarification, objective negotiation, or domain selection when the desktop has already chosen the target.

# Trinity Core

## What This Is
`trinity_core/` is the active execution orchestrator for Trinity Pilot. It receives a finalized objective and selected MCP target from the desktop, executes against the target's visible tools, and verifies the result.

This silo is the execution authority. It is not the user-facing layer.

## Responsibility
- Owns:
  - the Core runtime contract
  - target-bound execution
  - tool catalog discovery and use
  - retries, queuing, and verification
  - Core-side telemetry and result envelopes
- Does Not Own:
  - user clarification
  - objective generation
  - re-deciding the business/domain route after the desktop chose it

## How It Fits The Product
Active flow:

`User -> Trinity Unified Desktop -> finalized objective + selected MCP target -> Trinity Core -> visible MCP tools`

- Input: `TaskInput` with finalized objective and selected target server
- Output: `TaskResult` with result metadata, artifacts, and status
- Upstream dependency: [../unified-app/README.md](../unified-app/README.md)
- Downstream dependency: tool-provider silos and visible MCP servers

## Folder Map
- `trinity.py` - `TrinityExecutor`, the main execution entrypoint
- `mcp_strategy_runtime.py` - target-bound MCP runtime loop
- `strategy_registry.py` - registry of available MCP-backed targets
- `models.py` - task and result contracts
- `toolset_mcp_server.py` - internal visible-tool MCP server used by the active runtime
- `tools/` - primitive tool implementations grouped by domain
- `tests/` - authoritative runtime, contract, and integration coverage

## Entry Points
Primary code entrypoints:
- `trinity.py`
- `toolset_mcp_server.py`

Authoritative checks:
- `pytest tests -q`

This silo is not an end-user app. It is called by the desktop and by focused tests.

## Contracts
The active contract is target-bound, not route-discovering.

Expected input includes:
- `task_id`
- `description`
- normalized `domain`
- `target_server`
- approved `objective_steps`
- `expected_outcome`

Expected runtime behavior:
- Core resolves the selected target
- discovers visible tools
- executes against those tools
- verifies completion

Compatibility fallback still exists for missing `target_server`, but new work should treat the desktop-selected target as authoritative.

## Configuration
Common runtime requirements:
- `OPENAI_API_KEY` - required for the active runtime provider
- target-specific local prerequisites depending on the selected tool domain

Typical validation command:

```powershell
pytest tests -q
```

## Development Workflow
Start with:
- `trinity.py` for execution flow
- `mcp_strategy_runtime.py` for runtime loop behavior
- `strategy_registry.py` for target registration
- `tools/` for primitive tool behavior

If a change is about user intent or objective confirmation, stop and move back to the desktop silo.

## Testing
Authoritative:
- `pytest tests -q`

What this proves:
- model contracts
- executor behavior
- MCP runtime behavior
- visible tool integration

Live or support-heavy checks should be used only when changing real target runtimes.

## Known Architectural Boundaries
- Desktop owns clarification and target selection.
- Core owns execution and verification.
- Tool/provider silos own primitives, not the global loop.
- `toolset_mcp_server.py` should remain a visible-tool surface, not a hidden execution path.

## Legacy / Compatibility Debt
There is still compatibility logic around target resolution and alternate strategy surfaces. Treat it as migration residue, not a reason to move routing back into Core.

## Common Failure Modes
- Missing `OPENAI_API_KEY`
  - Symptom: initialization or health checks fail
  - First check: confirm environment and desktop handoff environment
- Unknown target server
  - Symptom: `StrategyRegistry` lookup fails
  - First check: inspect desktop target selection and `strategy_registry.py`
- Tool catalog mismatch
  - Symptom: runtime cannot use expected tools
  - First check: inspect `toolset_mcp_server.py` and the selected domain tool module

## Change Rules
- Do not move domain selection back into Core.
- Do not add hidden mini-agent behavior behind the visible tool contract.
- Prefer primitive tools and explicit runtime logic over adapter fat.
- Update this README and `tools/README.md` when the runtime contract changes.

## Related Docs
- [../README.md](../README.md)
- [../unified-app/README.md](../unified-app/README.md)
- [tools/README.md](./tools/README.md)
