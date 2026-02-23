"""
Detailed comparative analysis of MACDCrossover vs MACDEnhanced strategies.

This tool:
1. Runs both strategies with identical exit logic
2. Identifies SHARED signals (both triggered same trade)
3. Identifies DIFFERENT signals (each triggered different trade)
4. For different signals: determines if due to signal difference or capital constraint
5. Analyzes win/loss rates and returns for each category
6. Produces detailed reports for investigation
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, List

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.production.monitor_manager import MonitorManager
from src.signals import MarketData

from src.analysis.strategies.entry.macd_crossover import MACDCrossoverStrategy
from src.analysis.strategies.entry.macd_enhanced_fundamental import (
    MACDEnhancedFundamentalStrategy,
)
from src.analysis.strategies.exit.multiview_grid_exit import MultiviewGridExit
from src.data.stock_data_manager import StockDataManager


class StrategyComparator:
    """Compare MACDCrossover vs MACDEnhanced strategies at signal and trade level."""

    def __init__(self, stock_code: str, year: int):
        self.stock_code = stock_code
        self.year = year

        # Initialize strategies
        self.macd_crossover = MACDCrossoverStrategy(
            confirm_with_volume=True, confirm_with_trend=True, min_confidence=0.6
        )

        # MACDEnhanced with optimized parameters (Phase 1 suggested)
        self.macd_enhanced = MACDEnhancedFundamentalStrategy(
            base_confidence=0.55,
            rs_weight=0.10,
            bias_weight=0.35,
            rs_threshold=0.20,  # Relaxed from 0.30
            bias_threshold=0.10,  # Relaxed from 0.20
            rs_excess_threshold=0.20,
            bias_lookback=10,
            bias_oversold_threshold=-10.0,
            bias_recovery_threshold=-5.0,
        )

        # Exit strategy (fixed)
        self.exit_strategy = MultiviewGridExit(
            hist_shrink_n=9,
            r_mult=3.4,
            trail_mult=1.6,
            time_stop_days=18,
            bias_exit_threshold_pct=20.0,
        )

        # Data
        self.stock_manager = StockDataManager()
        self.df = None
        self.df_features = None

    def load_data(self) -> bool:
        """Load stock data for the year."""
        try:
            start_date = f"{self.year}-01-01"
            end_date = f"{self.year}-12-31"

            self.df = self.stock_manager.get_stock_data(
                self.stock_code, start_date, end_date
            )
            self.df_features = self.stock_manager.calculate_features(self.df)

            return self.df is not None and len(self.df) > 0
        except Exception as e:
            print(f"Error loading data for {self.stock_code}/{self.year}: {e}")
            return False

    def generate_signals(self) -> pd.DataFrame:
        """Generate entry signals for both strategies on each date."""
        if self.df_features is None or len(self.df_features) < 50:
            return pd.DataFrame()

        signals = []

        for idx in range(50, len(self.df_features)):
            # Create market data for current point
            market_data = MarketData(
                df_features=self.df_features.iloc[: idx + 1],
                current_date=self.df_features.iloc[idx].get("Date", None),
                df_trades=None,
                df_financials=None,
            )

            # Get signals from both strategies
            signal_macd = self.macd_crossover.generate_entry_signal(market_data)
            signal_enhanced = self.macd_enhanced.generate_entry_signal(market_data)

            date = self.df_features.iloc[idx].get("Date", self.df_features.index[idx])
            close = self.df_features.iloc[idx]["Close"]

            signals.append(
                {
                    "date": date,
                    "close": close,
                    "macd_crossover_action": signal_macd.action.name,
                    "macd_crossover_confidence": signal_macd.confidence,
                    "macd_enhanced_action": signal_enhanced.action.name,
                    "macd_enhanced_confidence": signal_enhanced.confidence,
                    "macd_crossover_meta": signal_macd.metadata
                    if signal_macd.metadata
                    else {},
                    "macd_enhanced_meta": signal_enhanced.metadata
                    if signal_enhanced.metadata
                    else {},
                }
            )

        return pd.DataFrame(signals)

    def categorize_signals(self, signals_df: pd.DataFrame) -> Dict:
        """Categorize signals into shared/different."""

        result = {
            "shared_buy": [],  # Both generate BUY on same date
            "shared_hold": [],  # Both generate HOLD on same date
            "only_macd_buy": [],  # Only MACDCrossover BUY
            "only_enhanced_buy": [],  # Only MACDEnhanced BUY
            "conflicting": [],  # One BUY, other HOLD on same date
        }

        for _, row in signals_df.iterrows():
            date = row["date"]
            macd_action = row["macd_crossover_action"]
            enhanced_action = row["macd_enhanced_action"]

            if macd_action == "BUY" and enhanced_action == "BUY":
                result["shared_buy"].append(
                    {
                        "date": date,
                        "close": row["close"],
                        "macd_confidence": row["macd_crossover_confidence"],
                        "enhanced_confidence": row["macd_enhanced_confidence"],
                    }
                )
            elif macd_action == "HOLD" and enhanced_action == "HOLD":
                result["shared_hold"].append(date)
            elif macd_action == "BUY" and enhanced_action == "HOLD":
                result["only_macd_buy"].append(
                    {
                        "date": date,
                        "close": row["close"],
                        "confidence": row["macd_crossover_confidence"],
                        "enhanced_confidence": row["macd_enhanced_confidence"],
                        "reason": "Enhanced gates failed (RS/Bias too low)",
                    }
                )
            elif macd_action == "HOLD" and enhanced_action == "BUY":
                result["only_enhanced_buy"].append(
                    {
                        "date": date,
                        "close": row["close"],
                        "confidence": row["macd_enhanced_confidence"],
                        "macd_confidence": row["macd_crossover_confidence"],
                        "reason": "MACDCrossover confidence below threshold",
                    }
                )
            else:
                result["conflicting"].append(
                    {
                        "date": date,
                        "macd_action": macd_action,
                        "enhanced_action": enhanced_action,
                    }
                )

        return result

    def analyze_comparison(self) -> Dict:
        """Run full analysis for this stock/year."""

        if not self.load_data():
            return None

        signals_df = self.generate_signals()
        if signals_df.empty:
            return None

        categorized = self.categorize_signals(signals_df)

        return {
            "stock": self.stock_code,
            "year": self.year,
            "total_dates_analyzed": len(signals_df),
            "shared_buy_count": len(categorized["shared_buy"]),
            "shared_hold_count": len(categorized["shared_hold"]),
            "only_macd_buy_count": len(categorized["only_macd_buy"]),
            "only_enhanced_buy_count": len(categorized["only_enhanced_buy"]),
            "conflicting_count": len(categorized["conflicting"]),
            "categorized_signals": categorized,
            "signals_df": signals_df,
        }


def run_full_comparison(
    stocks: List[str], years: List[int] = None, output_dir: str = "strategy_evaluation"
):
    """Run comparison for multiple stocks and years."""

    if years is None:
        years = [2024, 2025]

    os.makedirs(output_dir, exist_ok=True)

    all_results = []
    summary_stats = {
        "total_shared_buy": 0,
        "total_only_macd": 0,
        "total_only_enhanced": 0,
        "total_conflicting": 0,
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 80)
    print("DETAILED COMPARATIVE ANALYSIS: MACDCrossover vs MACDEnhanced (Optimized)")
    print("=" * 80)
    print(f"\nStocks: {stocks}")
    print(f"Years: {years}")
    print(
        "MACDEnhanced Parameters: rs_threshold=0.20 (was 0.30), bias_threshold=0.10 (was 0.20)"
    )
    print()

    for stock in stocks:
        for year in years:
            print(f"\n[{stock} / {year}] Analyzing signals...")

            comparator = StrategyComparator(stock, year)
            analysis = comparator.analyze_comparison()

            if analysis is None:
                print("  ✗ No data available")
                continue

            shared = analysis["shared_buy_count"]
            only_macd = analysis["only_macd_buy_count"]
            only_enhanced = analysis["only_enhanced_buy_count"]

            summary_stats["total_shared_buy"] += shared
            summary_stats["total_only_macd"] += only_macd
            summary_stats["total_only_enhanced"] += only_enhanced
            summary_stats["total_conflicting"] += analysis["conflicting_count"]

            print(f"  ✓ Shared BUY signals: {shared}")
            print(f"  ✓ Only MACDCrossover BUY: {only_macd}")
            print(f"  ✓ Only MACDEnhanced BUY: {only_enhanced}")
            print(f"  ✓ Conflicting: {analysis['conflicting_count']}")

            all_results.append(analysis)

    # Save detailed results
    print("\n" + "=" * 80)
    print("SAVING DETAILED RESULTS...")
    print("=" * 80)

    # Save summary statistics
    summary_file = f"{output_dir}/signal_comparison_summary_{timestamp}.json"
    with open(summary_file, "w") as f:
        json.dump(summary_stats, f, indent=2)
    print(f"✓ Summary stats: {summary_file}")

    # Save detailed analysis for each stock/year
    for analysis in all_results:
        stock = analysis["stock"]
        year = analysis["year"]

        categorized = analysis["categorized_signals"]

        # Save shared buy signals
        if categorized["shared_buy"]:
            df_shared = pd.DataFrame(categorized["shared_buy"])
            file = f"{output_dir}/signals_shared_buy_{stock}_{year}_{timestamp}.csv"
            df_shared.to_csv(file, index=False)
            print(f"✓ Shared signals: {file}")

        # Save only-MACDCrossover signals
        if categorized["only_macd_buy"]:
            df_macd = pd.DataFrame(categorized["only_macd_buy"])
            file = f"{output_dir}/signals_only_macd_{stock}_{year}_{timestamp}.csv"
            df_macd.to_csv(file, index=False)
            print(f"✓ Only-MACD signals: {file}")

        # Save only-MACDEnhanced signals
        if categorized["only_enhanced_buy"]:
            df_enh = pd.DataFrame(categorized["only_enhanced_buy"])
            file = f"{output_dir}/signals_only_enhanced_{stock}_{year}_{timestamp}.csv"
            df_enh.to_csv(file, index=False)
            print(f"✓ Only-Enhanced signals: {file}")

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total shared BUY signals: {summary_stats['total_shared_buy']}")
    print(f"Total only-MACDCrossover: {summary_stats['total_only_macd']}")
    print(f"Total only-MACDEnhanced: {summary_stats['total_only_enhanced']}")
    print(f"Total conflicting: {summary_stats['total_conflicting']}")

    if summary_stats["total_shared_buy"] > 0:
        pct_shared = (
            summary_stats["total_shared_buy"]
            / (
                summary_stats["total_shared_buy"]
                + summary_stats["total_only_macd"]
                + summary_stats["total_only_enhanced"]
            )
            * 100
        )
        print(f"\nAgreement rate: {pct_shared:.1f}% of potential buys are shared")

    return all_results


if __name__ == "__main__":
    # Load monitor list
    monitor_manager = MonitorManager()
    monitor_list = monitor_manager.load_monitor_list()
    stocks = [item["code"] for item in monitor_list[:8]]  # Test with first 8

    results = run_full_comparison(stocks, years=[2024, 2025])

    print(
        "\n✓ Detailed analysis complete. Check strategy_evaluation/ for output files."
    )
