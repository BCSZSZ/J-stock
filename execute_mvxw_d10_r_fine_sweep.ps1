# Phase A1-fine: MVXW R fine sweep at production-exact (N5, T1.45, D10, B20.0).
# Refines the 0.05-step low-R cluster around R=0.55 to 0.01 step.
# 41 R values: R ∈ {0.50, 0.51, 0.52, ..., 0.90}.
# Years 2022-2025 (4 years), ranking momentum.
# OVERLAY: OFF (project policy).

Set-Location -Path $PSScriptRoot

$rValues = 0..40 | ForEach-Object { [math]::Round(0.50 + 0.01 * $_, 2) }

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
