# Phase-2 Round-2 Joint Fine Tuning
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Push-Location "$PSScriptRoot"
try {
    Write-Host "=== Phase-2 Round-2 Joint Fine Tuning ===" -ForegroundColor Cyan

    $entryStrategies = @(
        Get-Content strategy_evaluation/phase2_round2_entry_strategies.txt |
        Where-Object { $_ -and $_.Trim().Length -gt 0 }
    )
    $exitStrategies = @(
        Get-Content strategy_evaluation/phase2_round2_exit_strategies.txt |
        Where-Object { $_ -and $_.Trim().Length -gt 0 }
    )

    $tasks = $entryStrategies.Count * $exitStrategies.Count * 5
    Write-Host ("Entry strategies: {0}" -f $entryStrategies.Count) -ForegroundColor Green
    Write-Host ("Exit strategies : {0}" -f $exitStrategies.Count) -ForegroundColor Green
    Write-Host ("5-year tasks     : {0}" -f $tasks) -ForegroundColor Yellow

    $args = @(
        "main.py",
        "evaluate",
        "--mode", "annual",
        "--years", "2021", "2022", "2023", "2024", "2025",
        "--entry-strategies"
    )

    $args += $entryStrategies
    $args += @("--exit-strategies")
    $args += $exitStrategies
    $args += @("--ranking-mode", "target20")

    $startTime = Get-Date
    & .venv/Scripts/python.exe @args
    if ($LASTEXITCODE -ne 0) {
        throw "Phase-2 Round-2 Joint Fine Tuning failed"
    }

    $duration = (Get-Date) - $startTime
    Write-Host ""
    Write-Host "=== Phase-2 Round-2 Joint Fine Tuning completed ===" -ForegroundColor Green
    Write-Host ("Elapsed: {0:N2} minutes" -f $duration.TotalMinutes) -ForegroundColor Cyan
}
finally {
    Pop-Location
}
