!include "MUI2.nsh"

Name "Orchestrator Desktop App"
OutFile "OrchestratorSetup.exe"
InstallDir "$PROGRAMFILES\OrchestratorDesktopApp"

Page directory
Page instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File "dist\OrchestratorDesktopApp.exe"
  CreateShortcut "$DESKTOP\Orchestrator Desktop App.lnk" "$INSTDIR\OrchestratorDesktopApp.exe"
SectionEnd
