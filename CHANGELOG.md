# Changelog

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
