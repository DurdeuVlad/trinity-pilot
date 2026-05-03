"""
CLI executor reference — allowed commands, cheat sheet, forbidden patterns.

Single source of truth injected into the CLI domain briefing at runtime.
"""

CLI_REFERENCE = """\
ALLOWED COMMANDS (validator allowlist — only these will pass):

  filesystem: Add-Content, Copy-Item, Get-ChildItem, Get-Content, Get-Location,
    Get-Item, Invoke-Item, Join-Path, Move-Item, New-Item, Out-File, Remove-Item,
    Rename-Item, Resolve-Path, Select-String, Set-Content, Set-Location, Split-Path,
    Test-Path, dir, ls, pwd, Push-Location, Pop-Location, type

  process: Get-Process, Start-Process, Stop-Process, explorer, notepad, tasklist

  system_info: Get-CimInstance, Get-ComputerInfo, Get-Date, Get-Disk, Get-EventLog,
    Get-Host, Get-NetAdapter, Get-PSDrive, Get-Service, Get-Variable, Get-Volume,
    Get-WinEvent, Get-WmiObject, hostname, systeminfo, ver, whoami, wmic

  network: Invoke-WebRequest, Resolve-DnsName, Test-Connection, curl, ipconfig, ping

  output: ConvertTo-Json, Format-List, Format-Table, Out-String, Write-Host,
    Write-Output, echo

  pipeline: Compare-Object, Expand-Property, ForEach-Object, Get-Unique,
    Group-Object, Measure-Object, Select-Object, Sort-Object, Tee-Object,
    Where-Object, findstr, where

  language: ConvertFrom-Csv, ConvertFrom-Json, ConvertTo-Csv, New-Variable,
    Set-Variable, Write-Error, catch, finally, if, else, return, try

  package_management: npm, pip, winget

COMMAND CHEAT SHEET (translate shorthand to validator-safe PowerShell):

  Show current directory     -> Get-Location
  List directory contents    -> Get-ChildItem
  List files recursively     -> Get-ChildItem -Path <dir> -Recurse -File | Select-Object FullName
  List by extension          -> Get-ChildItem -Path <dir> -Filter '*.py' -File | Select-Object -ExpandProperty Name
  Read a file                -> Get-Content -Path <file>
  Search file contents       -> Get-ChildItem -Path <dir> -Recurse -File | Select-String -Pattern 'text'
  Count matches              -> (Get-ChildItem -Path <dir> -Recurse -File | Select-String -Pattern 'text').Count
  Create directory           -> New-Item -Path <dir> -ItemType Directory -Force
  Create/overwrite text file -> 'content' | Out-File -FilePath <file> -Encoding utf8
  Append to file             -> 'content' | Add-Content -Path <file>
  Check path exists          -> Test-Path <path>
  Rename file/folder         -> Rename-Item -Path <path> -NewName <name>
  Copy file/folder           -> Copy-Item -Path <src> -Destination <dst>
  Move file/folder           -> Move-Item -Path <src> -Destination <dst>
  Delete one path            -> Remove-Item -Path <path> -Force
  Python version             -> python --version
  System info                -> Get-ComputerInfo  or  systeminfo
  Disk usage                 -> Get-PSDrive  or  Get-Volume
  Running processes          -> Get-Process
  Check if process running   -> Get-Process -Name <name> -ErrorAction SilentlyContinue

  Aliases blocked at validation -- use the PowerShell form:
    dir / ls    -> Get-ChildItem
    pwd         -> Get-Location
    type / cat  -> Get-Content
    copy        -> Copy-Item
    move        -> Move-Item
    ren         -> Rename-Item
    del         -> Remove-Item -Path <path> -Force
    findstr     -> Select-String
    where       -> Get-ChildItem with -Filter

FORBIDDEN PATTERNS (these are rejected by the validator, do not emit them):

  Invoke-Expression / iex    (CL-POL-001) -- dynamic code execution
  Invoke-Command             (CL-POL-002) -- remote execution
  Start-Job                  (CL-POL-003) -- background jobs
  Register-ScheduledTask     (CL-POL-004) -- task scheduling
  Set-ExecutionPolicy        (CL-POL-005) -- security policy change
  Add-Type                   (CL-POL-006) -- runtime C# compilation
  Format-Volume              (CL-POL-007) -- disk formatting (irreversible)
  Remove-Item -Recurse -Force (CL-POL-008) -- bulk recursive delete
  Restart-Computer           (CL-POL-009) -- system restart
  Stop-Computer              (CL-POL-010) -- system shutdown
  cmd /c, powershell -Command -- shell wrappers (not needed; use cmdlets directly)
"""
