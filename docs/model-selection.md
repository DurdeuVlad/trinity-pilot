# Model Selection

## Current defaults

| Role | Default | Override env var |
|------|---------|-----------------|
| Planner | `gemini-2.5-flash` | `GEMINI_PLANNER_MODEL` |
| Worker (all domains) | `gemini-2.5-flash` | `GEMINI_WORKER_MODEL` |

## Why not gemini-2.0-flash

`gemini-2.0-flash` was the original default. Live testing on 2026-05-17 showed it is **unsuitable
for multi-step agentic tool calling**:

- After a single successful tool call, the model transitions into text-generation mode and stops
  calling tools entirely.
- The `"no tool called, continue."` nudge message in `agentic_mixin.run_loop` is insufficient to
  break this lock — the model repeated text-only responses for 14 consecutive steps until the step
  budget was exhausted.
- Root cause: Gemini 2.0 Flash has weak instruction-following in multi-turn function-calling
  conversations. It is optimised for single-turn generation, not ReAct loops.

**Do not use `gemini-2.0-flash` or `gemini-2.0-flash-lite` as a worker model.**

## Recommended models

| Model | Suitable for |
|-------|-------------|
| `gemini-2.5-flash` | Workers (all domains) — good tool-call reliability, fast |
| `gemini-2.5-flash` | Planner — sufficient for structured JSON output |
| `gemini-3.1-flash-lite` | Workers on budget — smarter than 2.0, still fast |
| `gemini-3.1-pro-preview` | Planner on hard tasks — best reasoning quality |

## Configuration example

```dotenv
GEMINI_API_KEY=your-key-here
GEMINI_PLANNER_MODEL=gemini-2.5-flash
GEMINI_WORKER_MODEL=gemini-2.5-flash
```

For maximum capability:

```dotenv
GEMINI_PLANNER_MODEL=gemini-3.1-pro-preview
GEMINI_WORKER_MODEL=gemini-3.1-flash-lite
```
