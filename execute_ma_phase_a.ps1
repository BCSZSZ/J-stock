# Phase A MA entry grid evaluation
# Auto-discovers all Phase A entry strategies (MACX_*), then runs evaluate.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Push-Location "$PSScriptRoot"
try {
    Write-Host "=== Phase A: MA Entry Grid Evaluation ===" -ForegroundColor Cyan

    $entryLines = & .venv/Scripts/python.exe -c "from src.utils.strategy_loader import ENTRY_STRATEGIES; print('\n'.join(sorted(k for k in ENTRY_STRATEGIES if k.startswith('MACX_'))))"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to load Phase A strategy list"
    }

    $entryStrategies = @(
        $entryLines -split "`r?`n" |
        Where-Object { $_ -and $_.Trim().Length -gt 0 }
    )

    if ($entryStrategies.Count -eq 0) {
        throw "No Phase A strategy found (expected names with MACX_ prefix)"
    }

    Write-Host ("Phase A entry strategy count: {0}" -f $entryStrategies.Count) -ForegroundColor Green
    Write-Host "Exit strategy: MVX_N9_R3p6_T1p7_D18_B20p0" -ForegroundColor Yellow
    Write-Host "Ranking mode: target20" -ForegroundColor Yellow
    Write-Host "Years: 2021-2025" -ForegroundColor Yellow

    $args = @(
        "main.py",
        "evaluate",
        "--mode", "annual",
        "--years", "2021", "2022", "2023", "2024", "2025",
        "--entry-strategies"
    )

    $args += $entryStrategies
    $args += @(
        "--exit-strategies", "MVX_N9_R3p6_T1p7_D18_B20p0",
        "--ranking-mode", "target20"
    )

    $startTime = Get-Date
    & .venv/Scripts/python.exe @args
    if ($LASTEXITCODE -ne 0) {
        throw "Phase A evaluation failed"
    }

    $duration = (Get-Date) - $startTime
    Write-Host "" 
    Write-Host "=== Phase A run completed ===" -ForegroundColor Green
    Write-Host ("Elapsed: {0:N2} minutes" -f $duration.TotalMinutes) -ForegroundColor Cyan
}
finally {
    Pop-Location
}
