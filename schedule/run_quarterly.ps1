# Quarterly auto-run: refresh holdings -> full pipeline (M1->clock->M2->M3 + quant) -> Finance.md proposal
# Called by the scheduled task once per quarter (see register_task.ps1). Can also be run manually to test.
# ASCII-only on purpose: PowerShell 5.1 mis-decodes non-BOM UTF-8 .ps1 (Chinese turns to mojibake).
$ErrorActionPreference = "Continue"

# Project root = parent of this script's folder (schedule/). Portable, no hardcoded absolute path.
$proj = Split-Path -Parent $PSScriptRoot
Set-Location $proj
$env:PYTHONIOENCODING = "utf-8"

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$logDir = Join-Path $proj "outputs\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "run_$ts.log"

"[$(Get-Date)] === quarterly run start ===" | Tee-Object -FilePath $log
"[$(Get-Date)] [1/3] holdings_sync (refresh per-fund holdings)" | Tee-Object -FilePath $log -Append
python -m uv run python -m holdings_sync *>> $log
"[$(Get-Date)] [2/3] main.py (M1->clock->M2->M3 + quant layer)" | Tee-Object -FilePath $log -Append
python -m uv run python main.py *>> $log
"[$(Get-Date)] [3/3] results_sync (Finance.md proposal only, does NOT edit Finance.md)" | Tee-Object -FilePath $log -Append
python -m uv run python -m results_sync *>> $log

"[$(Get-Date)] === done ===" | Tee-Object -FilePath $log -Append
"Outputs in outputs/. Log: $log" | Tee-Object -FilePath $log -Append
"Review outputs/finance_sync_proposal.md before applying to Finance.md (human-in-the-loop)." | Tee-Object -FilePath $log -Append
