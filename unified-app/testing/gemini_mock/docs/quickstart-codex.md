# Gemini Mock Quickstart: Codex

Use this when Codex needs deterministic tests or a local control loop instead of real Gemini calls.

## Steps

1. For deterministic tests, set `GEMINI_MOCK=1`; for live app control, start `python -m testing.gemini_mock --port 8765 serve` and set `GEMINI_MOCK=http`.
2. Run `PYTHONPATH=. pytest unified-app/tests/ -q` or `GEMINI_MOCK=http python unified-app/main.py`.
3. Verify with `PYTHONPATH=. python testing/gemini_mock/validate_cross_module.py` or inspect server state via `python -m testing.gemini_mock status`.

See [backends-reference.md](backends-reference.md) for backend selection details.
