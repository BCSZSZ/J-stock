# Phase-1 Expanded Coarse Grid (Nightly)
# Entry families are pruned to strong winners; freed capacity is moved to exits.
# Designed for ~6h runtime under assumption: 1 task ~= 15s.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Push-Location "$PSScriptRoot"
try {
    Write-Host "=== Phase-1 Expanded Coarse Grid ===" -ForegroundColor Cyan

    $entryStrategies = @(
        Get-Content strategy_evaluation/phase1_expanded_entry_strategies.txt |
        Where-Object { $_ -and $_.Trim().Length -gt 0 }
    )

    $exitStrategies = @(
        Get-Content strategy_evaluation/phase1_expanded_exit_strategies.txt |
        Where-Object { $_ -and $_.Trim().Length -gt 0 }
    )

    if ($entryStrategies.Count -eq 0) {
        throw "No entry strategies found in strategy_evaluation/phase1_expanded_entry_strategies.txt"
    }

    if ($exitStrategies.Count -eq 0) {
        throw "No exit strategies found in strategy_evaluation/phase1_expanded_exit_strategies.txt"
    }

    $comboCount = $entryStrategies.Count * $exitStrategies.Count
    $tasks = $comboCount * 5
    $estSeconds = $tasks * 15
    $estHours = $estSeconds / 3600.0

    Write-Host ("Entry strategies: {0}" -f $entryStrategies.Count) -ForegroundColor Green
    Write-Host ("Exit strategies : {0}" -f $exitStrategies.Count) -ForegroundColor Green
    Write-Host ("Combos          : {0}" -f $comboCount) -ForegroundColor Green
    Write-Host ("5-year tasks    : {0}" -f $tasks) -ForegroundColor Yellow
    Write-Host ("Est. runtime    : {0:N2} hours (@15s/task)" -f $estHours) -ForegroundColor Yellow
    Write-Host "Ranking mode    : target20" -ForegroundColor Yellow

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
        throw "Phase-1 expanded run failed"
    }

    $duration = (Get-Date) - $startTime
    Write-Host ""
    Write-Host "=== Phase-1 expanded run completed ===" -ForegroundColor Green
    Write-Host ("Elapsed: {0:N2} minutes" -f $duration.TotalMinutes) -ForegroundColor Cyan
}
finally {
    Pop-Location
}