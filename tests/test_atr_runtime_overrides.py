from types import SimpleNamespace

import pytest

from src.cli.production_daily import (
    _apply_atr_runtime_overrides,
    _sync_position_risk_state_to_base,
)
from src.utils.atr_position_sizing import AtrPositionSizingConfig
from src.utils.atr_runtime_overrides import (
    merge_entry_filter_runtime_bounds,
    merge_portfolio_runtime_overrides,
)


def test_merge_portfolio_runtime_overrides_layers_over_profile() -> None:
    args = SimpleNamespace(
        position_sizing_mode="atr",
        risk_per_trade_pct=0.006,
        atr_stop_multiple=2.0,
    )

    overrides = merge_portfolio_runtime_overrides(
        args,
        {
            "position_sizing_mode": "fixed",
            "starting_capital_jpy": 9_000_000,
            "atr_position_sizing": {"risk_per_trade_pct": 0.01},
        },
    )

    assert overrides is not None
    assert overrides["position_sizing_mode"] == "atr"
    assert overrides["starting_capital_jpy"] == 9_000_000
    assert overrides["atr_position_sizing"] == {
        "risk_per_trade_pct": pytest.approx(0.006),
        "atr_stop_multiple": pytest.approx(2.0),
    }


def test_merge_portfolio_runtime_overrides_returns_none_without_changes() -> None:
    args = SimpleNamespace(
        position_sizing_mode=None,
        risk_per_trade_pct=None,
        atr_stop_multiple=None,
    )

    assert merge_portfolio_runtime_overrides(args) is None


def test_merge_entry_filter_runtime_bounds_uses_filter_key_names() -> None:
    args = SimpleNamespace(atr_ratio_min=0.015, atr_ratio_max=0.03)

    merged = merge_entry_filter_runtime_bounds(
        {"enabled": True, "atr_price_min": 0.01},
        args,
    )

    assert merged["enabled"] is True
    assert merged["atr_price_min"] == pytest.approx(0.015)
    assert merged["atr_price_max"] == pytest.approx(0.03)


def test_production_daily_applies_atr_runtime_overrides_to_config() -> None:
    args = SimpleNamespace(
        position_sizing_mode="atr",
        risk_per_trade_pct=0.006,
        atr_stop_multiple=2.0,
    )
    prod_cfg = SimpleNamespace(
        position_sizing_mode="fixed",
        atr_position_sizing=AtrPositionSizingConfig(
            risk_per_trade_pct=0.01,
            atr_stop_multiple=3.0,
        ),
    )

    _apply_atr_runtime_overrides(args, prod_cfg)

    assert prod_cfg.position_sizing_mode == "atr"
    assert prod_cfg.atr_position_sizing.risk_per_trade_pct == pytest.approx(0.006)
    assert prod_cfg.atr_position_sizing.atr_stop_multiple == pytest.approx(2.0)


def test_production_daily_ignores_atr_runtime_overrides_when_fixed() -> None:
    args = SimpleNamespace(
        position_sizing_mode="fixed",
        risk_per_trade_pct=0.006,
        atr_stop_multiple=2.0,
    )
    prod_cfg = SimpleNamespace(
        position_sizing_mode="atr",
        atr_position_sizing=AtrPositionSizingConfig(
            risk_per_trade_pct=0.01,
            atr_stop_multiple=3.0,
        ),
    )

    _apply_atr_runtime_overrides(args, prod_cfg)

    assert prod_cfg.position_sizing_mode == "fixed"
    assert prod_cfg.atr_position_sizing.risk_per_trade_pct == pytest.approx(0.01)
    assert prod_cfg.atr_position_sizing.atr_stop_multiple == pytest.approx(3.0)


def test_sync_position_risk_state_to_base_only_tightens_stop_metadata() -> None:
    effective_position = SimpleNamespace(
        ticker="7203",
        quantity=100,
        lot_id="lot-1",
        peak_price=130.0,
        entry_atr=5.0,
        initial_stop_price=90.0,
        locked_stop_price=96.0,
    )
    base_position = SimpleNamespace(
        ticker="7203",
        quantity=100,
        lot_id="lot-1",
        peak_price=120.0,
        entry_atr=None,
        initial_stop_price=None,
        locked_stop_price=98.0,
    )
    effective_group = SimpleNamespace(id="group_main", positions=[effective_position])
    base_group = SimpleNamespace(id="group_main", positions=[base_position])
    effective_state = SimpleNamespace(get_all_groups=lambda: [effective_group])
    base_state = SimpleNamespace(get_group=lambda group_id: base_group)

    changed = _sync_position_risk_state_to_base(effective_state, base_state)

    assert changed is True
    assert base_position.peak_price == pytest.approx(130.0)
    assert base_position.entry_atr == pytest.approx(5.0)
    assert base_position.initial_stop_price == pytest.approx(90.0)
    assert base_position.locked_stop_price == pytest.approx(98.0)
