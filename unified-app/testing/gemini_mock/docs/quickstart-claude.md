# Gemini Mock Quickstart: Claude CLI

Use this when Claude should answer Gemini prompts without spending Gemini credits.

## Steps

1. Set `GEMINI_MOCK=llm` and `GEMINI_MOCK_LLM_PROVIDER=anthropic`.
2. Run `PYTHONPATH=. pytest unified-app/tests/ -q` for tests, or `GEMINI_MOCK=llm GEMINI_MOCK_LLM_PROVIDER=anthropic python unified-app/main.py` for live app work.
3. Verify `41 passed` for the test suite or inspect live prompts with `python -m testing.gemini_mock calls` when using HTTP mode.

See [backends-reference.md](backends-reference.md) for all env vars and backend tradeoffs.
