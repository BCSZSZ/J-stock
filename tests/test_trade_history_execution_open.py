import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from web.api.routers import state as state_router


def test_trade_history_enriches_execution_day_open_and_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_file = tmp_path / "history.json"
    features_dir = tmp_path / "data" / "features"
    features_dir.mkdir(parents=True)

    history_file.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "events": [
                    {
                        "date": "2026-05-18",
                        "group_id": "group_main",
                        "ticker": "1111",
                        "action": "BUY",
                        "quantity": 10,
                        "price": 110.0,
                        "total_jpy": 1_100.0,
                    },
                    {
                        "date": "2026-05-18",
                        "group_id": "group_main",
                        "ticker": "2222",
                        "action": "SELL",
                        "quantity": 100,
                        "price": 99.0,
                        "total_jpy": 9_900.0,
                    },
                    {
                        "date": "2026-05-18",
                        "group_id": "group_main",
                        "ticker": "3333",
                        "action": "SELL",
                        "quantity": 100,
                        "price": 101.0,
                        "total_jpy": 10_100.0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    pd.DataFrame(
        {
            "Date": ["2026-05-16", "2026-05-18"],
            "Open": [99.0, 100.0],
        }
    ).to_parquet(features_dir / "1111_features.parquet")
    pd.DataFrame(
        {
            "Date": ["2026-05-18"],
            "Open": [100.0],
        }
    ).to_parquet(features_dir / "2222_features.parquet")

    monkeypatch.setattr(
        state_router,
        "get_production_config",
        lambda: SimpleNamespace(history_file=str(history_file)),
    )
    monkeypatch.setattr(state_router, "get_project_root", lambda: tmp_path)

    response = state_router.get_trade_history()

    events = response["events"]
    buy_event = events[0]
    sell_event = events[1]
    missing_event = events[2]
    summary = response["summary"]

    assert buy_event["benchmark_status"] == "AVAILABLE"
    assert buy_event["execution_open_price"] == 100.0
    assert buy_event["actual_vs_open_jpy"] == 10.0
    assert buy_event["actual_vs_open_pct"] == pytest.approx(10.0)
    assert buy_event["slippage_pct"] == pytest.approx(10.0)
    assert buy_event["slippage_bps"] == pytest.approx(1000.0)
    assert buy_event["slippage_direction"] == "WORSE"

    assert sell_event["benchmark_status"] == "AVAILABLE"
    assert sell_event["execution_open_price"] == 100.0
    assert sell_event["actual_vs_open_jpy"] == -1.0
    assert sell_event["actual_vs_open_pct"] == pytest.approx(-1.0)
    assert sell_event["slippage_pct"] == pytest.approx(1.0)
    assert sell_event["slippage_bps"] == pytest.approx(100.0)
    assert sell_event["slippage_direction"] == "WORSE"

    assert missing_event["benchmark_status"] == "MISSING_OPEN"
    assert missing_event["execution_open_price"] is None
    assert missing_event["slippage_pct"] is None

    assert summary["total_trades"] == 3
    assert summary["benchmarked_trades"] == 2
    assert summary["missing_open_trades"] == 1
    assert summary["capital_weighted_avg_slippage_pct_overall"] == pytest.approx(
        200.0 / 11_000.0 * 100.0
    )
    assert summary["capital_weighted_avg_slippage_pct_buy"] == pytest.approx(10.0)
    assert summary["capital_weighted_avg_slippage_pct_sell"] == pytest.approx(1.0)
    assert summary["avg_slippage_pct_overall"] == pytest.approx(5.5)
    assert summary["avg_slippage_pct_buy"] == pytest.approx(10.0)
    assert summary["avg_slippage_pct_sell"] == pytest.approx(1.0)
    assert summary["avg_abs_error_jpy"] == pytest.approx(5.5)
    assert summary["median_slippage_pct"] == pytest.approx(5.5)