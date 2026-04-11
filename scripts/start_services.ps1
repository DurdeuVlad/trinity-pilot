# Trinity-Pilot Module Services Startup Script
# Starts all three module services in separate PowerShell windows

Write-Host "Starting Trinity-Pilot Module Services..." -ForegroundColor Cyan

# Get the repo root (this script lives in scripts/ subdirectory)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

# Check if .env file exists
$envFile = Join-Path $repoRoot "unified-app\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "ERROR: .env file not found at $envFile" -ForegroundColor Red
    Write-Host "Please create unified-app/.env with GEMINI_API_KEY" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Found .env file" -ForegroundColor Green

# Start Browser Service (Port 8103)
Write-Host "`nStarting Browser Module Service (Port 8103)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$repoRoot\browser-gui-automation'; python browser_module_service.py"

# Wait a bit
Start-Sleep -Seconds 2

# Start Desktop Service (Port 8101)
Write-Host "Starting Desktop Module Service (Port 8101)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$repoRoot\api-accessibility-poc'; python desktop_module_service.py"

# Wait a bit
Start-Sleep -Seconds 2

# Start CLI Service (Port 8102)
Write-Host "Starting CLI Module Service (Port 8102)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$repoRoot\cli-automation-poc'; python cli_module_service.py"

Write-Host "`n✅ All services started!" -ForegroundColor Green
Write-Host "`nService URLs:" -ForegroundColor Cyan
Write-Host "  Browser: http://127.0.0.1:8103/health" -ForegroundColor White
Write-Host "  Desktop: http://127.0.0.1:8101/health" -ForegroundColor White
Write-Host "  CLI:     http://127.0.0.1:8102/health" -ForegroundColor White

Write-Host "`nWait 5-10 seconds for services to initialize, then test health endpoints." -ForegroundColor Yellow
Write-Host "Press Ctrl+C in each service window to stop." -ForegroundColor Gray
