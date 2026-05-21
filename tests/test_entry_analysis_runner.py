from datetime import date
from pathlib import Path

import pandas as pd

from src.entry_analysis.models import EntryAnalysisRequest
from src.entry_analysis.runner import run_entry_analysis


def test_run_entry_analysis_writes_dataset_manifest_without_rules(tmp_path, monkeypatch) -> None:
    import src.entry_analysis.runner as runner

    candidates = pd.DataFrame(
        {
            "entry_strategy": ["FakeEntry"],
            "ticker": ["7203"],
            "signal_date": ["2026-01-05"],
            "action": ["BUY"],
            "confidence": [0.8],
            "score": [77.0],
            "reasons_json": ["[]"],
            "metadata_json": ["{}"],
            "RSI": [55.0],
            "ADX_14": [22.0],
            "forward_date_5d": ["2026-01-13"],
            "forward_price_5d": [105.0],
            "forward_return_5d_pct": [5.0],
            "forward_missing_5d": [False],
        }
    )
    monkeypatch.setattr(runner, "scan_entry_signals", lambda _request, _columns: candidates)

    request = EntryAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        horizons=[5],
        rules=[],
        output_dir=str(tmp_path),
    )

    summary = run_entry_analysis(request)

    manifest_path = Path(summary.artifacts.manifest_json)
    assert summary.candidate_count == 1
    assert summary.aggregate_count == 0
    assert summary.artifacts.aggregates_csv is None
    assert Path(summary.artifacts.candidates_csv).exists()
    assert manifest_path.exists()
    assert "RSI" in manifest_path.read_text(encoding="utf-8")