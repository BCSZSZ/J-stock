from datetime import datetime
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.portfolio_engine import PortfolioBacktestEngine
from src.evaluation.strategy_evaluator import StrategyEvaluator
from src.utils.strategy_loader import load_entry_strategy
from src.analysis.strategies.exit.multiview_grid_exit import MultiViewCompositeExit


class MultiViewCompositeExitWithFastNegCheck(MultiViewCompositeExit):
    """MVX variant with an additional fixed fast-negative MACD histogram check.

    This variant intentionally does not expose new external parameters. The thresholds
    are fixed constants for A/B validation only.
    """

    def _hist_shrinking(self, df_features: pd.DataFrame, n: int) -> bool:
        if super()._hist_shrinking(df_features, n):
            return True
        return self._fast_negative_check(df_features)

    @staticmethod
    def _fast_negative_check(df_features: pd.DataFrame) -> bool:
        hist = df_features["MACD_Hist"].dropna()
        if len(hist) < 20:
            return False

        h2 = float(hist.iloc[-3])
        h1 = float(hist.iloc[-2])
        h0 = float(hist.iloc[-1])

        sigma = float(hist.tail(20).std())
        if sigma <= 0:
            return False

        deadband = 0.15 * sigma
        min_drop = 0.80 * sigma

        recent_drop = h1 - h0
        prev_drop = h2 - h1

        crossed_to_negative = (h1 > deadband) and (h0 < -deadband)
        deepening_negative = (h1 < -deadband) and (h0 < h1)
        fast_drop = (recent_drop >= min_drop) and (prev_drop > 0)

        return bool((crossed_to_negative or deepening_negative) and fast_drop)


def run_variant(exit_strategy, name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    periods = [
        ("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025", "2025-01-01", "2025-12-31"),
    ]

    evaluator = StrategyEvaluator(data_root="data", output_dir="strategy_evaluation", verbose=False)
    tickers = evaluator._load_monitor_list()
    entry = load_entry_strategy("MACDCrossoverStrategy")

    rows = []
    trade_rows = []

    for period, start_date, end_date in periods:
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
                "variant": name,
                "period": period,
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
                    "variant": name,
                    "period": period,
                    "holding_days": tr.holding_days,
                    "return_pct": tr.return_pct,
                    "return_jpy": tr.return_jpy,
                    "exit_urgency": tr.exit_urgency,
                }
            )

    return pd.DataFrame(rows), pd.DataFrame(trade_rows)


def main() -> None:
    base = MultiViewCompositeExit(
        hist_shrink_n=10,
        r_mult=3.6,
        trail_mult=2.2,
        time_stop_days=20,
        bias_exit_threshold_pct=15,
    )
    base.strategy_name = "MVX_N10_R3p6_T2p2_D20_B15_BASE"

    with_check = MultiViewCompositeExitWithFastNegCheck(
        hist_shrink_n=10,
        r_mult=3.6,
        trail_mult=2.2,
        time_stop_days=20,
        bias_exit_threshold_pct=15,
    )
    with_check.strategy_name = "MVX_N10_R3p6_T2p2_D20_B15_WITH_CHECK"

    base_df, base_trades = run_variant(base, "NO_CHECK")
    check_df, check_trades = run_variant(with_check, "WITH_CHECK")

    raw = pd.concat([base_df, check_df], ignore_index=True)
    trades = pd.concat([base_trades, check_trades], ignore_index=True)

    summary = (
        raw.groupby("variant", as_index=False)
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

    hold = (
        trades.groupby("variant", as_index=False)
        .agg(avg_hold=("holding_days", "mean"))
        .merge(
            trades[trades["return_pct"] > 0]
            .groupby("variant", as_index=False)
            .agg(avg_win_ret=("return_pct", "mean"), avg_win_hold=("holding_days", "mean")),
            on="variant",
            how="left",
        )
        .merge(
            trades[trades["return_pct"] <= 0]
            .groupby("variant", as_index=False)
            .agg(avg_loss_ret=("return_pct", "mean"), avg_loss_hold=("holding_days", "mean")),
            on="variant",
            how="left",
        )
    )

    trigger = (
        trades.groupby(["variant", "exit_urgency"], as_index=False)
        .size()
        .sort_values(["variant", "size"], ascending=[True, False])
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("strategy_evaluation")
    out_dir.mkdir(exist_ok=True)

    raw_path = out_dir / f"n10r36_check_ab_raw_{ts}.csv"
    summary_path = out_dir / f"n10r36_check_ab_summary_{ts}.csv"
    hold_path = out_dir / f"n10r36_check_ab_hold_{ts}.csv"
    trade_path = out_dir / f"n10r36_check_ab_trades_{ts}.csv"
    trigger_path = out_dir / f"n10r36_check_ab_trigger_{ts}.csv"

    raw.to_csv(raw_path, index=False)
    summary.to_csv(summary_path, index=False)
    hold.to_csv(hold_path, index=False)
    trades.to_csv(trade_path, index=False)
    trigger.to_csv(trigger_path, index=False)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)

    print("=== Yearly Return Pivot ===")
    print(raw.pivot(index="period", columns="variant", values="return_pct").round(4).to_string())
    print("\n=== Summary ===")
    print(summary.round(4).to_string(index=False))
    print("\n=== Holding/Return Profile ===")
    print(hold.round(4).to_string(index=False))
    print("\n=== Trigger Counts ===")
    print(trigger.to_string(index=False))
    print("\nSaved files:")
    print(raw_path)
    print(summary_path)
    print(hold_path)
    print(trade_path)
    print(trigger_path)


if __name__ == "__main__":
    main()
