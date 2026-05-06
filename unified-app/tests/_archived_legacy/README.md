# Archived Legacy Tests

These tests are intentionally outside active pytest collection.

They target removed or non-authoritative unified-app surfaces such as:
- `mcp_server`
- `ui.panels`
- `ui.overlay`
- `orchestrator.macro_planner`
- `orchestrator.objectives_decomposer`
- `orchestrator.service_manager`
- removed startup preflight APIs
- removed event-bus compatibility helpers

They were quarantined because they failed import-time collection and blocked
the active test suite from proving the current product architecture.

Do not re-enable these files wholesale. Salvage individual assertions only if
the target behavior still exists in the current user flow:

`ChatPanel prompt -> generated sub-objectives -> PlanPanel Run -> executor -> result`
