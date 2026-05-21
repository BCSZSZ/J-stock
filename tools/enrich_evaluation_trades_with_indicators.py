import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.trade_indicator_enrichment import (
    DEFAULT_INDICATOR_COLUMNS,
    resolve_indicator_columns,
    write_enriched_trades_sidecar,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich evaluation trade CSVs with entry/exit daily feature snapshots."
    )
    parser.add_argument("--trades-csv", required=True, help="Evaluation trades CSV path")
    parser.add_argument("--data-root", default="data", help="Data root containing features/")
    parser.add_argument("--output", default="", help="Output CSV path; defaults next to trades CSV")
    parser.add_argument(
        "--indicator-columns",
        nargs="*",
        default=None,
        help="Feature columns to join; supports space-separated values or comma-separated groups",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    trades_csv = Path(args.trades_csv)
    data_root = Path(args.data_root)
    output_path = Path(args.output) if args.output else None
    indicator_columns = resolve_indicator_columns(args.indicator_columns)

    saved_path = write_enriched_trades_sidecar(
        trades_csv=trades_csv,
        data_root=data_root,
        output_path=output_path,
        indicator_columns=indicator_columns,
    )
    print(f"Saved enriched trades: {saved_path}")
    print(f"Indicators: {len(indicator_columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())