#!/usr/bin/env python3
"""Prepare Phase-2 multi-round joint tuning sets from Step-1 results.

Outputs:
- strategy_evaluation/phase2_round1_entry_strategies.txt
- strategy_evaluation/phase2_round1_exit_strategies.txt
- strategy_evaluation/phase2_round2_entry_strategies.txt
- strategy_evaluation/phase2_round2_exit_strategies.txt
- execute_phase2_round1.ps1
- execute_phase2_round2.ps1
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.strategy_loader import ENTRY_STRATEGIES, EXIT_STRATEGIES


MACX_PAT = re.compile(
    r"^MACX_F(?P<fast>E20|S20|S25)_S(?P<slow>E50|E200)_P(?P<spread>\d+p\d+)_A(?P<a>[01])_C(?P<c>\d+p\d+)$"
)
MVX_PAT = re.compile(
    r"^MVX_N(?P<n>\d+)_R(?P<r>\d+p\d+)_T(?P<t>\d+p\d+)_D(?P<d>\d+)_B(?P<b>\d+p\d+)$"
)
MDX_PAT = re.compile(
    r"^MDX_C(?P<c>\d+)_R(?P<r>\d+p\d+)_T(?P<t>\d+p\d+)_D(?P<d>\d+)_O(?P<o>\d+p\d+)$"
)


def p2f(token: str) -> float:
    return float(token.replace("p", "."))


def f2p(value: float) -> str:
    return str(float(value)).replace(".", "p")


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def create_execute_ps1(path: Path, entry_file: str, exit_file: str, label: str) -> None:
    content = f"""# {label}
Set-StrictMode -Version Latest
$ErrorActionPreference = \"Stop\"

