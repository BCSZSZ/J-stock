from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from src.analysis.macd_segment_analysis import (
    normalize_ticker_inputs,
    run_multi_ticker_macd_segment_analysis,
    save_macd_segment_analysis_outputs,
)
from src.config.runtime import get_config_file_path
from src.config.service import load_config


def _build_parser(default_data_root: str, default_output_dir: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze MACD bullish segments and compare MACD-only sell rules for one or more tickers."
    )
    parser.add_argument(
        "--ticker",
        action="append",
        default=[],
        help="Ticker code to analyze. Can be repeated.",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated ticker list, e.g. 1321,7203,6758",
    )
    parser.add_argument(
        "--data-root",
        default=default_data_root,
        help="Data root containing raw_prices/ and features/",
    )
    parser.add_argument(
        "--output-dir",
        default=default_output_dir,
        help="Directory where CSV outputs will be written",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=1825,
        help="Target history window in calendar days",
    )
    return parser


def _load_defaults() -> tuple[str, str]:
    config_path = get_config_file_path()
    config = load_config(str(config_path)) if config_path.exists() else {}
    default_data_root = str(config.get("data", {}).get("data_dir", "data") or "data")
    default_output_dir = str(
        config.get("evaluation", {}).get("output_dir", "strategy_evaluation")
        or "strategy_evaluation"
    )
    return default_data_root, default_output_dir


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()

    default_data_root, default_output_dir = _load_defaults()
    parser = _build_parser(default_data_root, default_output_dir)
    args = parser.parse_args()

    tickers = normalize_ticker_inputs(args.ticker, args.tickers)
    if not tickers:
        parser.error("Please provide at least one ticker via --ticker or --tickers")

    analysis_result = run_multi_ticker_macd_segment_analysis(
        tickers=tickers,
        data_root=args.data_root,
        lookback_days=args.lookback_days,
        api_key=os.getenv("JQUANTS_API_KEY"),
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    files = save_macd_segment_analysis_outputs(
        analysis_result,
        output_dir=args.output_dir,
        timestamp=timestamp,
    )

    readiness_df = analysis_result["final_readiness"]
    summary_df = analysis_result["summary_by_ticker"]
    rule_summary_df = analysis_result["rule_summary"]
    overall_rules = rule_summary_df[rule_summary_df["ticker"] == "__ALL__"].copy()
    overall_rules = overall_rules.sort_values(
        ["avg_capture_high_ratio", "avg_return_pct"],
        ascending=[False, False],
    )

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)

    print("=== READINESS ===")
    print(readiness_df.to_string(index=False))
    print("\n=== SEGMENT SUMMARY BY TICKER ===")
    print(summary_df.round(4).to_string(index=False))
    print("\n=== OVERALL RULE RANKING ===")
    print(overall_rules.round(4).to_string(index=False))
    print("\nSaved files:")
    for key, path in files.items():
        print(f"- {key}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())