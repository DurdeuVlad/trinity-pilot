# Real Tests

These tests hit live infrastructure. They are **not run in CI by default**.

## Requirements

| Test | Requires |
|------|---------|
| `test_browser_real.py` | Playwright + Chromium installed (`playwright install chromium`), network access |
| `test_terminal_real.py` | `echo` command available (any OS) |
| `test_planner_real.py` | `GEMINI_API_KEY` env var set, network access |
| `test_live_e2e_audit.py` | Windows interactive desktop, `GEMINI_API_KEY`, `pywinauto`, `pywin32`, writable `.audit-runs`; `pyautogui` is fallback-only |

## Running

```bash
# Run all real tests
uv run pytest tests/real/ -v --real

# Run one file
uv run pytest tests/real/test_terminal_real.py -v --real

# Run with API key inline
GEMINI_API_KEY=your-key uv run pytest tests/real/test_planner_real.py -v --real

# Run live audit. Missing prerequisites create a skipped JSON/Markdown flight record before pytest skips.
uv run pytest tests/real/test_live_e2e_audit.py -m real -s
```

## Skipping behaviour

Without `--real`, all tests in this folder are skipped automatically.
These legacy real-model tests target Gemini directly; tests with a missing `GEMINI_API_KEY` skip themselves with an explanation. The main application and e2e fixtures support both configured providers.
Live audit tests are the exception: they run their prerequisite probe first, write a skipped flight record under `.audit-runs/`, then call `pytest.skip` with the collected missing prerequisite codes.
If `pywinauto` is available but `pyautogui` is broken, the live audit uses the pywinauto keyboard/UIA path and records `pyautogui_unavailable` as a warning, not a skip reason.