Push-Location \"$PSScriptRoot\"
try {{
    Write-Host \"=== {label} ===\" -ForegroundColor Cyan

    $entryStrategies = @(
        Get-Content {entry_file} |
        Where-Object {{ $_ -and $_.Trim().Length -gt 0 }}
    )
    $exitStrategies = @(
        Get-Content {exit_file} |
        Where-Object {{ $_ -and $_.Trim().Length -gt 0 }}
    )

    $tasks = $entryStrategies.Count * $exitStrategies.Count * 5
    Write-Host (\"Entry strategies: {{0}}\" -f $entryStrategies.Count) -ForegroundColor Green
    Write-Host (\"Exit strategies : {{0}}\" -f $exitStrategies.Count) -ForegroundColor Green
    Write-Host (\"5-year tasks     : {{0}}\" -f $tasks) -ForegroundColor Yellow

    $args = @(
        \"main.py\",
        \"evaluate\",
        \"--mode\", \"annual\",
        \"--years\", \"2021\", \"2022\", \"2023\", \"2024\", \"2025\",
        \"--entry-strategies\"
    )

    $args += $entryStrategies
    $args += @("--exit-strategies")
    $args += $exitStrategies
    $args += @("--ranking-mode", "target20")

    $startTime = Get-Date
    & .venv/Scripts/python.exe @args
    if ($LASTEXITCODE -ne 0) {{
        throw \"{label} failed\"
    }}

    $duration = (Get-Date) - $startTime
    Write-Host \"\"
    Write-Host \"=== {label} completed ===\" -ForegroundColor Green
    Write-Host (\"Elapsed: {{0:N2}} minutes\" -f $duration.TotalMinutes) -ForegroundColor Cyan
}}
finally {{
    Pop-Location
}}
"""
    path.write_text(content, encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Phase-2 multi-round lists")
    parser.add_argument("--step1-rank-csv", required=True, help="Step-1 target20 rank CSV")
    args = parser.parse_args()

    rank_df = pd.read_csv(args.step1_rank_csv)

    # Round-1: top entries + diversified top exits
    entry_r1 = (
        rank_df.groupby("entry_strategy", as_index=False)["target20_score"]
        .mean()
        .sort_values("target20_score", ascending=False)
        .head(6)["entry_strategy"]
        .tolist()
    )

    exit_mean = (
        rank_df.groupby("exit_strategy", as_index=False)["target20_score"]
        .mean()
        .sort_values("target20_score", ascending=False)
    )
    mvx_top = [x for x in exit_mean["exit_strategy"].tolist() if str(x).startswith("MVX_")][:4]
    mdx_top = [x for x in exit_mean["exit_strategy"].tolist() if str(x).startswith("MDX_")][:4]
    remain = [x for x in exit_mean["exit_strategy"].tolist() if x not in mvx_top and x not in mdx_top]
    exit_r1 = (mvx_top + mdx_top + remain)[:8]

    # Round-2: smaller-step local neighborhoods around best entry/exit families
    best_row = rank_df.sort_values(["target20_score", "rank"], ascending=[False, True]).iloc[0]

    # Entry fine neighborhood
    entry_r2: list[str] = []
    m = MACX_PAT.match(str(best_row["entry_strategy"]))
    if m:
        g = m.groupdict()
        fast = g["fast"]
        slow = g["slow"]
        spread_center = p2f(g["spread"])
        conf_center = p2f(g["c"])

        spread_vals = sorted(
            {
                round(max(0.0, spread_center - 0.05), 2),
                round(spread_center, 2),
                round(spread_center + 0.05, 2),
            }
        )
        conf_vals = sorted(
            {
                round(max(0.56, conf_center - 0.02), 2),
                round(conf_center, 2),
                round(min(0.64, conf_center + 0.02), 2),
            }
        )

        for spread in spread_vals:
            for conf in conf_vals:
                for a in [0, 1]:
                    name = f"MACXF_F{fast}_S{slow}_P{f2p(spread)}_A{a}_C{f2p(conf)}"
                    if name in ENTRY_STRATEGIES:
                        entry_r2.append(name)

    entry_r2 = sorted(set(entry_r2))[:18]

    # Exit fine neighborhood from best MVX and best MDX
    mvx_r2_scored: list[tuple[float, str]] = []
    mdx_r2_scored: list[tuple[float, str]] = []

    best_mvx_row = rank_df[rank_df["exit_strategy"].str.startswith("MVX_")].sort_values(
        ["target20_score", "rank"], ascending=[False, True]
    )
    if not best_mvx_row.empty:
        mvx = MVX_PAT.match(str(best_mvx_row.iloc[0]["exit_strategy"]))
        if mvx:
            g = mvx.groupdict()
            n_center = int(g["n"])
            r_center = p2f(g["r"])
            t_center = p2f(g["t"])
            b_center = p2f(g["b"])

            n_vals = sorted({max(8, n_center - 1), n_center, min(10, n_center + 1)})
            r_vals = sorted({round(r_center - 0.05, 2), round(r_center, 2), round(r_center + 0.05, 2)})
            t_vals = sorted({round(t_center - 0.05, 2), round(t_center, 2), round(t_center + 0.05, 2)})
            b_vals = sorted({round(b_center - 0.25, 2), round(b_center, 2), round(b_center + 0.25, 2)})

            for n in n_vals:
                for r in r_vals:
                    for t in t_vals:
                        for b in b_vals:
                            name = f"MVXF_N{n}_R{f2p(r)}_T{f2p(t)}_D18_B{f2p(b)}"
                            if name in EXIT_STRATEGIES:
                                dist = abs(n - n_center) + abs(r - r_center) * 10 + abs(t - t_center) * 10 + abs(b - b_center) * 4
                                mvx_r2_scored.append((dist, name))

    best_mdx_row = rank_df[rank_df["exit_strategy"].str.startswith("MDX_")].sort_values(
        ["target20_score", "rank"], ascending=[False, True]
    )
    if not best_mdx_row.empty:
        mdx = MDX_PAT.match(str(best_mdx_row.iloc[0]["exit_strategy"]))
        if mdx:
            g = mdx.groupdict()
            c_center = int(g["c"])
            r_center = p2f(g["r"])
            t_center = p2f(g["t"])
            o_center = p2f(g["o"])

            c_vals = sorted({max(2, c_center - 1), c_center, min(3, c_center + 1)})
            r_vals = sorted({round(r_center - 0.1, 2), round(r_center, 2), round(r_center + 0.1, 2)})
            t_vals = sorted({round(t_center - 0.05, 2), round(t_center, 2), round(t_center + 0.05, 2)})
            o_vals = sorted({round(max(74.0, o_center - 1.0), 2), round(o_center, 2), round(min(76.0, o_center + 1.0), 2)})

            for c in c_vals:
                for r in r_vals:
                    for t in t_vals:
                        for o in o_vals:
                            name = f"MDXF_C{c}_R{f2p(r)}_T{f2p(t)}_D18_O{f2p(o)}"
                            if name in EXIT_STRATEGIES:
                                dist = abs(c - c_center) + abs(r - r_center) * 10 + abs(t - t_center) * 10 + abs(o - o_center)
                                mdx_r2_scored.append((dist, name))

    mvx_sorted = [
        name
        for _, name in sorted(set(mvx_r2_scored), key=lambda x: (x[0], x[1]))
    ]
    mdx_sorted = [
        name
        for _, name in sorted(set(mdx_r2_scored), key=lambda x: (x[0], x[1]))
    ]

    exit_r2 = []
    exit_r2.extend(mvx_sorted[:10])
    exit_r2.extend(mdx_sorted[:10])

    if len(exit_r2) < 20:
        for name in mvx_sorted[10:] + mdx_sorted[10:]:
            if name not in exit_r2:
                exit_r2.append(name)
            if len(exit_r2) >= 20:
                break

    out_dir = PROJECT_ROOT / "strategy_evaluation"
    write_lines(out_dir / "phase2_round1_entry_strategies.txt", entry_r1)
    write_lines(out_dir / "phase2_round1_exit_strategies.txt", exit_r1)
    write_lines(out_dir / "phase2_round2_entry_strategies.txt", entry_r2)
    write_lines(out_dir / "phase2_round2_exit_strategies.txt", exit_r2)

    create_execute_ps1(
        PROJECT_ROOT / "execute_phase2_round1.ps1",
        "strategy_evaluation/phase2_round1_entry_strategies.txt",
        "strategy_evaluation/phase2_round1_exit_strategies.txt",
        "Phase-2 Round-1 Joint Tuning",
    )
    create_execute_ps1(
        PROJECT_ROOT / "execute_phase2_round2.ps1",
        "strategy_evaluation/phase2_round2_entry_strategies.txt",
        "strategy_evaluation/phase2_round2_exit_strategies.txt",
        "Phase-2 Round-2 Joint Fine Tuning",
    )

    print(f"ROUND1_ENTRY={len(entry_r1)}")
    print(f"ROUND1_EXIT={len(exit_r1)}")
    print(f"ROUND1_TASKS_5Y={len(entry_r1) * len(exit_r1) * 5}")
    print(f"ROUND2_ENTRY={len(entry_r2)}")
    print(f"ROUND2_EXIT={len(exit_r2)}")
    print(f"ROUND2_TASKS_5Y={len(entry_r2) * len(exit_r2) * 5}")


if __name__ == "__main__":
    main()
