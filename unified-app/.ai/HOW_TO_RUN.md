# How to Run: unified-app

## Prerequisites

- Python 3.10+
- Dependencies from `requirements.txt`
- Optional live Gemini key: `GEMINI_API_KEY`

## Startup Modes

The app decides startup mode before the first task runs:

- `live` mode: used when `GEMINI_MOCK` is unset. Startup loads `.env` if present, then runs a bounded readiness probe for both Gemini caller paths.
- `mock` mode: used when `GEMINI_MOCK` is set. Startup activates `testing.gemini_mock` and skips live Gemini readiness probes.

Shell environment variables take precedence over values loaded from `.env`.

## Live Mode

```powershell
cd unified-app
pip install -r requirements.txt

"GEMINI_API_KEY=your_real_key" | Out-File -Encoding ascii .env

$env:PYTHONPATH='..'
python main.py
```

Expected result:

- The window opens.
- The Task Input panel shows `Startup mode: live Gemini ready (...)`.
- Task submission remains enabled.

If live mode is blocked:

- The Task Input panel shows a startup warning that explains the failure.
- The Run button remains disabled for new submissions.
- Switch to mock mode for the demo instead of retrying inside the UI.

Recommended live smoke task:

- Objective: `list files in current directory`
- Domain: `cli`
- Success rule: the task reaches a terminal state within 60 seconds and the UI shows either a completed run or a clean actionable failure

## Mock Mode

```powershell
cd unified-app
pip install -r requirements.txt

$env:PYTHONPATH='..'
$env:GEMINI_MOCK='1'
$env:GEMINI_API_KEY='mock'
python main.py
```

Expected result:

- The window opens.
- The Task Input panel shows `Startup mode: mock fallback active.`
- Task submission is enabled without real Gemini credentials.

## 30-Second Demo Decision

Use live mode only if all three checks pass:

1. Startup status says `live Gemini ready`.
2. The CLI smoke task is the first demo task you run.
3. The smoke task reaches a terminal state quickly and without auth/quota warnings.

Switch to mock mode immediately if any of these happen:

1. Startup says live mode is blocked.
2. The smoke task shows auth, quota, network, or malformed-response guidance.
3. The smoke task is still not in a terminal state after 60 seconds.

## Notes

- `.env` loading is non-destructive: existing shell env vars are not overwritten.
- The app creates a local SQLite database at `_runtime/orchestrator.db` on first run.

## Building a Standalone Executable

```powershell
python scripts/build.ps1
```

Or:

```powershell
pyinstaller orchestrator.spec
```

## Configuration

| Env var | Required | Description |
|---------|----------|-------------|
| `GEMINI_API_KEY` | Live mode only | Gemini API key used by both live planner paths |
| `GEMINI_MOCK` | Mock mode only | Any non-empty value enables runtime Gemini mock activation |
