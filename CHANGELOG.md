# CHANGELOG

## 2026-05-02 — desktop-llm-loop

- feat(desktop): `list_windows` and `get_focused_window` MCP tools — LLM can now inspect desktop state before acting
- feat(desktop): `was_existing` flag in `open_app` — disambiguates existing vs fresh windows to stop focus loops
- docs(desktop): OPEN_APP RULES + REORIENTATION instructions — explicit guidance for LLM when `was_existing: true`
- test: 9 unit tests for new tools and `was_existing` logic in `test_desktop_tools.py`

## 2026-05-02 — desktop-hang-fix

- fix(mcp): `asyncio.wait_for(timeout=30s)` on `call_tool()` — TaskQueue no longer starves when desktop MCP server subprocess hangs
- fix(mcp): `asyncio.wait_for(timeout=10s)` on `list_tools()`, `list_prompts()`, `list_resources()`
- test: 5 new tests for timeout behaviour and queue unblock in `trinity_core/tests/test_mcp_client_timeout.py`
- verified: desktop scenarios now fail cleanly in ~38s instead of hanging 120s; TIMEOUT count 0/9; no regressions on CLI/Web passing scenarios
