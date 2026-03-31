param(
  [switch]$Clean
)

if ($Clean) {
  Remove-Item -Recurse -Force .\build, .\dist -ErrorAction SilentlyContinue
}

Write-Host "Building Orchestrator Desktop App with PyInstaller..."
pyinstaller orchestrator.spec --noconfirm

Write-Host "Build finished. Output: .\dist\OrchestratorDesktopApp.exe"
