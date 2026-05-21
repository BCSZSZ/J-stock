import json
from pathlib import Path

import pandas as pd

from src.evaluation.trade_indicator_enrichment import (
    DEFAULT_INDICATOR_COLUMNS,
    enrich_trades_with_indicators,
)


def _write_features(data_root: Path, ticker: str) -> None:
    features_dir = data_root / "features"
    features_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(
                ["2025-01-09", "2025-01-10", "2025-01-20", "2025-01-21"]
            ),
            "RSI": [48.0, 52.0, 61.0, 58.0],
            "RSI_9": [47.0, 53.0, 62.0, 59.0],
            "RSI_14": [48.0, 52.0, 61.0, 58.0],
            "RSI_22": [49.0, 51.0, 60.0, 57.0],
            "EMA_20": [100.0, 101.0, 108.0, 109.0],
            "EMA_50": [98.0, 99.0, 104.0, 105.0],
            "EMA_200": [90.0, 90.5, 94.0, 94.5],
            "ATR": [2.0, 2.1, 2.5, 2.4],
            "ADX_14": [18.0, 19.0, 25.0, 24.0],
            "MACD": [0.1, 0.2, 0.8, 0.7],
            "MACD_Signal": [0.0, 0.1, 0.6, 0.65],
            "MACD_Hist": [0.1, 0.1, 0.2, 0.05],
        }
    )
    df.to_parquet(features_dir / f"{ticker}_features.parquet", index=False)


def test_enrich_trades_with_indicators_maps_signal_and_execution_dates(tmp_path):
    data_root = tmp_path / "data"
    _write_features(data_root, "7203")
    trades_csv = tmp_path / "trades.csv"
    pd.DataFrame(
        [
            {
                "ticker": "7203",
                "entry_date": "2025-01-10",
                "entry_metadata_json": json.dumps({"entry_signal_date": "2025-01-09"}),
                "exit_date": "2025-01-21",
                "exit_metadata_json": json.dumps({"exit_signal_date": "2025-01-20"}),
                "return_pct": 5.0,
            }
        ]
    ).to_csv(trades_csv, index=False)

    enriched = enrich_trades_with_indicators(
        trades_csv=trades_csv,
        data_root=data_root,
        indicator_columns=DEFAULT_INDICATOR_COLUMNS,
    )
    row = enriched.iloc[0]

    assert row["entry_signal_RSI"] == 48.0
    assert row["entry_exec_RSI"] == 52.0
    assert row["exit_signal_EMA_20"] == 108.0
    assert row["exit_exec_EMA_200"] == 94.5
    assert row["entry_signal_indicator_valid_count"] == len(DEFAULT_INDICATOR_COLUMNS)
    assert row["exit_exec_indicator_quality"] == 1.0


def test_enrich_trades_with_indicators_preserves_rows_when_features_missing(tmp_path):
    trades_csv = tmp_path / "trades.csv"
    pd.DataFrame(
        [
            {
                "ticker": "9999",
                "entry_date": "2025-01-10",
                "entry_metadata_json": "{}",
                "exit_date": "2025-01-21",
                "exit_metadata_json": "{}",
                "return_pct": -2.0,
            }
        ]
    ).to_csv(trades_csv, index=False)

    enriched = enrich_trades_with_indicators(
        trades_csv=trades_csv,
        data_root=tmp_path / "data",
        indicator_columns=("RSI", "EMA_20"),
    )
    row = enriched.iloc[0]

    assert len(enriched) == 1
    assert bool(row["entry_exec_feature_found"]) is False
    assert row["entry_exec_indicator_missing_count"] == 2
    assert pd.isna(row["entry_exec_RSI"])