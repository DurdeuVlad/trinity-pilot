# Unified App Packaging Build

This is the canonical Windows packaging entrypoint for the internal one-folder release.

## Scope

The build packages:

- `unified-app`
- `trinity_core`
- `cli-automation-poc`
- `browser-gui-automation`
- `api-accessibility-poc`

The produced artifact is a PyInstaller one-folder bundle under `unified-app/dist/`.

## Preconditions

- Windows PowerShell
- Python environment with `unified-app/requirements.txt` installed
- The sibling backend folders present in the same repo checkout
- Config template sources present:
  - `cli-automation-poc/.env.example`
  - `browser-gui-automation/.env.example`

The script resolves paths from its own location, so it can be launched from any working directory. It does not rely on running from repo root.
If the canonical `unified-app/build` or `unified-app/dist` trees are locked by the environment, you can override them explicitly for the current run.

## Validate Inputs

Use this first to confirm the spec, entrypoint, and config-template inputs exist:

```powershell
powershell -ExecutionPolicy Bypass -File .\unified-app\build.ps1 -Version 0.1.0-internal -ValidateOnly
```

## Build

Clean build:

```powershell
powershell -ExecutionPolicy Bypass -File .\unified-app\build.ps1 -Version 0.1.0-internal -Clean
```

Incremental build:

```powershell
powershell -ExecutionPolicy Bypass -File .\unified-app\build.ps1 -Version 0.1.0-internal
```

If `python` is not on PATH, pass an explicit interpreter:

```powershell
powershell -ExecutionPolicy Bypass -File .\unified-app\build.ps1 -Version 0.1.0-internal -PythonExe C:\path\to\python.exe
```

If you need to stage the PyInstaller work/output directories somewhere else:

```powershell
powershell -ExecutionPolicy Bypass -File .\unified-app\build.ps1 -Version 0.1.0-internal -BuildRootOverride .\.tmp\packaging\build -DistRootOverride .\.tmp\packaging\dist
```

## Output

The build creates `unified-app/dist/UnifiedApp-<version>/` with:

- `OrchestratorDesktopApp.exe`
- bundled Python/runtime files from PyInstaller
- `config/.env.example`
- `metadata/version.txt`
- `metadata/build-info.json`
- `metadata/SMOKE_TEST.txt`

The build script verifies that both `OrchestratorDesktopApp.exe` and `config/.env.example` exist before it reports success.

## Notes

- The PyInstaller spec is `unified-app/unified-app.spec`.
- The packaged bundle excludes `testing.gemini_mock`.
- The config template is generated for the release from validated backend template inputs so the release always includes an operator-facing `.env.example`.
