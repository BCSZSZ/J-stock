from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tools.score_evaluation_outputs import (
    discover_outputs,
    load_raw_panel,
    score_candidates,
    summarize_candidates,
)


def _write_raw(path: Path, entry: str, returns: list[float], mdds: list[float], win: float) -> None:
    rows = []
    for period, return_pct, mdd in zip(["2025", "2026"], returns, mdds, strict=True):
        rows.append(
            {
                "period": period,
                "entry_strategy": entry,
                "exit_strategy": "Exit",
                "entry_filter": "off",
                "return_pct": return_pct,
                "alpha": return_pct - 10.0,
                "sharpe_ratio": 4.0 if entry == "HighReturnFragile" else 3.0,
                "max_drawdown_pct": mdd,
                "num_trades": 10,
                "win_rate_pct": win,
                "atr_risk_per_trade_pct": 0.0108,
                "atr_stop_multiple": 0.60,
            }
        )
    frame = pd.DataFrame(rows)
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def test_global_output_score_merges_single_candidate_workers(tmp_path: Path) -> None:
    fragile_dir = tmp_path / "fragile"
    balanced_dir = tmp_path / "balanced"
    fragile_dir.mkdir()
    balanced_dir.mkdir()
    _write_raw(
        fragile_dir / "strategy_evaluation_raw_20260621_010000.parquet",
        "HighReturnFragile",
        [300.0, 300.0],
        [40.0, 50.0],
        50.0,
    )
    _write_raw(
        balanced_dir / "strategy_evaluation_raw_20260621_010001.csv",
        "Balanced",
        [200.0, 200.0],
        [5.0, 6.0],
        80.0,
    )
    summary_json = tmp_path / "summary.json"
    summary_json.write_text(
        json.dumps(
            {
                "workers": [
                    {
                        "worker_id": "fragile_worker",
                        "job_name": "fragile",
                        "output_dir": str(fragile_dir),
                    },
                    {
                        "worker_id": "balanced_worker",
                        "job_name": "balanced",
                        "output_dir": str(balanced_dir),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    outputs = discover_outputs(
        summary_json=summary_json,
        output_dirs=[],
        output_root=None,
        recursive=False,
    )
    raw_panel = load_raw_panel(outputs)
    summary = summarize_candidates(raw_panel)
    scored = score_candidates(summary)

    assert scored.iloc[0]["source_candidate_id"] == "balanced_worker"
    assert scored.iloc[0]["mdd_win_score"] > scored.iloc[1]["mdd_win_score"]
    assert scored.iloc[0]["recent_return"] == 200.0
