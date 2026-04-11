# Test Trinity-Pilot Module Services Health
# Checks if all three services are running and healthy

Write-Host "Testing Trinity-Pilot Module Services..." -ForegroundColor Cyan

$services = @(
    @{ Name = "Browser"; Port = 8103 },
    @{ Name = "Desktop"; Port = 8101 },
    @{ Name = "CLI"; Port = 8102 }
)

$allHealthy = $true

foreach ($service in $services) {
    $url = "http://127.0.0.1:$($service.Port)/health"
    Write-Host "`nTesting $($service.Name) service at $url..." -ForegroundColor Yellow
    
    try {
        $response = Invoke-RestMethod -Uri $url -TimeoutSec 5
        if ($response.status -eq "ok") {
            Write-Host "✅ $($service.Name) service is healthy" -ForegroundColor Green
        } else {
            Write-Host "⚠️  $($service.Name) service returned: $($response.status)" -ForegroundColor Yellow
            $allHealthy = $false
        }
    } catch {
        Write-Host "❌ $($service.Name) service is not responding" -ForegroundColor Red
        Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Gray
        $allHealthy = $false
    }
}

Write-Host "`n" + ("="*70) -ForegroundColor Cyan
if ($allHealthy) {
    Write-Host "✅ ALL SERVICES HEALTHY - Ready for testing!" -ForegroundColor Green
} else {
    Write-Host "❌ SOME SERVICES ARE DOWN - Check service windows for errors" -ForegroundColor Red
}
Write-Host ("="*70) -ForegroundColor Cyan
