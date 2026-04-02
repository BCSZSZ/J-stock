#!/usr/bin/env python3
"""Prepare Step-1 exit screening strategy lists.

Step-1 scope:
- Entry: 3 representative MA entries from Phase-A ranking winners.
- Exit: 24 candidates (12 MVX + 12 MDX) for family-level screening.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.strategy_loader import EXIT_STRATEGIES


PATTERN = re.compile(
    r"^MACX_F(?P<fast>E20|S20|S25)_S(?P<slow>E50|E200)_P(?P<spread>\d+p\d+)_A(?P<a>[01])_C(?P<c>\d+p\d+)$"
)


def build_exit_candidates() -> list[str]:
    names: list[str] = []

    # MVX coarse neighborhood around current strong baseline
    for n in [8, 9, 10]:
        for r in ["3p5", "3p6"]:
            for t in ["1p6", "1p7"]:
                names.append(f"MVX_N{n}_R{r}_T{t}_D18_B20p0")

    # MDX coarse neighborhood centered on D18/O75
    for c in [2, 3]:
        for r in ["3p2", "3p4", "3p6"]:
            for t in ["1p6", "1p7"]:
                names.append(f"MDX_C{c}_R{r}_T{t}_D18_O75p0")

    missing = [name for name in names if name not in EXIT_STRATEGIES]
    if missing:
        raise ValueError(f"Missing exit strategies in loader: {missing}")

    return names


def build_entry_representatives(rank_csv: Path) -> list[str]:
    df = pd.read_csv(rank_csv)

    rows = []
    for _, row in df.iterrows():
        strategy = str(row["entry_strategy"])
        m = PATTERN.match(strategy)
        if not m:
            continue
        g = m.groupdict()
        rows.append(
            {
                "entry_strategy": strategy,
                "rank": int(row["rank"]),
                "target20_score": float(row["target20_score"]),
                "fast": g["fast"],
                "slow": g["slow"],
            }
        )

    meta = pd.DataFrame(rows)
    if meta.empty:
        raise ValueError("No MACX strategies found in ranking CSV")

    representative_families = [("E20", "E50"), ("S20", "E50"), ("S25", "E200")]

    selected: list[str] = []
    for fast, slow in representative_families:
        sub = meta[(meta["fast"] == fast) & (meta["slow"] == slow)].sort_values(
            ["target20_score", "rank"], ascending=[False, True]
        )
        if not sub.empty:
            selected.append(str(sub.iloc[0]["entry_strategy"]))

    if len(selected) < 3:
        extra = meta[~meta["entry_strategy"].isin(selected)].sort_values(
            ["target20_score", "rank"], ascending=[False, True]
        )
        selected.extend(extra["entry_strategy"].head(3 - len(selected)).tolist())

    return selected[:3]


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Step-1 exit screening lists")
    parser.add_argument(
        "--phase-a-rank-csv",
        default=r"G:/My Drive/AI-Stock-Sync/strategy_evaluation/strategy_evaluation_target20_rank_20260402_125622.csv",
        help="Phase-A target20 rank CSV path",
    )
    parser.add_argument(
        "--entry-output",
        default="strategy_evaluation/exit_a_entry_strategies.txt",
        help="Output file for representative entry strategies",
    )
    parser.add_argument(
        "--exit-output",
        default="strategy_evaluation/exit_a_exit_strategies.txt",
        help="Output file for exit screening strategies",
    )
    args = parser.parse_args()

    rank_csv = Path(args.phase_a_rank_csv)
    entry_output = Path(args.entry_output)
    exit_output = Path(args.exit_output)

    entry_list = build_entry_representatives(rank_csv)
    exit_list = build_exit_candidates()

    write_lines(entry_output, entry_list)
    write_lines(exit_output, exit_list)

    tasks = len(entry_list) * len(exit_list) * 5

    print(f"ENTRY_COUNT={len(entry_list)}")
    for name in entry_list:
        print(f"  {name}")

    print(f"EXIT_COUNT={len(exit_list)}")
    print(f"TASKS_5Y={tasks}")


if __name__ == "__main__":
    main()
