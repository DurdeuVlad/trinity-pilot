# testing/gemini_mock Context

## Purpose

`testing/gemini_mock` intercepts `google.generativeai` imports and routes them to pluggable backends so repo modules can exercise Gemini-dependent paths without real Gemini API calls.

## Architecture

`mock_genai.py`
: Drop-in `google.generativeai` replacement with `GenerativeModel`, `MockResponse`, `GenerationConfig`, and `upload_file()`.

`activator.py`
: Injects the mock into `sys.modules`, preserves real `google.api_core` when present, and selects a backend from `GEMINI_MOCK`.

`backends/`
: `queue_backend.py` for scripted pytest responses, `stdio_backend.py` for pipe responders, `llm_backend.py` for Anthropic/OpenAI/Ollama.

`server.py`
: Stdlib HTTP control server plus `HttpBackend` for cross-process live app control.

`pytest_plugin.py`
: `gemini_mock` fixtures for test activation and teardown.

`cli.py` and `__main__.py`
: `python -m testing.gemini_mock serve|push|calls|status|reset`.

`validate_cross_module.py`
: Validates compatibility with `dom-based-web-agent-poc` and `poc-vision-and-click-module`.

## Key Paths

- Quickstarts: `testing/gemini_mock/docs/`
- Module docs: `testing/gemini_mock/.ai/`
- Focused tests: `testing/gemini_mock/tests/`
- Unified-app wiring: `unified-app/tests/conftest.py`
