"""
Grid search for MACDEnhancedFundamental strategy optimization.

Phase 1: Entry Gate Threshold Testing
Goal: Find optimal rs_threshold and bias_threshold to recover alpha gap

Testing combinations of:
- rs_threshold: [0.10, 0.15, 0.20, 0.25, 0.30]
- bias_threshold: [0.05, 0.10, 0.15, 0.20]

Each combination tested on 5-year backtest (2021-2025) for each holding.

Expected outcome: 20-30 combination variants with alpha 15-22%
Target: rs_threshold=0.20, bias_threshold=0.10 expected to achieve ~19-21% alpha
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.backtest.portfolio_backtest import PortfolioBacktester
from src.production.monitor_manager import MonitorManager

from src.analysis.strategies.entry.macd_enhanced_fundamental import (
    MACDEnhancedFundamentalStrategy,
)
from src.analysis.strategies.exit.multiview_grid_exit import MultiviewGridExit


def run_grid_search(
    years: list = None, output_prefix: str = "macd_enhanced_grid_search"
):
    """
    Run grid search for MACD Enhanced parameter optimization.

    Args:
        years: List of years to test (default: [2021, 2022, 2023, 2024, 2025])
        output_prefix: Output file prefix
    """
    if years is None:
        years = [2021, 2022, 2023, 2024, 2025]

    # Phase 1: Entry gate parameters
    rs_thresholds = [0.10, 0.15, 0.20, 0.25, 0.30]
    bias_thresholds = [0.05, 0.10, 0.15, 0.20]

    # Keep all other parameters at current defaults
    base_confidence = 0.55
    rs_weight = 0.10
    bias_weight = 0.35
    rs_excess_threshold = 0.20
    bias_lookback = 10
    bias_oversold_threshold = -10.0
    bias_recovery_threshold = -5.0

    # Exit strategy (fixed)
    exit_strategy = MultiviewGridExit(
        hist_shrink_n=9,
        r_mult=3.4,
        trail_mult=1.6,
        time_stop_days=18,
        bias_exit_threshold_pct=20.0,
    )

    # Load monitor list
    monitor_manager = MonitorManager()
    monitor_list = monitor_manager.load_monitor_list()
    stocks = [item["code"] for item in monitor_list[:7]]  # Test with first 7

    results = []
    total_combinations = len(rs_thresholds) * len(bias_thresholds)
    current_combo = 0

    print(f"Grid Search: {total_combinations} parameter combinations")
    print(f"Testing stocks: {stocks}")
    print(f"Years: {years}")
    print("-" * 80)

    # Iterate through all combinations
    for rs_thresh in rs_thresholds:
        for bias_thresh in bias_thresholds:
            current_combo += 1
            print(
                f"\n[{current_combo}/{total_combinations}] Testing rs_threshold={rs_thresh}, bias_threshold={bias_thresh}"
            )

            # Create strategy instance with current parameters
            entry_strategy = MACDEnhancedFundamentalStrategy(
                base_confidence=base_confidence,
                rs_weight=rs_weight,
                bias_weight=bias_weight,
                rs_threshold=rs_thresh,
                bias_threshold=bias_thresh,
                rs_excess_threshold=rs_excess_threshold,
                bias_lookback=bias_lookback,
                bias_oversold_threshold=bias_oversold_threshold,
                bias_recovery_threshold=bias_recovery_threshold,
            )

            # Run backtest for this combination
            combo_results = {
                "rs_threshold": rs_thresh,
                "bias_threshold": bias_thresh,
                "combination_id": f"rs{rs_thresh:.2f}_bias{bias_thresh:.2f}",
            }

            # Test across each year
            year_returns = []
            year_alpha = []
            year_sharpe = []
            year_trades = []

            for year in years:
                try:
                    # Initialize backtest for this year
                    backtester = PortfolioBacktester(
                        start_date=f"{year}-01-01",
                        end_date=f"{year}-12-31",
                        entry_strategy=entry_strategy,
                        exit_strategy=exit_strategy,
                        max_positions=7,
                        max_position_pct=0.18,
                        min_position_pct=0.05,
                    )

                    # Run backtest
                    reports = []
                    for stock in stocks:
                        try:
                            report = backtester.run_backtest(stock)
                            if report:
                                reports.append(report)
                        except Exception as e:
                            print(f"  Error backtesting {stock} for {year}: {e}")
                            continue

                    # Aggregate results for this year
                    if reports:
                        total_return = np.mean(
                            [r.get("total_return", 0) for r in reports]
                        )
                        alpha = np.mean([r.get("alpha", 0) for r in reports])
                        sharpe = np.mean([r.get("sharpe_ratio", 0) for r in reports])
                        trades = sum([r.get("num_trades", 0) for r in reports])

                        year_returns.append(total_return)
                        year_alpha.append(alpha)
                        year_sharpe.append(sharpe)
                        year_trades.append(trades)

                        print(
                            f"  {year}: Return={total_return * 100:.2f}%, Alpha={alpha * 100:.2f}%, Sharpe={sharpe:.3f}, Trades={trades}"
                        )

                except Exception as e:
                    print(f"  Error in backtest for {year}: {e}")
                    continue

            # Aggregate across all years
            if year_returns:
                combo_results["avg_return"] = np.mean(year_returns)
                combo_results["avg_alpha"] = np.mean(year_alpha)
                combo_results["avg_sharpe"] = np.mean(year_sharpe)
                combo_results["total_trades"] = sum(year_trades)
                combo_results["std_return"] = np.std(year_returns)
                combo_results["min_return"] = np.min(year_returns)
                combo_results["max_return"] = np.max(year_returns)

                results.append(combo_results)

                print(
                    f"  ✓ Summary: Alpha={combo_results['avg_alpha'] * 100:.2f}%, "
                    f"Return={combo_results['avg_return'] * 100:.2f}%, "
                    f"Sharpe={combo_results['avg_sharpe']:.3f}"
                )
            else:
                print("  ✗ No results for this combination")

    # Save results
    if results:
        df_results = pd.DataFrame(results)
        df_results = df_results.sort_values("avg_alpha", ascending=False)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"strategy_evaluation/{output_prefix}_{timestamp}.csv"
        os.makedirs("strategy_evaluation", exist_ok=True)
        df_results.to_csv(output_file, index=False)

        print("\n" + "=" * 80)
        print("RESULTS SUMMARY (sorted by avg_alpha):")
        print("=" * 80)
        print(
            df_results[
                [
                    "combination_id",
                    "rs_threshold",
                    "bias_threshold",
                    "avg_alpha",
                    "avg_return",
                    "avg_sharpe",
                    "total_trades",
                ]
            ].to_string(index=False)
        )

        print(f"\n✓ Results saved to {output_file}")

        # Find top 3
        print("\n" + "=" * 80)
        print("TOP 3 COMBINATIONS:")
        print("=" * 80)
        for idx, (_, row) in enumerate(df_results.head(3).iterrows(), 1):
            print(
                f"\n#{idx}. rs_threshold={row['rs_threshold']:.2f}, bias_threshold={row['bias_threshold']:.2f}"
            )
            print(
                f"   Alpha: {row['avg_alpha'] * 100:.2f}% | Return: {row['avg_return'] * 100:.2f}% | "
                f"Sharpe: {row['avg_sharpe']:.3f}"
            )

        return df_results
    else:
        print("No results to save")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grid search MACD Enhanced parameters")
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=[2021, 2022, 2023, 2024, 2025],
        help="Years to test",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="macd_enhanced_grid_search",
        help="Output file prefix",
    )

    args = parser.parse_args()

    print("MACD Enhanced Fundamental - Phase 1: Entry Gate Optimization")
    print(f"Start time: {datetime.now()}")

    results_df = run_grid_search(years=args.years, output_prefix=args.output)

    print(f"\nEnd time: {datetime.now()}")
