# Phase A0+A1 (merged): MVXW R full sweep at production-exact (N5, T1.45, D10, B20.0)
# Hypothesis: Production R=3.35 is too large for short-window D10 trades.
# 4022 ラサ工業 (2026-04-22): peak +¥107 ≈ +0.27R, R=3.35 prevented TP1.
# 58 R values (0.05 step): R ∈ {0.50, 0.55, ..., 3.35}.
# Years 2022-2025 (4 years), ranking momentum to align with production.
# R=3.35 inside the grid serves as A0 baseline.
# OVERLAY: OFF (project policy; baseline 1949% is overlay-OFF).

Set-Location -Path $PSScriptRoot

$rValues = 0..57 | ForEach-Object { [math]::Round(0.50 + 0.05 * $_, 2) }

function Format-RToken {
    param([double]$value)
    $s = "{0:F2}" -f $value
    if ($s.EndsWith("00")) { $s = $s.Substring(0, $s.Length - 1) }
    elseif ($s.EndsWith("0")) { $s = $s.Substring(0, $s.Length - 1) }
    return $s.Replace(".", "p")
}

$exitList = @()
foreach ($r in $rValues) {
    $token = Format-RToken -value $r
    $exitList += "MVXW_N5_R${token}_T1p45_D10_B20p0"
}

Write-Output "exit_count=$($exitList.Count)"
Write-Output "first=$($exitList[0])"
Write-Output "last=$($exitList[-1])"

.venv/Scripts/python.exe main.py evaluate `
    --mode annual `
    --years 2022 2023 2024 2025 `
    --entry-strategies MACDPreCross2BarEntry `
    --exit-strategies $exitList `
    --ranking-strategies momentum `
    --ranking-mode target20 `
    --entry-filter-mode off
