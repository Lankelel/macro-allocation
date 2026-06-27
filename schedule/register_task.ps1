# Register the quarterly scheduled task (Windows Task Scheduler).
# Quarterly = 1st day of Jan/Apr/Jul/Oct at 09:00 (Task Scheduler has no native "quarterly"; use month filter).
# Usage (run manually in PowerShell):  .\schedule\register_task.ps1
# Note: creating a scheduled task is a system-level action; this script is NOT auto-invoked.
$ErrorActionPreference = "Stop"

$taskName = "MacroAllocationQuarterly"
$script = Join-Path $PSScriptRoot "run_quarterly.ps1"
if (-not (Test-Path $script)) { throw "run_quarterly.ps1 not found: $script" }

# Action: run run_quarterly.ps1 via powershell (path has spaces -> inner quotes required)
$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$script`""

Write-Host "Registering scheduled task: $taskName"
Write-Host "  Trigger: 1st of Jan/Apr/Jul/Oct at 09:00"
Write-Host "  Runs:    $script"
schtasks.exe /Create /TN $taskName /TR $action /SC MONTHLY /M JAN,APR,JUL,OCT /D 1 /ST 09:00 /F

if ($?) {
    Write-Host ""
    Write-Host "Registered. Manage with:"
    Write-Host "  Inspect:  schtasks /Query /TN $taskName /V /FO LIST"
    Write-Host "  Test now: schtasks /Run /TN $taskName"
    Write-Host "  Remove:   .\schedule\unregister_task.ps1"
}
