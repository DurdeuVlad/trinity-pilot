# Harness seeder for TC-CLI-01
# Seeds C:\Temp\trinity_cli_test with 3 log files containing exactly 4 lines with 'error'
# Distribution: file1.txt=2, file2.txt=1, file3.txt=1
# Run this before each TC-CLI-01 live test run.

param(
    [string]$Root = "C:\Temp\trinity_cli_test"
)

# Clean up any previous run
if (Test-Path $Root) {
    Remove-Item -Recurse -Force $Root
}

# Create directory structure
New-Item -ItemType Directory -Path "$Root\subdir_a" -Force | Out-Null
New-Item -ItemType Directory -Path "$Root\subdir_b" -Force | Out-Null

# file1.txt — 2 error lines
@"
2026-04-11 10:00:01 INFO  Service started
2026-04-11 10:00:05 error disk threshold exceeded
2026-04-11 10:00:10 WARN  Retrying connection
2026-04-11 10:00:15 error null pointer in handler
2026-04-11 10:00:20 INFO  Recovered successfully
"@ | Set-Content -Path "$Root\subdir_a\file1.txt"

# file2.txt — 1 error line
@"
2026-04-11 11:00:01 INFO  Worker initialized
2026-04-11 11:00:03 DEBUG Reading config
2026-04-11 11:00:07 error timeout waiting for response
2026-04-11 11:00:08 INFO  Fallback triggered
"@ | Set-Content -Path "$Root\subdir_a\file2.txt"

# file3.txt — 1 error line
@"
2026-04-11 12:00:01 INFO  Batch job started
2026-04-11 12:00:04 INFO  Processing 100 records
2026-04-11 12:00:09 error file not found: data.csv
2026-04-11 12:00:10 WARN  Skipping missing file
2026-04-11 12:00:15 INFO  Batch job finished
"@ | Set-Content -Path "$Root\subdir_b\file3.txt"

Write-Host "Seeded $Root"
Write-Host "  subdir_a\file1.txt - 2 error lines"
Write-Host "  subdir_a\file2.txt - 1 error line"
Write-Host "  subdir_b\file3.txt - 1 error line"
Write-Host "Total expected error line count: 4"
