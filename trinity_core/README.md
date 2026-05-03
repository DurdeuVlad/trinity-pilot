Status: Active
Owns: Objective orchestration, sub-objective planning, domain routing, visible MCP tool usage, retries, and verification.
Does Not Own: User clarification or objective negotiation before submission.

# Trinity Core

## What This Is
`trinity_core/` is the active objective orchestrator for Trinity Pilot. It receives a finalized objective, plans domain-scoped sub-objectives, executes each sub-objective through the correct MCP target, and verifies the full objective.

This silo is the execution authority. It is not the user-facing layer.

## Responsibility
- Owns:
  - the Core objective contract
  - objective planning and validation
  - sub-objective routing and execution
  - tool catalog discovery and use
  - retries, queuing, and verification
  - Core-side telemetry and result envelopes
- Does Not Own:
  - user clarification
  - objective generation
  - pretending a missing prerequisite is a tool failure

## How It Fits The Product
Active flow:

`User -> Trinity Unified Desktop -> finalized objective -> Trinity Core -> domain-scoped sub-objectives -> visible MCP tools`

- Input: `TaskInput` with finalized objective, optional approved sub-objectives, and optional target hint
- Output: `TaskResult` with objective plan, sub-objective results, objective evidence, artifacts, and status
- Upstream dependency: [../unified-app/README.md](../unified-app/README.md)
- Downstream dependency: tool-provider silos and visible MCP servers

## Folder Map
- `trinity.py` - `ObjectiveOrchestrator`, the main objective orchestration entrypoint
- `objective_planner.py` - LLM-backed and deterministic objective planning
- `sub_objective_executor.py` - target-bound MCP runtime loop for one sub-objective
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
The active contract is objective-owned, not script-following. The Core owns finishing the objective by any valid route it can prove.

Expected input includes:
- `task_id`
- `description`
- normalized `domain`
- optional `target_server`
- approved `sub_objectives` or legacy `objective_steps`
- `expected_outcome`

Expected runtime behavior:
- Core creates and validates an `ObjectivePlan`
- Core runs preflight checks for prerequisites such as localhost services
- Core executes each `SubObjective` through one `SubObjectiveExecutor`
- Core collects `ObjectiveEvidence`
- Core verifies completion before returning success

Mixed objectives must split into domain-scoped sub-objectives. `mixed` must not default to a browser target.

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
- `objective_planner.py` for objective/sub-objective planning
- `sub_objective_executor.py` for one-target runtime loop behavior
- `strategy_registry.py` for target registration
- `tools/` for primitive tool behavior

If a change is about user intent or objective confirmation, stop and move back to the desktop silo.

## Testing
Authoritative:
- `pytest tests -q`

What this proves:
- model contracts
- objective orchestrator behavior
- sub-objective executor behavior
- visible tool integration

Live or support-heavy checks should be used only when changing real target runtimes.

## Known Architectural Boundaries
- Desktop owns clarification and app-side history/events/UI.
- Core owns objective planning, routing, execution, adaptation, and verification.
- Tool/provider silos own primitives, not the global loop.
- `toolset_mcp_server.py` should remain a visible-tool surface, not a hidden execution path.

## Legacy / Compatibility Debt
There is still compatibility logic around legacy `objective_steps`. Treat it as migration residue; new code should use objective/sub-objective terminology.

## Common Failure Modes
- Missing `OPENAI_API_KEY`
  - Symptom: initialization or health checks fail
  - First check: confirm environment and desktop handoff environment
- Unknown target server
  - Symptom: `StrategyRegistry` lookup fails
  - First check: inspect `objective_planner.py` and `strategy_registry.py`
- Missing localhost service
  - Symptom: `prerequisite_missing`
  - First check: start the exact URL reported in `TaskResult.metadata.failure_reason`
- Tool catalog mismatch
  - Symptom: runtime cannot use expected tools
  - First check: inspect `toolset_mcp_server.py` and the selected domain tool module

## Terminology
Consistent with the project-wide convention:

- **objective** - the top-level goal passed to the `ObjectiveOrchestrator`.
- **sub-objective** - a discrete piece of the objective. Never call these "steps".
- **ObjectiveOrchestrator** - owns the full objective until it is complete, blocked, or proven impossible.
- **SubObjectiveExecutor** - executes exactly one domain-scoped sub-objective through one MCP toolset.
- **turn** - one LLM request-response cycle. Never call these "iterations" or "rounds".

Code: `objective_steps` field is legacy input naming. New fields and metadata should use `sub_objectives`.

## Change Rules
- Do not route a mixed objective to one global executor.
- Do not let a sub-objective executor claim full objective completion.
- Prefer primitive tools and explicit runtime logic over adapter fat.
- Update this README and `tools/README.md` when the runtime contract changes.

## Related Docs
- [../README.md](../README.md)
- [../unified-app/README.md](../unified-app/README.md)
- [tools/README.md](./tools/README.md)
