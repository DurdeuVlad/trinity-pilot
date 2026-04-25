Status: Active
Owns: User interaction, clarification, objective generation, objective confirmation, domain selection, and the handoff into Trinity Core.
Does Not Own: Execution orchestration, backend-local planning loops, or hidden tool execution paths.

# Trinity Unified Desktop

## What This Is
`unified-app/` is the desktop product shell for Trinity Pilot. It is the only user-facing runtime in the active path.

Its job is to work with the user until the objective is correct, choose the right MCP target for that objective, and then hand the finalized request to Trinity Core.

## Responsibility
- Owns:
  - the PyQt6 desktop UI
  - clarification and conversation state
  - objective preview generation and editing
  - final objective confirmation
  - target selection and Desktop -> Core handoff
  - execution status display and local history
- Does Not Own:
  - global execution planning or retries
  - backend-side orchestration
  - hidden routing around Trinity Core

## How It Fits The Product
Active product flow:

`User -> Trinity Unified Desktop -> finalized objective + selected MCP target -> Trinity Core -> visible MCP tools`

- Input: natural-language user request
- Output: finalized task payload for Core plus execution UI
- Upstream dependency: user input and configured desktop-side provider
- Downstream dependency: [../trinity_core/README.md](../trinity_core/README.md)

## Folder Map
- `main.py` - desktop entrypoint
- `orchestrator/` - clarification, objective shaping, target selection, and Core handoff
- `ui/` - tabs, widgets, overlays, and presentation logic
- `mcp_server/` - internal tooling and desktop-side control surfaces, not the main product runtime
- `tests/` - unit, integration, and live-marked coverage for the desktop app

## Entry Points
Real product entrypoint:
- `python main.py`

Authoritative checks:
- `pytest tests -q`
- `pytest tests -q -m integration`

Support-only entrypoints:
- MCP and command-pipe utilities under `mcp_server/`

## Contracts
This silo is responsible for producing a valid handoff to Core:
- normalized domain
- selected target server
- finalized objective text
- approved objective steps
- runtime settings and cancellation context as needed

If the desktop cannot confirm those things, it should keep working with the user instead of guessing.

## Configuration
Expected local configuration:
- `GEMINI_API_KEY` - required for objective generation and desktop-side clarification flows
- `OPENAI_API_KEY` - required because the desktop hands execution to Trinity Core
- `unified-app/.env` - local configuration file based on `.env.example`

Common run commands:

```powershell
pip install -r requirements.txt
python main.py
```

## Development Workflow
Read [orchestrator/README.md](./orchestrator/README.md) before changing task flow logic.

Typical work split:
- UI behavior or panels: `ui/`
- handoff logic and objective shaping: `orchestrator/`
- support tooling or test harnesses: `mcp_server/`

Do not add execution logic here just because it is convenient. If the change is about retries, tool choice, or verification, it probably belongs in Core instead.

## Testing
- `pytest tests -q` - main confidence check for this silo
- `pytest tests -q -m integration` - in-process integration coverage
- `pytest tests -q -m live` - live checks when the change actually touches live runtime surfaces

Authoritative areas after the cleanup:
- handoff contract tests
- service-manager health checks
- integration tests that verify Desktop -> Core flow

## Known Architectural Boundaries
- Desktop owns clarification and target selection.
- Core owns execution.
- Backend silos expose tool primitives and support wrappers.
- `mcp_server/` is internal tooling, not the authority for the product execution path.

## Legacy / Compatibility Debt
Some desktop-adjacent support surfaces still exist:
- `mcp_server/` contains tooling for desktop control and session-style utilities
- support wrappers and live utilities still exist for diagnostics

They are useful, but they should not redefine the active architecture.

## Common Failure Modes
- Objective generation fails
  - Symptom: preview regeneration or modification fails before execution
  - First check: provider config and `GEMINI_API_KEY`
- Core health is unavailable
  - Symptom: service checks show unavailable targets or handoff fails immediately
  - First check: `OPENAI_API_KEY` and Core runtime readiness
- Wrong target selection
  - Symptom: a valid objective gets sent to the wrong MCP target
  - First check: domain normalization and target selection logic in `orchestrator/`

## Change Rules
- Do not add new desktop-side execution loops.
- Do not bypass Trinity Core from the product path.
- Keep objective editing and confirmation explicit.
- Update this README and `orchestrator/README.md` if handoff behavior changes.

## Related Docs
- [../README.md](../README.md)
- [orchestrator/README.md](./orchestrator/README.md)
- [mcp_server/README.md](./mcp_server/README.md)
- [../trinity_core/README.md](../trinity_core/README.md)
