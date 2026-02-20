from datetime import datetime
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.portfolio_engine import PortfolioBacktestEngine
from src.evaluation.strategy_evaluator import StrategyEvaluator
from src.utils.strategy_loader import load_entry_strategy, load_exit_strategy


def summarize_trades(df: pd.DataFrame) -> pd.Series:
    wins = df[df["return_pct"] > 0]
    losses = df[df["return_pct"] <= 0]

    avg_win_ret = wins["return_pct"].mean() if len(wins) else 0.0
    avg_loss_ret = losses["return_pct"].mean() if len(losses) else 0.0
    avg_win_hold = wins["holding_days"].mean() if len(wins) else 0.0
    avg_loss_hold = losses["holding_days"].mean() if len(losses) else 0.0
    gross_win = wins["return_jpy"].sum()
    gross_loss = -losses["return_jpy"].sum()

    wl_return_ratio = (abs(avg_loss_ret) / avg_win_ret) if avg_win_ret > 0 else float("inf")
    wl_hold_ratio = (avg_loss_hold / avg_win_hold) if avg_win_hold > 0 else float("inf")
    exit_asymmetry_index = wl_return_ratio * wl_hold_ratio

    return pd.Series(
        {
            "trades": len(df),
            "win_rate": (len(wins) / len(df) * 100) if len(df) else 0.0,
            "avg_win_ret": avg_win_ret,
            "avg_loss_ret": avg_loss_ret,
            "avg_win_hold": avg_win_hold,
            "avg_loss_hold": avg_loss_hold,
            "gross_win_jpy": gross_win,
            "gross_loss_jpy": gross_loss,
            "profit_factor_jpy": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
            "wl_return_ratio": wl_return_ratio,
            "wl_hold_ratio": wl_hold_ratio,
            "exit_asymmetry_index": exit_asymmetry_index,
        }
    )


def main() -> None:
    periods = [
        ("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025", "2025-01-01", "2025-12-31"),
    ]

    entry_name = "MACDCrossoverStrategy"
    exit_names = ["MVX_N4_R1p8_T2p2_D20_B15", "ScoreBasedExitStrategy"]

    evaluator = StrategyEvaluator(data_root="data", output_dir="strategy_evaluation", verbose=False)
    tickers = evaluator._load_monitor_list()
    entry_strategy = load_entry_strategy(entry_name)

    trade_rows = []
    result_rows = []

    for exit_name in exit_names:
        exit_strategy = load_exit_strategy(exit_name)
        for period_label, start_date, end_date in periods:
            engine = PortfolioBacktestEngine(
                data_root="data",
                starting_capital=5_000_000,
                max_positions=5,
            )
            result = engine.backtest_portfolio_strategy(
                tickers=tickers,
                entry_strategy=entry_strategy,
                exit_strategy=exit_strategy,
                start_date=start_date,
                end_date=end_date,
                show_signal_ranking=False,
            )

            result_rows.append(
                {
                    "strategy": exit_name,
                    "period": period_label,
                    "total_return_pct": result.total_return_pct,
                    "num_trades": result.num_trades,
                    "win_rate_pct": result.win_rate_pct,
                    "avg_gain_pct": result.avg_gain_pct,
                    "avg_loss_pct": result.avg_loss_pct,
                }
            )

            for trade in result.trades:
                trade_rows.append(
                    {
                        "strategy": exit_name,
                        "period": period_label,
                        "ticker": trade.ticker,
                        "entry_date": trade.entry_date,
                        "exit_date": trade.exit_date,
                        "holding_days": trade.holding_days,
                        "return_pct": trade.return_pct,
                        "return_jpy": trade.return_jpy,
                        "exit_urgency": trade.exit_urgency,
                        "exit_reason": trade.exit_reason,
                        "is_win": trade.return_pct > 0,
                    }
                )

    trades = pd.DataFrame(trade_rows)
    results = pd.DataFrame(result_rows)

    summary_all = trades.groupby("strategy").apply(summarize_trades).reset_index()
    summary_by_year = trades.groupby(["strategy", "period"]).apply(summarize_trades).reset_index()
    summary_2024_2025 = (
        trades[trades["period"].isin(["2024", "2025"])]
        .groupby("strategy")
        .apply(summarize_trades)
        .reset_index()
    )

    out_dir = Path("strategy_evaluation")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    path_summary = out_dir / f"mvx_vs_score_selltiming_summary_{ts}.csv"
    path_focus = out_dir / f"mvx_vs_score_selltiming_2024_2025_{ts}.csv"
    path_year = out_dir / f"mvx_vs_score_selltiming_by_year_{ts}.csv"

    summary_all.to_csv(path_summary, index=False)
    summary_2024_2025.to_csv(path_focus, index=False)
    summary_by_year.to_csv(path_year, index=False)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)

    print("=== OVERALL ===")
    print(summary_all.round(4).to_string(index=False))
    print("\n=== 2024-2025 FOCUS ===")
    print(summary_2024_2025.round(4).to_string(index=False))
    print("\n=== RETURN PIVOT ===")
    print(
        results.pivot(index="period", columns="strategy", values="total_return_pct")
        .round(4)
        .to_string()
    )
    print("\nSaved files:")
    print(path_summary)
    print(path_focus)
    print(path_year)


if __name__ == "__main__":
    main()
