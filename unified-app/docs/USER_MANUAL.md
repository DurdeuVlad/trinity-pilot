# Orchestrator Desktop App - User Manual

## Installation

1. Install Python 3.10+.
2. Install dependencies:
```powershell
pip install -r requirements.txt
```
3. Launch:
```powershell
python main.py
```

## First Run

1. Open the `Settings` tab.
2. Set Gemini API key if you want cloud planning.
3. Keep defaults for timeout and retries.
4. Return to `Run` tab and submit a task.

## Running Tasks

1. Enter a task description in natural language.
2. Keep domain on `Auto-detect` unless you need explicit routing.
3. Click `Run Task`.
4. Review:
- execution plan
- real-time status log
- glass box screenshots

## History

- Open `History` tab to inspect prior runs.
- Use search to filter tasks.
- Double-click a row to capture task id through emitted signal integration.

## Settings

- API key, timeout, retries, domain defaults, frame limits.
- Click `Save Settings` to persist.

## Troubleshooting

- Missing API key: planner falls back to deterministic local planning.
- No screenshots: verify backends are writing to `_runtime/screenshots`.
- Task failures: inspect status log and history entry details.
