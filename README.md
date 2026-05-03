Status: Active
Owns: The top-level product map, cross-silo orientation, and the truthful description of how Trinity Pilot is split across desktop, Core, tool providers, and support tooling.
Does Not Own: Detailed implementation rules for any one silo; those belong in each silo README.

# Trinity Pilot

## What This Is
Trinity Pilot is the real product repository inside this workspace. Its active product flow is:

`User -> Trinity Unified Desktop -> finalized objective + selected MCP target -> Trinity Core -> visible MCP tools`

This README is the honest map of that split. It should help a new developer or AI find the right silo without reviving old architecture by accident.

## Responsibility
- Owns:
  - the top-level architecture map
  - the entrypoint and silo layout
  - the distinction between active product path and support-heavy or tooling-only folders
- Does Not Own:
  - low-level implementation detail for each silo
  - hidden architectural exceptions not reflected in the code

## How It Fits The Product
This repository contains the full product runtime and its adjacent support tooling.

- Upstream input: user intent from the desktop UI
- Active flow:
  1. `unified-app/` clarifies intent, generates objectives, confirms the plan, and selects the MCP target.
  2. `trinity_core/` executes the finalized objective against the selected target's visible tools.
  3. Tool-provider silos expose desktop, browser, or CLI primitives that Core can use.
- Downstream output: task results, telemetry, artifacts, and audit traces

## Folder Map
- `unified-app/` - active desktop product shell and Desktop -> Core handoff
- `trinity_core/` - active execution orchestrator and visible MCP runtime
- `api-accessibility-poc/` - Windows desktop automation primitives and support surfaces
- `browser-gui-automation/` - browser automation primitives and support surfaces
- `cli-automation-poc/` - CLI and PowerShell automation primitives and support surfaces
- `audit-debugger/` - internal tooling for audit capture and inspection
- `scripts/` - operational helper scripts for setup, service checks, and local validation
- `puppeteer-mcp-wrapper/` - non-default Puppeteer MCP wrapper retained as an alternate browser strategy

## Entry Points
Real product entrypoints:
- `cd unified-app && python main.py`
- `pytest trinity_core/tests -q`
- `pytest unified-app/tests -q`

Support and debug entrypoints:
- `python verify_installation.py`
- `.\scripts\start_services.ps1` - compatibility-heavy support script that launches the older module-service stack for local diagnostics
- `.\scripts\test_services.ps1` - companion health check for that support stack

Not all runnable folders are equal. Some backend wrappers are still useful for support and live diagnostics, but they are not the authority for global orchestration.

## Contracts
The most important repository-level contract is the Desktop -> Core handoff:

- Desktop sends:
  - finalized objective text
  - approved objective steps
  - normalized domain
  - selected MCP target server
- Core expects:
  - a valid target server or a compatible fallback
  - the runtime API keys required for execution
  - visible tool catalogs from the selected MCP runtime
- Tool silos provide:
  - primitive, visible tools
  - support wrappers where still intentionally retained
  - no ownership of the global orchestration loop

## Configuration
Common setup from the repository root:

```powershell
pip install -r unified-app/requirements.txt
pip install -r api-accessibility-poc/requirements.txt
pip install -r cli-automation-poc/requirements.txt
pip install -r browser-gui-automation/requirements.txt
playwright install chromium
```

Common environment variables:
- `OPENAI_API_KEY` - required for the active Trinity Core runtime
- `GEMINI_API_KEY` - required for desktop-side objective generation and some support wrappers

The desktop app reads `unified-app/.env`.

## Development Workflow
Start with the silo README that matches the responsibility you are changing:
- desktop behavior: [unified-app/README.md](./unified-app/README.md)
- execution/runtime behavior: [trinity_core/README.md](./trinity_core/README.md)
- tool/provider behavior: backend silo READMEs

If you cannot say which silo owns the change, the change is probably crossing an architectural boundary and should be reduced before implementation.

## Testing
Authoritative repo-level checks:
- `pytest trinity_core/tests -q` - Core execution runtime and tool-contract coverage
- `pytest unified-app/tests -q` - desktop handoff, UI orchestration boundaries, and integration coverage
- `pytest api-accessibility-poc/tests -q` - desktop automation support/runtime coverage
- `pytest browser-gui-automation/tests -q` - browser tool and support/runtime coverage
- `pytest cli-automation-poc/tests -q` - CLI tool and support/runtime coverage

Use targeted live checks only when the change actually touches a live runtime surface.

## Known Architectural Boundaries
- `unified-app/` owns user interaction, objective generation, confirmation, and target selection.
- `trinity_core/` owns execution orchestration, tool usage, retries, and verification.
- Backend silos own tool primitives and support runtimes, not the global execution loop.
- `audit-debugger/` and `scripts/` support the product but do not define product architecture.

## Legacy / Compatibility Debt
The codebase is cleaner than before, but it still contains support-heavy and compatibility-heavy areas:
- backend wrapper services still exist for some silos
- `unified-app/mcp_server/` contains desktop-side control and session utilities, not the main runtime path
- `puppeteer-mcp-wrapper/` is an alternate strategy surface, not the default browser path

Those areas should be documented honestly and extended cautiously.

## Common Failure Modes
- Missing `OPENAI_API_KEY`
  - Symptom: Core health checks fail or desktop reports Core unavailable
  - First check: confirm `unified-app/.env` or shell env contains a valid key
- Missing `GEMINI_API_KEY`
  - Symptom: objective generation or support wrappers fail before execution
  - First check: confirm desktop-side provider configuration
- Wrong silo edit
  - Symptom: duplicated orchestration or new hidden routing path
  - First check: verify the change belongs to desktop, Core, or a tool provider before coding

## Terminology

Use these terms consistently across code, docs, prompts, and any AI-generated output:

| Concept | Correct term | Banned terms |
|---|---|---|
| The top-level goal given to the executor | **objective** | task goal, prompt goal, command |
| A discrete piece of the objective the executor must achieve | **sub-objective** | step, step item, action item, subtask |
| A single LLM request-response cycle | **turn** | iteration, round, step, response cycle |

Rules:
- Never use "steps" or "step list" to describe what the executor should do. Use "sub-objectives".
- Never use "iteration" or "round" for an LLM exchange. Use "turn".
- Code field names follow the same convention where possible (`objective_steps` is legacy; prefer `sub_objectives` in new fields).

## Change Rules
- Do not reintroduce desktop-side execution loops.
- Do not move domain selection back into Core.
- Do not let tool-provider silos grow hidden mini-agent behavior.
- Prefer deleting compatibility layers over wrapping them again.
- Update the affected silo README when ownership or entrypoints change.

## Related Docs
- [unified-app/README.md](./unified-app/README.md)
- [trinity_core/README.md](./trinity_core/README.md)
- [api-accessibility-poc/README.md](./api-accessibility-poc/README.md)
- [browser-gui-automation/README.md](./browser-gui-automation/README.md)
- [cli-automation-poc/README.md](./cli-automation-poc/README.md)
- [audit-debugger/README.md](./audit-debugger/README.md)
