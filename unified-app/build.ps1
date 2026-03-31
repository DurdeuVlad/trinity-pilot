[CmdletBinding()]
param(
    [string]$Version = "0.0.0-dev",
    [switch]$Clean,
    [switch]$ValidateOnly,
    [string]$PythonExe = "python",
    [string]$BuildRootOverride = "",
    [string]$DistRootOverride = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-PathExists {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Label not found: $Path"
    }
}

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )

    Write-Host ">> $FilePath $($ArgumentList -join ' ')" -ForegroundColor Cyan
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw ("Command failed with exit code {0}: {1}" -f $LASTEXITCODE, $FilePath)
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = Resolve-NormalizedPath $ScriptDir
$RepoRoot = Resolve-NormalizedPath (Join-Path $AppRoot "..")
$SpecPath = Join-Path $AppRoot "unified-app.spec"
$MainPath = Join-Path $AppRoot "main.py"
$BuildRoot = if ($BuildRootOverride) {
    Resolve-NormalizedPath $BuildRootOverride
} else {
    Join-Path $AppRoot "build"
}
$DistRoot = if ($DistRootOverride) {
    Resolve-NormalizedPath $DistRootOverride
} else {
    Join-Path $AppRoot "dist"
}
$ConfigTemplateSources = @(
    (Join-Path $RepoRoot "cli-automation-poc\.env.example"),
    (Join-Path $RepoRoot "browser-gui-automation\.env.example")
)

Assert-PathExists -Path $SpecPath -Label "PyInstaller spec"
Assert-PathExists -Path $MainPath -Label "App entrypoint"
foreach ($TemplatePath in $ConfigTemplateSources) {
    Assert-PathExists -Path $TemplatePath -Label "Config template source"
}

$ReleaseName = "UnifiedApp-$Version"
$ReleaseDir = Join-Path $DistRoot $ReleaseName
$MetadataDir = Join-Path $ReleaseDir "metadata"
$ConfigDir = Join-Path $ReleaseDir "config"
$BuildInfoPath = Join-Path $MetadataDir "build-info.json"
$VersionPath = Join-Path $MetadataDir "version.txt"
$SmokeTestPath = Join-Path $MetadataDir "SMOKE_TEST.txt"
$MergedTemplatePath = Join-Path $ConfigDir ".env.example"
$EntrypointPath = Join-Path $ReleaseDir "OrchestratorDesktopApp.exe"

if ($Clean) {
    Write-Host "Cleaning build outputs under $AppRoot" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $BuildRoot, $DistRoot -ErrorAction SilentlyContinue
}

$env:UNIFIED_APP_VERSION = $Version
$env:UNIFIED_APP_DIST_NAME = $ReleaseName

Write-Host "Packaging repo root: $RepoRoot"
Write-Host "Packaging app root:  $AppRoot"
Write-Host "Packaging version:   $Version"
Write-Host "Build root:          $BuildRoot"
Write-Host "Dist root:           $DistRoot"
Write-Host "Release folder:      $ReleaseDir"

if ($ValidateOnly) {
    Write-Host "Validation succeeded. Build inputs and template sources are present." -ForegroundColor Green
    return
}

New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null

Push-Location $AppRoot
try {
    Invoke-CheckedProcess -FilePath $PythonExe -ArgumentList @(
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        $DistRoot,
        "--workpath",
        $BuildRoot,
        $SpecPath
    )
}
finally {
    Pop-Location
}

Assert-PathExists -Path $ReleaseDir -Label "PyInstaller release output"

New-Item -ItemType Directory -Force -Path $MetadataDir, $ConfigDir | Out-Null

$MergedTemplate = @(
    "# Unified App internal release configuration",
    "# Copy this file to %LOCALAPPDATA%\UnifiedApp\config\.env and set real values before launch.",
    "GEMINI_API_KEY=",
    "",
    "# Optional browser backend configuration",
    "BROWSER_WS_URL=ws://127.0.0.1:9222/devtools/browser/<id>",
    "",
    "# Optional CLI backend tuning",
    "CLI_BACKEND_NAME=cli-automation-poc",
    "MAX_COMMAND_TIMEOUT=120",
    "MAX_ACTION_RETRIES=3",
    "LOG_LEVEL=INFO"
)
[System.IO.File]::WriteAllLines($MergedTemplatePath, $MergedTemplate)

$BuildInfo = [ordered]@{
    version = $Version
    release_name = $ReleaseName
    built_at_utc = [DateTime]::UtcNow.ToString("o")
    python_exe = $PythonExe
    spec_path = $SpecPath
    app_root = $AppRoot
    repo_root = $RepoRoot
    config_template_sources = $ConfigTemplateSources
}
$BuildInfo | ConvertTo-Json -Depth 4 | Set-Content -Path $BuildInfoPath -Encoding UTF8
Set-Content -Path $VersionPath -Encoding UTF8 -Value $Version

$SmokeTest = @(
    "1. Copy config\.env.example to %LOCALAPPDATA%\UnifiedApp\config\.env and set GEMINI_API_KEY.",
    "2. Launch OrchestratorDesktopApp.exe from this release folder.",
    "3. Confirm the app starts without repo-root PYTHONPATH or sibling source folders.",
    "4. In the Run tab, verify live startup reports Gemini readiness before task submission.",
    "5. Exercise one CLI task, one browser task, and one desktop task on the target machine."
)
[System.IO.File]::WriteAllLines($SmokeTestPath, $SmokeTest)

Assert-PathExists -Path $EntrypointPath -Label "Packaged entrypoint"
Assert-PathExists -Path $MergedTemplatePath -Label "Generated config template"

Write-Host "Build finished. Release folder: $ReleaseDir" -ForegroundColor Green
Write-Host "Executable: $EntrypointPath" -ForegroundColor Green
Write-Host "Config template: $MergedTemplatePath" -ForegroundColor Green
