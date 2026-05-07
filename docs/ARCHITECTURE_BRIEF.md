# Trinity Pilot — Architecture Brief

**Status:** Research complete. Architecture decided. Ready for Flux implementation.

---

## What This Project Is

Trinity Pilot is a Python desktop application that automates real PC tasks using LLM orchestration. The user describes a task in natural language; the app decomposes it into typed objectives, executes them using the right backend (browser, terminal, or desktop GUI), reviews results, and retries on failure.

Target users: developers and power users on Windows (cross-platform stretch goal).

---

## Why We're Starting From Scratch

The previous codebase accumulated too much technical noise, over-engineering, and broken scaffolding. Clean slate. The research is done — do not re-research. Go straight to architecture planning.

---

## Architecture Decision (Final — Do Not Re-Debate)

**Winner: Durable supervisor + graph inner loop + explicit typed handoffs**

| Layer | Decision |
|-------|----------|
| Desktop shell | PySide6 (Qt for Python) + QtAsyncio |
| Control plane | Temporal Python SDK (1 workflow = 1 user task) |
| Inner planner | ObjectiveSpec DAG (typed, not prose) |
| Capability boundary | FastMCP servers (MCP at boundary, direct calls in hot path) |
| Browser domain | Playwright Python — headful Chromium, dedicated profile |
| Terminal/code domain | SWE-agent-style ACI — PTY-backed, structured commands, not raw shell |
| Desktop-app domain | pywinauto UIA backend → AXUIElement (macOS) → AT-SPI (Linux) → screenshot fallback (degraded mode) |
| Memory/evidence | SQLite — WAL mode, JSON columns, FTS5 |
| Testing | unit + integration + real (MCP server controls live app) |

---

## Non-Negotiables

1. **Discovery is separate from execution.** Never mix planning and tool calls in the same agent pass.

2. **ObjectiveSpec must be fully typed** — refuse execution if any field missing:
   - `objective_id`, `goal`, `dependencies`, `domain`, `required_capabilities`
   - `risk_class`, `preconditions`, `success_tests`, `evidence_bundle`
   - `max_attempts`, `rollback_or_abort_rule`

3. **Workers are disposable.** One worker per objective. Kill after completion or failure.

4. **Reviewer is a separate agent** with read-mostly tools and a typed failure reason system: `missing_artifact | failed_assertion | ui_state_mismatch | wrong_output | environment_divergence`

5. **Retries live in Temporal** (workflow layer), not in LLM prompts. Max 3 attempts per objective.

6. **Three kill paths:** in-app stop button, global hotkey, PyAutoGUI pointer fail-safe.

7. **MCP at the boundary, direct calls in hot path.** Do not force everything through MCP.

---

## Test Coverage Requirements

- **Unit:** fully isolated, no external deps, no LLM calls
- **Integration:** mocked infra (fake Temporal, fake MCP servers, fake DB)
- **Real:** MCP server controls the live running app — drive UI, assert state, verify end-to-end

---

## Research Sources

Full research document with paper citations and architecture analysis:
`E:\Downloads\deep-research-report (4).md`

Prior art PDFs (desktop automation research):
- `docs/research/2406.01014-mobileagent-v2.pdf`
- `docs/research/2410.08164-agent-s.pdf`
- `docs/research/2502.14282-pc-agent.pdf`
- `docs/research/2504.14603-ufo2.pdf`
- `docs/research/2507.22358-magentic-ui.pdf`
- `docs/research/2511.11332-ufo3.pdf`

Validation playbooks (what real tests must cover):
- `docs/validation-playbooks/browser-validation.md`
- `docs/validation-playbooks/cli-validation.md`
- `docs/validation-playbooks/desktop-validation.md`

---

## Starting Instruction for Fresh Claude Session

1. Read this brief fully
2. Read `docs/research/` PDFs for prior art context (optional but recommended)
3. Paste the requirements file from the user (they have it as a separate .md)
4. Run `/flux-plan` to produce the full architecture plan
5. Then `/flux-build` story by story
6. Tests: unit first, integration second, real (MCP-controlled) third

**Do not run `/flux-discovery` or `/flux-explore` — research and direction are already decided.**
