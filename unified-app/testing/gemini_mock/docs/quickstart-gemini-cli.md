# Gemini Mock Quickstart: Gemini CLI

Use this when you only have a pipe-capable CLI and want to answer Gemini prompts yourself.

## Steps

1. Set `GEMINI_MOCK=stdio`.
2. Run a responder loop such as `while IFS= read -r line; do echo '{"steps":["open calculator"],"estimated_duration":10,"confidence":0.9}'; done`, where each input line is NDJSON like `{"prompt":"...","model":"...","mime_type":"..."}`.
3. Verify with `PYTHONPATH=. pytest unified-app/tests/ -q` for deterministic coverage or run the target app in stdio mode and confirm no real Gemini key is required.

See [backends-reference.md](backends-reference.md) for the exact protocol and alternative backends.
