from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.artifacts.tabular import read_table_auto, write_large_artifact


def test_write_large_artifact_defaults_to_parquet_only(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "event_row": [1, None],
            "entry_strategy": ["EntryA", "EntryA"],
            "return_pct": [1.2, -0.5],
        }
    )

    written = write_large_artifact(frame, tmp_path / "events.csv", "parquet")

    assert written["csv"] is None
    assert written["parquet"] == tmp_path / "events.parquet"
    assert not (tmp_path / "events.csv").exists()
    loaded = read_table_auto(written["parquet"])
    assert list(loaded["entry_strategy"]) == ["EntryA", "EntryA"]


def test_write_large_artifact_supports_csv_and_both(tmp_path: Path) -> None:
    frame = pd.DataFrame({"ticker": ["7203"], "rank": [1]})

    csv_written = write_large_artifact(frame, tmp_path / "csv_only.parquet", "csv")
    assert csv_written["csv"] == tmp_path / "csv_only.csv"
    assert csv_written["parquet"] is None
    assert read_table_auto(csv_written["csv"]).iloc[0]["ticker"] == 7203

    both_written = write_large_artifact(frame, tmp_path / "both.csv", "both")
    assert both_written["csv"] == tmp_path / "both.csv"
    assert both_written["parquet"] == tmp_path / "both.parquet"
    assert both_written["csv"].exists()
    assert both_written["parquet"].exists()
