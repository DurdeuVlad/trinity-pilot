# Trinity-Pilot Module Services Startup Script
# Starts all services in separate PowerShell windows

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

# Start Ollama
Write-Host "`nStarting Ollama..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "ollama serve"
Start-Sleep -Seconds 3

# Start Browser Service (Port 8103)
Write-Host "`nStarting Browser Module Service (Port 8103)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$repoRoot\browser-gui-automation'; python browser_module_service.py"
Start-Sleep -Seconds 2

# Start Desktop Service (Port 8101)
Write-Host "Starting Desktop Module Service (Port 8101)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$repoRoot\api-accessibility-poc'; python desktop_module_service.py"
Start-Sleep -Seconds 2

# Start CLI Service (Port 8102)
Write-Host "Starting CLI Module Service (Port 8102)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$repoRoot\cli-automation-poc'; python cli_module_service.py"
Start-Sleep -Seconds 2

# Start Local LLM Service (Port 8104)
Write-Host "Starting Local LLM Service (Port 8104)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$repoRoot\local-llm-backend'; python local_llm_service.py"
Start-Sleep -Seconds 2

# Start Unified App (Frontend GUI)
Write-Host "Starting Unified App Frontend..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$repoRoot\unified-app'; python main.py"

Write-Host "`n✅ All services started!" -ForegroundColor Green
Write-Host "`nService URLs:" -ForegroundColor Cyan
Write-Host "  Ollama:    http://127.0.0.1:11434" -ForegroundColor White
Write-Host "  Browser:   http://127.0.0.1:8103/health" -ForegroundColor White
Write-Host "  Desktop:   http://127.0.0.1:8101/health" -ForegroundColor White
Write-Host "  CLI:       http://127.0.0.1:8102/health" -ForegroundColor White
Write-Host "  Local LLM: http://127.0.0.1:8104/health" -ForegroundColor White
Write-Host "  Dashboard: http://127.0.0.1:8104/dashboard" -ForegroundColor White
Write-Host "`nWait 10-15 seconds for all services and GUI to initialize." -ForegroundColor Yellow
Write-Host "Press Ctrl+C in each service window to stop." -ForegroundColor Gray
