# Unregister the quarterly scheduled task.  Usage:  .\schedule\unregister_task.ps1
$taskName = "MacroAllocationQuarterly"
schtasks.exe /Delete /TN $taskName /F
if ($?) { Write-Host "Deleted scheduled task: $taskName" }
