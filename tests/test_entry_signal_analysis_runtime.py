from __future__ import annotations

from types import SimpleNamespace

from src.entry_signal_analysis.models import EntrySignalAnalysisRequest
from src.entry_signal_analysis.runtime import (
    build_request_from_args,
    resolve_effective_entry_filter_for_request,
    resolve_tail_guard_for_request,
)


def _args(**overrides):
    base = {
        "entry_strategies": None,
        "universe_file": None,
        "start": "2026-01-01",
        "end": "2026-01-31",
        "years": None,
        "horizons": [1, 3, 5],
        "primary_horizon": 5,
        "primary_horizons": None,
        "label_mode": "next_open",
        "ranking_strategy": None,
        "entry_filter_mode": "auto",
        "entry_filter_name": None,
        "position_sizing_mode": None,
        "risk_per_trade_pct": None,
        "atr_stop_multiple": None,
        "atr_ratio_min": None,
        "atr_ratio_max": None,
        "tail_guard_enabled": None,
        "tail_guard_max_rank": None,
        "tail_guard_rank_limit_mode": None,
        "limit": None,
        "data_root": "data",
        "output_dir": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_request_from_args_uses_production_defaults(monkeypatch) -> None:
    import src.entry_signal_analysis.runtime as runtime

    prod_cfg = SimpleNamespace(
        strategy_groups=[{"entry_strategy": "ProdEntry"}],
        default_entry_strategy="FallbackEntry",
        monitor_list_file="data/production_monitor_list.json",
        position_sizing_mode="atr",
        atr_position_sizing=SimpleNamespace(
            risk_per_trade_pct=0.0108,
            atr_stop_multiple=0.6,
        ),
    )
    config_mgr = SimpleNamespace(
        raw_config={
            "production": {
                "signal_ranking_strategy": "momentum",
                "entry_filter": {"enabled": False},
            }
        },
        get_production_config=lambda: prod_cfg,
    )

    monkeypatch.setattr(runtime, "load_config_manager", lambda: config_mgr)
    monkeypatch.setattr(runtime, "load_tickers", lambda universe_files, limit=None: ["7203", "6758"][:limit])

    request = build_request_from_args(_args(limit=1))

    assert request.entry_strategies == ["ProdEntry"]
    assert request.tickers == ["7203"]
    assert request.ranking_strategy == "momentum"
    assert request.risk_per_trade_pct == 0.0108
    assert request.atr_stop_multiple == 0.6
    assert request.primary_horizons == [5]


def test_build_request_from_args_supports_multiple_primary_horizons(monkeypatch) -> None:
    import src.entry_signal_analysis.runtime as runtime

    prod_cfg = SimpleNamespace(
        strategy_groups=[{"entry_strategy": "ProdEntry"}],
        default_entry_strategy="FallbackEntry",
        monitor_list_file="data/production_monitor_list.json",
        position_sizing_mode="atr",
        atr_position_sizing=SimpleNamespace(
            risk_per_trade_pct=0.0108,
            atr_stop_multiple=0.6,
        ),
    )
    config_mgr = SimpleNamespace(
        raw_config={"production": {"signal_ranking_strategy": "momentum"}},
        get_production_config=lambda: prod_cfg,
    )

    monkeypatch.setattr(runtime, "load_config_manager", lambda: config_mgr)
    monkeypatch.setattr(runtime, "load_tickers", lambda universe_files, limit=None: ["7203"])

    request = build_request_from_args(
        _args(
            horizons=[3, 5, 7, 9],
            primary_horizons=[3, 5, 7, 9],
            primary_horizon=5,
        )
    )

    assert request.primary_horizons == [3, 5, 7, 9]
    assert request.primary_horizon == 3


def test_build_request_from_args_normalizes_unbounded_atr_ratio_strings(monkeypatch) -> None:
    import src.entry_signal_analysis.runtime as runtime

    prod_cfg = SimpleNamespace(
        strategy_groups=[{"entry_strategy": "ProdEntry"}],
        default_entry_strategy="FallbackEntry",
        monitor_list_file="data/production_monitor_list.json",
        position_sizing_mode="atr",
        atr_position_sizing=SimpleNamespace(
            risk_per_trade_pct=0.0108,
            atr_stop_multiple=0.6,
        ),
    )
    config_mgr = SimpleNamespace(
        raw_config={"production": {"signal_ranking_strategy": "momentum"}},
        get_production_config=lambda: prod_cfg,
    )

    monkeypatch.setattr(runtime, "load_config_manager", lambda: config_mgr)
    monkeypatch.setattr(runtime, "load_tickers", lambda universe_files, limit=None: ["7203"])

    request = build_request_from_args(
        _args(
            atr_ratio_min="none",
            atr_ratio_max="none",
        )
    )

    assert request.atr_ratio_min is None
    assert request.atr_ratio_max is None


def test_resolve_tail_guard_for_request_defaults_to_enabled_rank12(monkeypatch) -> None:
    import src.entry_signal_analysis.runtime as runtime

    monkeypatch.setattr(runtime, "load_runtime_config", lambda: {})

    request = EntrySignalAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203"],
        start_date="2026-01-01",
        end_date="2026-01-31",
        horizons=[1, 3, 5],
        output_dir="output/entry_signal_analysis_test",
    )

    config = resolve_tail_guard_for_request(request)

    assert config == {"enabled": True, "max_rank": 12}


def test_resolve_tail_guard_for_request_supports_min_mode_override(monkeypatch) -> None:
    import src.entry_signal_analysis.runtime as runtime

    monkeypatch.setattr(runtime, "load_runtime_config", lambda: {})

    request = EntrySignalAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203"],
        start_date="2026-01-01",
        end_date="2026-01-31",
        horizons=[1, 3, 5],
        tail_guard_max_rank=8,
        tail_guard_rank_limit_mode="min",
        output_dir="output/entry_signal_analysis_test",
    )

    config = resolve_tail_guard_for_request(request)

    assert config == {"enabled": True, "max_rank": 8, "rank_limit_mode": "min"}


def test_resolve_effective_entry_filter_for_request_uses_off_for_disabled_production_filter(monkeypatch) -> None:
    import src.entry_signal_analysis.runtime as runtime

    monkeypatch.setattr(
        runtime,
        "load_runtime_config",
        lambda: {"production": {"entry_filter": {"enabled": False, "atr_price_min": None, "atr_price_max": None}}},
    )

    request = EntrySignalAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203"],
        start_date="2026-01-01",
        end_date="2026-01-31",
        horizons=[1, 3, 5],
        entry_filter_mode="auto",
        output_dir="output/entry_signal_analysis_test",
    )

    mode, names = resolve_effective_entry_filter_for_request(request)

    assert mode == "off"
    assert names == ["production"]


def test_resolve_effective_entry_filter_for_request_uses_atr_for_production_atr_filter(monkeypatch) -> None:
    import src.entry_signal_analysis.runtime as runtime

    monkeypatch.setattr(
        runtime,
        "load_runtime_config",
        lambda: {
            "production": {
                "entry_filter": {
                    "enabled": True,
                    "require_ema_bull_stack": False,
                    "rsi_min": None,
                    "rsi_max": None,
                    "atr_price_min": 0.015,
                    "atr_price_max": 0.03,
                    "min_price": None,
                }
            }
        },
    )

    request = EntrySignalAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203"],
        start_date="2026-01-01",
        end_date="2026-01-31",
        horizons=[1, 3, 5],
        entry_filter_mode="auto",
        output_dir="output/entry_signal_analysis_test",
    )

    mode, names = resolve_effective_entry_filter_for_request(request)

    assert mode == "atr"
    assert names == ["production"]
