# Trinity Pilot — Architecture Brief

## What This Project Is

Trinity Pilot is a Python desktop application that automates real PC tasks using LLM orchestration. The user describes a task in natural language; the app decomposes it into typed objectives, executes them using the right backend (browser, terminal, or desktop GUI), reviews results, and retries on failure.

Target platform: Windows. Cross-platform is a stretch goal.

---

## Architecture

**Durable supervisor + typed objective DAG + explicit domain handoffs**

| Layer | Choice |
|-------|--------|
| Desktop shell | PySide6 (Qt for Python) + QtAsyncio |
| Inner planner | ObjectiveSpec DAG (typed, not prose) |
| Capability boundary | FastMCP servers (MCP at boundary, direct calls in hot path) |
| Browser domain | Playwright Python — headful Chromium, dedicated profile |
| Terminal domain | PTY-backed subprocess, structured commands |
| Desktop-app domain | pywinauto UIA backend → PyAutoGUI screenshot fallback (degraded mode) |
| Memory/evidence | SQLite — WAL mode, JSON columns |
| Testing | unit + integration + real (MCP server controls live app) |

---

## Design Constraints

1. **Planning separate from execution.** No tool calls during the planning pass.

2. **ObjectiveSpec must be fully typed** before execution — any missing field is rejected:
   - `objective_id`, `goal`, `dependencies`, `domain`, `required_capabilities`
   - `risk_class`, `preconditions`, `success_tests`, `evidence_bundle`
   - `max_attempts`, `rollback_or_abort_rule`

3. **Workers are disposable.** One worker per objective, killed after completion or failure.

4. **Reviewer is a separate agent** with read-mostly tools and a typed failure reason:
   `missing_artifact | failed_assertion | ui_state_mismatch | wrong_output | environment_divergence`

5. **Three kill paths:** in-app stop button, global hotkey, PyAutoGUI pointer fail-safe.

6. **MCP at the boundary, direct calls in hot path.**

---

## Test Coverage

- **Unit:** fully isolated, no external deps, no LLM calls
- **Integration:** mocked LLM provider, real DB, full planner→orchestrator→reviewer chain
- **Real/E2E:** MCP server controls the live running app — submit prompt, assert side effects on disk

---

## Prior Art

Research PDFs in `docs/research/`:
- `2406.01014-mobileagent-v2.pdf`
- `2410.08164-agent-s.pdf`
- `2502.14282-pc-agent.pdf`
- `2504.14603-ufo2.pdf`
- `2507.22358-magentic-ui.pdf`
- `2511.11332-ufo3.pdf`
