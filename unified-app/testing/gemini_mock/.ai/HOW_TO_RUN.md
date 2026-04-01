# How to Run: testing/gemini_mock

## Common Modes

- Deterministic tests: `GEMINI_MOCK=1 PYTHONPATH=. pytest unified-app/tests/ -q`
- Live app control: `python -m testing.gemini_mock --port 8765 serve` then `GEMINI_MOCK=http python unified-app/main.py`
- Autonomous provider responses: `GEMINI_MOCK=llm GEMINI_MOCK_LLM_PROVIDER=anthropic python unified-app/main.py`

## Quickstarts

- Claude CLI: `testing/gemini_mock/docs/quickstart-claude.md`
- Codex: `testing/gemini_mock/docs/quickstart-codex.md`
- Copilot: `testing/gemini_mock/docs/quickstart-copilot.md`
- Gemini CLI: `testing/gemini_mock/docs/quickstart-gemini-cli.md`

## Reference

See `testing/gemini_mock/docs/backends-reference.md` for all backend modes and env vars.
