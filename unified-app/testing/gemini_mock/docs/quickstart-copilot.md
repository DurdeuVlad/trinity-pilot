# Gemini Mock Quickstart: Copilot

Use this from the VS Code terminal when you want reproducible tests or a live queue-driven app session.

## Steps

1. In Terminal 1, run `python -m testing.gemini_mock --port 8765 serve` for live control, or set `GEMINI_MOCK=1` for deterministic tests.
2. In Terminal 2, run `PYTHONPATH=. pytest unified-app/tests/ -q` or launch the app with `GEMINI_MOCK=http python unified-app/main.py`.
3. In Terminal 3, queue responses with `python -m testing.gemini_mock --port 8765 push '{"steps":["x"],"estimated_duration":5,"confidence":0.8}'` and verify with `python -m testing.gemini_mock --port 8765 status`.

See [backends-reference.md](backends-reference.md) for the full HTTP workflow and env vars.
