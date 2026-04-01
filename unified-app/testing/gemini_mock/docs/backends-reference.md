# Gemini Mock Backends Reference

## Backends

| Backend | Env | Use Case |
|---|---|---|
| `QueueBackend` | `GEMINI_MOCK=1` or `queue` | Deterministic pytest runs and scripted responses |
| `StdioBackend` | `GEMINI_MOCK=stdio` | Pipe-driven CLI agents and shell responders |
| `HttpBackend` | `GEMINI_MOCK=http` | Live app control from another terminal |
| `LLMBackend` | `GEMINI_MOCK=llm` | Autonomous responses via Anthropic, OpenAI, or Ollama |

## Environment Variables

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_MOCK` | unset | Mock mode: `1`, `queue`, `stdio`, `http`, `llm` |
| `GEMINI_MOCK_SERVER_URL` | `http://localhost:8765` | Control server URL for `HttpBackend` |
| `GEMINI_MOCK_LLM_PROVIDER` | `anthropic` | Provider for `LLMBackend`: `anthropic`, `openai`, `ollama` |
| `ANTHROPIC_API_KEY` | unset | Required for `LLMBackend` with Anthropic |
| `OPENAI_API_KEY` | unset | Required for `LLMBackend` with OpenAI |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama base URL for `LLMBackend` |

## Verification Commands

```bash
PYTHONPATH=. pytest unified-app/tests/ -q
PYTHONPATH=. python testing/gemini_mock/validate_cross_module.py
python -m testing.gemini_mock --help
```
