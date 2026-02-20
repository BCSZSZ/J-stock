from datetime import datetime
from pathlib import Path
import sys
import argparse

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.portfolio_engine import PortfolioBacktestEngine
from src.evaluation.strategy_evaluator import StrategyEvaluator
from src.utils.strategy_loader import load_entry_strategy
from src.analysis.strategies.exit.multiview_grid_exit import MultiViewCompositeExit


def build_exit_name(n: int, r: float, t: float, d: int, b: int) -> str:
    return f"MVX_N{n}_R{str(r).replace('.', 'p')}_T{str(t).replace('.', 'p')}_D{d}_B{b}"


def parse_int_list(text: str) -> list[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


def parse_float_list(text: str) -> list[float]:
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate custom N/R grid across 5 years.")
    parser.add_argument("--n-values", default="6,7", help="Comma-separated N values, e.g. 6,7")
    parser.add_argument("--r-values", default="2.4,2.6", help="Comma-separated R values, e.g. 2.4,2.6")
    parser.add_argument("--t", type=float, default=2.2, help="Trailing ATR multiplier")
    parser.add_argument("--d", type=int, default=20, help="Time stop days")
    parser.add_argument("--b", type=int, default=15, help="Bias threshold pct")
    args = parser.parse_args()

    periods = [
        ("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025", "2025-01-01", "2025-12-31"),
    ]

    n_values = parse_int_list(args.n_values)
    r_values = parse_float_list(args.r_values)
    t = args.t
    d = args.d
    b = args.b

    evaluator = StrategyEvaluator(data_root="data", output_dir="strategy_evaluation", verbose=False)
    tickers = evaluator._load_monitor_list()
    entry = load_entry_strategy("MACDCrossoverStrategy")

    rows = []
    trade_rows = []

    for n in n_values:
        for r in r_values:
            name = build_exit_name(n, r, t, d, b)
            for period, start_date, end_date in periods:
                exit_strategy = MultiViewCompositeExit(
                    hist_shrink_n=n,
                    r_mult=r,
                    trail_mult=t,
                    time_stop_days=d,
                    bias_exit_threshold_pct=b,
                )
                exit_strategy.strategy_name = name

                engine = PortfolioBacktestEngine(
                    data_root="data",
                    starting_capital=5_000_000,
                    max_positions=5,
                )
                result = engine.backtest_portfolio_strategy(
                    tickers=tickers,
                    entry_strategy=entry,
                    exit_strategy=exit_strategy,
                    start_date=start_date,
                    end_date=end_date,
                    show_signal_ranking=False,
                )

                topix = evaluator._get_topix_return(start_date, end_date)
                alpha = None if topix is None else result.total_return_pct - topix

                rows.append(
                    {
                        "period": period,
                        "exit_strategy": name,
                        "N": n,
                        "R": r,
                        "T": t,
                        "D": d,
                        "B": b,
                        "return_pct": result.total_return_pct,
                        "topix_return_pct": topix,
                        "alpha": alpha,
                        "sharpe_ratio": result.sharpe_ratio,
                        "max_drawdown_pct": result.max_drawdown_pct,
                        "num_trades": result.num_trades,
                        "win_rate_pct": result.win_rate_pct,
                        "avg_gain_pct": result.avg_gain_pct,
                        "avg_loss_pct": result.avg_loss_pct,
                    }
                )

                for tr in result.trades:
                    trade_rows.append(
                        {
                            "period": period,
                            "exit_strategy": name,
                            "N": n,
                            "R": r,
                            "holding_days": tr.holding_days,
                            "return_pct": tr.return_pct,
                            "return_jpy": tr.return_jpy,
                            "exit_urgency": tr.exit_urgency,
                        }
                    )

    df = pd.DataFrame(rows)
    tdf = pd.DataFrame(trade_rows)

    summary = (
        df.groupby(["exit_strategy", "N", "R"], as_index=False)
        .agg(
            avg_return=("return_pct", "mean"),
            avg_alpha=("alpha", "mean"),
            avg_sharpe=("sharpe_ratio", "mean"),
            avg_mdd=("max_drawdown_pct", "mean"),
            avg_win_rate=("win_rate_pct", "mean"),
            total_trades=("num_trades", "sum"),
        )
        .sort_values("avg_return", ascending=False)
    )

    win_trades = tdf[tdf["return_pct"] > 0]
    loss_trades = tdf[tdf["return_pct"] <= 0]
    hold_summary = (
        tdf.groupby(["exit_strategy", "N", "R"], as_index=False)
        .agg(avg_hold=("holding_days", "mean"))
        .merge(
            win_trades.groupby(["exit_strategy", "N", "R"], as_index=False)
            .agg(avg_win_ret=("return_pct", "mean"), avg_win_hold=("holding_days", "mean")),
            on=["exit_strategy", "N", "R"],
            how="left",
        )
        .merge(
            loss_trades.groupby(["exit_strategy", "N", "R"], as_index=False)
            .agg(avg_loss_ret=("return_pct", "mean"), avg_loss_hold=("holding_days", "mean")),
            on=["exit_strategy", "N", "R"],
            how="left",
        )
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("strategy_evaluation")
    out_dir.mkdir(exist_ok=True)

    raw_path = out_dir / f"custom_nr_4x5_raw_{ts}.csv"
    summary_path = out_dir / f"custom_nr_4x5_summary_{ts}.csv"
    hold_path = out_dir / f"custom_nr_4x5_hold_{ts}.csv"
    trade_path = out_dir / f"custom_nr_4x5_trades_{ts}.csv"

    df.to_csv(raw_path, index=False)
    summary.to_csv(summary_path, index=False)
    hold_summary.to_csv(hold_path, index=False)
    tdf.to_csv(trade_path, index=False)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)

    print("=== Yearly Return Pivot ===")
    print(df.pivot(index="period", columns="exit_strategy", values="return_pct").round(4).to_string())
    print("\n=== Summary ===")
    print(summary.round(4).to_string(index=False))
    print("\n=== Holding/Return Profile ===")
    print(hold_summary.round(4).to_string(index=False))
    print("\nSaved files:")
    print(raw_path)
    print(summary_path)
    print(hold_path)
    print(trade_path)


if __name__ == "__main__":
    main()
