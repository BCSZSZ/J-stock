# Phase B Joint Tuning: Entry + Exit
# Uses strategy lists generated from Phase A winners and MVX nearby grid.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Push-Location "$PSScriptRoot"
try {
    Write-Host "=== Phase B Joint Tuning (Entry + Exit) ===" -ForegroundColor Cyan

    $entryStrategies = @(
        Get-Content strategy_evaluation/phase_b_joint_entry_strategies.txt |
        Where-Object { $_ -and $_.Trim().Length -gt 0 }
    )

    $exitStrategies = @(
        Get-Content strategy_evaluation/phase_b_joint_exit_strategies.txt |
        Where-Object { $_ -and $_.Trim().Length -gt 0 }
    )

    if ($entryStrategies.Count -eq 0) {
        throw "No entry strategies found in strategy_evaluation/phase_b_joint_entry_strategies.txt"
    }
    if ($exitStrategies.Count -eq 0) {
        throw "No exit strategies found in strategy_evaluation/phase_b_joint_exit_strategies.txt"
    }

    $tasks = $entryStrategies.Count * $exitStrategies.Count * 5

    Write-Host ("Entry strategies: {0}" -f $entryStrategies.Count) -ForegroundColor Green
    Write-Host ("Exit strategies : {0}" -f $exitStrategies.Count) -ForegroundColor Green
    Write-Host ("5-year tasks     : {0}" -f $tasks) -ForegroundColor Yellow
    Write-Host "Ranking mode     : target20" -ForegroundColor Yellow

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
        throw "Phase B joint evaluation failed"
    }

    $duration = (Get-Date) - $startTime
    Write-Host ""
    Write-Host "=== Phase B joint run completed ===" -ForegroundColor Green
    Write-Host ("Elapsed: {0:N2} minutes" -f $duration.TotalMinutes) -ForegroundColor Cyan
}
finally {
    Pop-Location
}
