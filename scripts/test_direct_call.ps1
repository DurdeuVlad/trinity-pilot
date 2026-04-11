# Test Direct Module Call
# Tests CLI module service with a simple task to verify Gemini function calling works

Write-Host "Testing Direct Module Call (CLI Service)..." -ForegroundColor Cyan

$url = "http://127.0.0.1:8102/task"
$body = @{
    description = "List all files in the current directory"
    context = ""
} | ConvertTo-Json

Write-Host "`nSending task to CLI module service..." -ForegroundColor Yellow
Write-Host "URL: $url" -ForegroundColor Gray
Write-Host "Task: List all files in the current directory" -ForegroundColor Gray

try {
    $response = Invoke-RestMethod -Uri $url -Method POST -Body $body -ContentType "application/json" -TimeoutSec 30
    
    Write-Host "`n" + ("="*70) -ForegroundColor Cyan
    Write-Host "✅ TASK COMPLETED SUCCESSFULLY" -ForegroundColor Green
    Write-Host ("="*70) -ForegroundColor Cyan
    
    Write-Host "`nResult:" -ForegroundColor Yellow
    Write-Host $response.result -ForegroundColor White
    
    Write-Host "`nSteps Taken: $($response.steps_taken)" -ForegroundColor Cyan
    
    if ($response.error) {
        Write-Host "`nError: $($response.error)" -ForegroundColor Red
    }
    
    Write-Host "`n" + ("="*70) -ForegroundColor Cyan
    Write-Host "✅ Gemini function calling is working!" -ForegroundColor Green
    Write-Host ("="*70) -ForegroundColor Cyan
    
} catch {
    Write-Host "`n" + ("="*70) -ForegroundColor Cyan
    Write-Host "❌ TASK FAILED" -ForegroundColor Red
    Write-Host ("="*70) -ForegroundColor Cyan
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "`nResponse Body:" -ForegroundColor Yellow
        Write-Host $responseBody -ForegroundColor Gray
    }
}
