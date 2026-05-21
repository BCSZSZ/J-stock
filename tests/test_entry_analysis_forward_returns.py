import pandas as pd
import pytest

from src.entry_analysis.forward_returns import compute_forward_returns


def test_signal_close_forward_returns_use_trading_day_offsets() -> None:
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    frame = pd.DataFrame(
        {
            "Open": [99.0, 101.0, 103.0, 104.0],
            "Close": [100.0, 102.0, 104.0, 110.0],
        },
        index=dates,
    )

    result = compute_forward_returns(frame, signal_pos=0, horizons=[1, 3], label_mode="signal_close")

    assert result["label_entry_date"] == "2026-01-02"
    assert result["label_entry_price"] == 100.0
    assert result["forward_date_1d"] == "2026-01-05"
    assert result["forward_return_1d_pct"] == pytest.approx(2.0)
    assert result["forward_date_3d"] == "2026-01-07"
    assert result["forward_return_3d_pct"] == pytest.approx(10.0)


def test_next_open_forward_returns_start_from_next_trading_day_open() -> None:
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    frame = pd.DataFrame(
        {
            "Open": [99.0, 101.0, 103.0, 104.0],
            "Close": [100.0, 102.0, 104.0, 111.1],
        },
        index=dates,
    )

    result = compute_forward_returns(frame, signal_pos=0, horizons=[3, 5], label_mode="next_open")

    assert result["label_entry_date"] == "2026-01-05"
    assert result["label_entry_price"] == 101.0
    assert result["forward_return_3d_pct"] == pytest.approx(10.0)
    assert result["forward_missing_5d"] is True
    assert result["forward_return_5d_pct"] is None
