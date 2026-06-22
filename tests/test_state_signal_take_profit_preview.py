import json
from types import SimpleNamespace

import pytest

from web.api.routers import state as state_router


def test_get_signals_enriches_buy_take_profit_preview(tmp_path, monkeypatch) -> None:
    signal_file = tmp_path / "2026-06-19.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "group_id": "group_main",
                    "ticker": "7203",
                    "signal_type": "BUY",
                    "close_price": 1000.0,
                    "planned_price": 1020.0,
                    "signal_metadata": {"ATR": 50.0},
                },
                {
                    "group_id": "group_main",
                    "ticker": "6758",
                    "signal_type": "SELL",
                    "close_price": 2000.0,
                },
            ]
        ),
        encoding="utf-8",
    )
    cfg = SimpleNamespace(
        signal_file_pattern=str(tmp_path / "{date}.json"),
        default_exit_strategy="MVXWL_N3_R0p54_T1p0_D14_B20p0_I0p55",
        strategy_groups=[
            {
                "id": "group_main",
                "exit_strategy": "MVXWL_N3_R0p54_T1p0_D14_B20p0_I0p55",
            }
        ],
    )
    monkeypatch.setattr(state_router, "get_production_config", lambda: cfg)

    signals = state_router.get_signals("2026-06-19")

    buy = signals[0]
    assert buy["tp_preview_available"] is True
    assert buy["tp_reference_price"] == pytest.approx(1000.0)
    assert buy["tp_assumed_entry_price"] == pytest.approx(1020.0)
    assert buy["tp_r_value"] == pytest.approx(27.0)
    assert buy["tp1_price"] == pytest.approx(1027.0)
    assert buy["tp2_price"] == pytest.approx(1054.0)
    assert buy["tp2_gain_pct"] == pytest.approx((1054.0 - 1020.0) / 1020.0 * 100.0)
    assert "tp2_price" not in signals[1]


def test_get_signals_can_estimate_take_profit_from_atr_ratio(
    tmp_path, monkeypatch
) -> None:
    signal_file = tmp_path / "2026-06-19.json"
    signal_file.write_text(
        json.dumps(
            [
                {
                    "group_id": "group_main",
                    "ticker": "7203",
                    "signal_type": "BUY",
                    "close_price": 1000.0,
                    "planned_price": 1010.0,
                    "signal_metadata": {"ATR_Ratio": 0.05},
                }
            ]
        ),
        encoding="utf-8",
    )
    cfg = SimpleNamespace(
        signal_file_pattern=str(tmp_path / "{date}.json"),
        default_exit_strategy="MVXWL_N3_R0p54_T1p0_D14_B20p0_I0p55",
        strategy_groups=[],
    )
    monkeypatch.setattr(state_router, "get_production_config", lambda: cfg)

    buy = state_router.get_signals("2026-06-19")[0]

    assert buy["tp_r_value"] == pytest.approx(27.0)
    assert buy["tp2_price"] == pytest.approx(1054.0)
