"""Per-exit-reason breakdown for a given strategy combination.

Given a backtest trades CSV (produced by `evaluate` / `pos-evaluation`), aggregate
trades for a specific (entry_strategy, exit_strategy) pair and report a table of:

    exit_urgency | trades | share% | win% | avg_ret% | median_ret% | total_ret_jpy | avg_hold_days

Two scopes are supported:

* ``--scope events`` (default): every exit event counted (TP1 partial + final exits).
* ``--scope full_only``: keep only ``exit_is_full_exit==True`` rows. This counts
  one row per closed trade lifecycle.

Example (R=0.55, T=1.30, 4-year continuous, overlay OFF):

    python tools/exit_breakdown.py \
        --trades-csv "G:/My Drive/AI-Stock-Sync/strategy_evaluation/strategy_evaluation_continuous_trades_20260428_190647.csv" \
        --exit-strategy MVXW_N5_R0p55_T1p3_D10_B20p0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd


def load_trades(
    csv_path: Path,
    exit_strategy: str,
    entry_strategy: Optional[str] = None,
    period: Optional[str] = None,
) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    mask = df["exit_strategy"] == exit_strategy
    if entry_strategy:
        mask &= df["entry_strategy"] == entry_strategy
    if period:
        mask &= df["period"].astype(str) == str(period)
    out = df.loc[mask].copy()
    if out.empty:
        raise SystemExit(
            f"No trades found in {csv_path} for exit_strategy={exit_strategy}"
            + (f", entry_strategy={entry_strategy}" if entry_strategy else "")
            + (f", period={period}" if period else "")
        )
    return out


def breakdown_by_urgency(trades: pd.DataFrame, scope: str) -> pd.DataFrame:
    if scope == "full_only":
        df = trades[trades["exit_is_full_exit"].astype(bool)].copy()
    else:
        df = trades.copy()

    total_events = len(df)
    grouped = df.groupby("exit_urgency", dropna=False)
    rows = []
    for urgency, g in grouped:
        rows.append(
            {
                "exit_urgency": urgency if pd.notna(urgency) else "(none)",
                "trades": len(g),
                "share_pct": 100.0 * len(g) / total_events if total_events else 0.0,
                "win_pct": 100.0 * (g["return_pct"] > 0).mean(),
                "avg_ret_pct": g["return_pct"].mean(),
                "median_ret_pct": g["return_pct"].median(),
                "total_ret_jpy": g["return_jpy"].sum(),
                "avg_hold_days": g["holding_days"].mean(),
            }
        )

    summary = pd.DataFrame(rows).sort_values("trades", ascending=False).reset_index(drop=True)

    # Append TOTAL row.
    total_row = {
        "exit_urgency": "TOTAL",
        "trades": total_events,
        "share_pct": 100.0 if total_events else 0.0,
        "win_pct": 100.0 * (df["return_pct"] > 0).mean() if total_events else 0.0,
        "avg_ret_pct": df["return_pct"].mean() if total_events else 0.0,
        "median_ret_pct": df["return_pct"].median() if total_events else 0.0,
        "total_ret_jpy": df["return_jpy"].sum() if total_events else 0.0,
        "avg_hold_days": df["holding_days"].mean() if total_events else 0.0,
    }
    return pd.concat([summary, pd.DataFrame([total_row])], ignore_index=True)


def render_table(df: pd.DataFrame) -> str:
    fmt = {
        "share_pct": "{:.1f}%".format,
        "win_pct": "{:.1f}%".format,
        "avg_ret_pct": "{:+.2f}%".format,
        "median_ret_pct": "{:+.2f}%".format,
        "total_ret_jpy": "{:,.0f}".format,
        "avg_hold_days": "{:.1f}".format,
    }
    out = df.copy()
    for col, f in fmt.items():
        out[col] = out[col].map(f)
    return out.to_string(index=False)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--trades-csv", required=True, type=Path)
    p.add_argument("--exit-strategy", required=True)
    p.add_argument("--entry-strategy", default=None)
    p.add_argument("--period", default=None, help="Restrict to one period label (e.g. 2024).")
    p.add_argument(
        "--scope",
        choices=["events", "full_only"],
        default="events",
        help="events = count every exit event (TP1 partial + finals); "
        "full_only = only rows with exit_is_full_exit=True.",
    )
    p.add_argument("--csv-out", default=None, type=Path, help="Optional path to save the table.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    trades = load_trades(
        args.trades_csv,
        exit_strategy=args.exit_strategy,
        entry_strategy=args.entry_strategy,
        period=args.period,
    )

    print(f"trades_csv     = {args.trades_csv}")
    print(f"exit_strategy  = {args.exit_strategy}")
    if args.entry_strategy:
        print(f"entry_strategy = {args.entry_strategy}")
    if args.period:
        print(f"period         = {args.period}")
    print(f"scope          = {args.scope}")
    periods = sorted(trades["period"].astype(str).unique().tolist())
    print(f"periods        = {periods}")
    print(f"matched rows   = {len(trades)}")
    print()

    table = breakdown_by_urgency(trades, scope=args.scope)
    print(render_table(table))

    if args.csv_out:
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.csv_out, index=False, encoding="utf-8-sig")
        print(f"\n✅ saved: {args.csv_out}")


if __name__ == "__main__":
    sys.exit(main())
