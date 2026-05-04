# Changelog

## 2026-05-04 — context-window-loop

- feat: `Session.get_context_window(max_messages=20)` — failure-pinned sliding window. Error tool results always pinned, non-failures pruned by recency.
- fix: executor LLM call now uses `get_context_window()` — LLM no longer loses failure history as sessions grow past context limits.
- test: 8 unit tests for window truncation, failure pinning, and edge cases.
