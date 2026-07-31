# Contributing

Thanks for helping improve Trinity Pilot. It is early-stage desktop automation software; correctness and clear safety boundaries matter more than clever demos.

## Before opening a pull request

1. Discuss substantial changes in an issue first.
2. Keep each pull request focused and include tests for changed behavior.
3. Do not commit API keys, `.env` files, databases, screenshots containing private data, or generated runtime artifacts.
4. Update user-facing docs when behavior, permissions, or data flow changes.

## Local checks

```bash
uv sync --locked --extra dev --extra windows
uv run ruff check .
uv run mypy trinity_pilot
uv run pytest tests/unit tests/integration -v
```

Run the GUI, desktop, and real-model suites only in a controlled Windows environment. They may open applications, use a real desktop, access the network, and require `GEMINI_API_KEY`.

## Pull-request expectations

Explain the problem, approach, tests run, and any residual risk. Avoid unrelated formatting changes. By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE).
