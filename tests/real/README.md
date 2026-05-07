# Real Tests

These tests hit live infrastructure. They are **not run in CI by default**.

## Requirements

| Test | Requires |
|------|---------|
| `test_browser_real.py` | Playwright + Chromium installed (`playwright install chromium`), network access |
| `test_terminal_real.py` | `echo` command available (any OS) |
| `test_planner_real.py` | `GEMINI_API_KEY` env var set, network access |

## Running

```bash
# Run all real tests
uv run pytest tests/real/ -v --real

# Run one file
uv run pytest tests/real/test_terminal_real.py -v --real

# Run with API key inline
GEMINI_API_KEY=your-key uv run pytest tests/real/test_planner_real.py -v --real
```

## Skipping behaviour

Without `--real`, all tests in this folder are skipped automatically.
Tests with missing env vars (`GEMINI_API_KEY`) skip themselves with an explanation.
