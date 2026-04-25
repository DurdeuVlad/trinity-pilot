Status: Active
Owns: Visible tool primitives exposed to Core-visible runtimes and MCP toolsets.
Does Not Own: High-level planning, user interaction, or hidden mini-agent behavior.

# Trinity Core Tools

## What This Is
`trinity_core/tools/` is the primitive tool layer used by Trinity Core. These tools are the visible building blocks that the Core runtime calls through MCP tool catalogs.

This folder should stay simple and explicit.

## Responsibility
- Owns:
  - domain-specific primitive tool implementations
  - shared tool base abstractions
  - visible tool contracts used by Core runtimes
- Does Not Own:
  - user clarification
  - execution planning
  - hidden retries, self-directed agents, or shadow orchestration

## How It Fits The Product
Active flow:

`Desktop -> Trinity Core -> visible tools in this folder -> real desktop/browser/CLI effects`

These tools are downstream of the Core runtime and upstream of the actual environment they act on.

## Folder Map
- `base.py` - common tool abstractions
- `browser_tools.py` - browser tool primitives
- `cli_tools.py` - CLI tool primitives
- `desktop_tools.py` - desktop automation primitives

## Entry Points
There is no end-user entrypoint here.

This folder is exercised through:
- Core runtime execution
- `toolset_mcp_server.py`
- `pytest ../tests -q`

## Contracts
Every tool in this folder should be:
- visible in the tool catalog
- narrow in scope
- explicit about inputs and outputs
- free of hidden planning behavior

If a tool needs multiple logical steps, keep them transparent rather than hiding orchestration inside the tool.

## Configuration
Tool prerequisites depend on domain:
- browser tools need browser/runtime prerequisites
- desktop tools need Windows/UIA prerequisites
- CLI tools need shell/process prerequisites

Core runtime configuration still governs when and how these tools are called.

## Development Workflow
When editing tools:
1. keep the behavior primitive
2. keep inputs/outputs explicit
3. validate through Core tests
4. avoid adding policy or user-facing logic

If you want to add planning, retries, or clarification here, stop. That belongs elsewhere.

## Testing
Primary validation:
- `pytest ../tests -q`

Use target-specific live checks only when changing tool behavior that cannot be trusted without a real environment.

## Known Architectural Boundaries
- Desktop owns clarification and target selection.
- Core owns the execution loop.
- This folder owns only the tool primitives Core can call.

## Common Failure Modes
- Tool side effects are too broad
  - Symptom: one tool quietly performs multiple opaque operations
  - First check: split the tool into explicit primitives
- Tool contract is ambiguous
  - Symptom: runtime or tests cannot tell what success means
  - First check: tighten result shape and evidence returned

## Change Rules
- Keep tools visible, primitive, and auditable.
- Do not hide mini-agent behavior here.
- Update this README if new domains or tool families are added.

## Related Docs
- [../README.md](../README.md)
- [../../unified-app/README.md](../../unified-app/README.md)
