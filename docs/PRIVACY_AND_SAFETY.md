# Privacy and safety

Trinity Pilot is a local Windows desktop automation application, not a sandbox or a security boundary.

## Data flow

The application sends task-planning and worker/reviewer prompts, including task text and relevant execution evidence, to the configured LLM provider. The shipped example selects OpenAI; Gemini remains supported as an alternative. Browser content, screenshots, terminal output, desktop UI text, file paths, and other evidence can therefore be included in model requests when relevant to a task. The exact provider-side retention and processing terms are governed by the provider and account configuration, not by this repository.

Locally, the application stores SQLite task state and evidence at `DB_PATH` (default when unset: `~/.trinity-pilot/trinity_pilot.db`), may write NDJSON traces when `TRINITY_TRACE=1`, and writes crash reports under `crashes/`. These files can contain task text, paths, command output, screenshots or error details. Keep them out of source control and protect or delete them according to your own retention requirements.

The project does not claim to provide encrypted storage, tenant isolation, a data-loss-prevention layer, or a guarantee that sensitive content will not reach a configured model provider.

## Authority and risk

- Browser automation can navigate to sites and submit data.
- Desktop automation can interact with visible Windows applications.
- Terminal automation executes local PowerShell commands as the launching user. It is **not sandboxed** and may affect any resource that user can access.

Model output, web pages, and documents can contain malicious or misleading instructions. Review tasks and results, use a dedicated low-privilege Windows account or VM for experimentation, keep backups, and never provide secrets or production access unless the task genuinely requires it.

## Operating guidance

Use `.env` for the selected provider key (`OPENAI_API_KEY` or `GEMINI_API_KEY`); never commit it. Set `DB_PATH` to a controlled location when the default app-data path is unsuitable. Before sharing logs, screenshots, crash reports, or databases, inspect them for credentials and personal or proprietary data. Stop the app and revoke credentials if you suspect unintended execution or exposure.
