# Changelog

## 2026-05-06 - live-domain-reliability-audit

- test: expanded GUI smoke to drive the unified app through prompt, plan, Run, result, and artifact verification across CLI, web, desktop, and mixed prompts.
- test: made the live domain runner default to the nine canonical scenarios and moved the extra three-domain chain behind `--include-extra`.
- test: deleted stale api-accessibility-poc tests for removed generic backend/planner/orchestrator modules and added same-repo import isolation.
- fix: split Core live desktop smoke from fast Core tests and fixed fast tests that were still touching real UIA or stale tool counts.
- docs: recorded the current live result: 5/9 pass, with zero-tool-call failures in CLI easy, desktop easy/moderate, and cross-domain complex.

## 2026-05-06 - architecture-truth-cleanup

- docs: added root architecture truth and ledger so current product flow, test authority, and dead surfaces are explicit.
- test: deleted archived legacy unified-app tests instead of preserving a stale quarantine.
- chore: removed generated root runtime captures and obsolete prompt-history documentation.

## 2026-05-06 - test-architecture-smoke-cleanup

- test: quarantined stale unified-app tests for removed architecture from active collection.
- test: added a GUI-driven user-flow smoke test for prompt -> plan -> Run -> result wiring.
- fix: aligned mixed-domain handoff tests with current Core-routing behavior.

## 2026-05-04 — context-window-loop

- feat: `Session.get_context_window(max_messages=20)` — failure-pinned sliding window. Error tool results always pinned, non-failures pruned by recency.
- fix: executor LLM call now uses `get_context_window()` — LLM no longer loses failure history as sessions grow past context limits.
- test: 8 unit tests for window truncation, failure pinning, and edge cases.
