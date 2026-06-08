from types import SimpleNamespace

import src.backtest.portfolio_engine as portfolio_engine_module
import src.evaluation.strategy_evaluator as strategy_evaluator_module
import src.utils.strategy_loader as strategy_loader_module
from src.analysis.signals import SignalAction, TradingSignal
from src.backtest.portfolio_engine import PortfolioBacktestEngine
from src.evaluation.strategy_evaluator import StrategyEvaluator
from src.utils.atr_position_sizing import PortfolioSizingConfig


def _build_engine(
    *,
    mode: str = "atr",
    momentum_exhaustion_config: dict[str, object] | None = None,
) -> PortfolioBacktestEngine:
    return PortfolioBacktestEngine(
        starting_capital=1_000_000,
        position_sizing_config=PortfolioSizingConfig(
            mode=mode,
            max_positions=5,
            max_position_pct=0.30,
        ),
        tail_guard_config={"enabled": True, "max_rank": 12},
        momentum_exhaustion_config=momentum_exhaustion_config,
    )


def _build_ranked_signals(scores: list[float]) -> list[tuple[str, TradingSignal, float]]:
    ranked_signals: list[tuple[str, TradingSignal, float]] = []
    for index, score in enumerate(scores, start=1):
        ranked_signals.append(
            (
                f"{index:04d}",
                TradingSignal(
                    action=SignalAction.BUY,
                    confidence=1.0,
                    reasons=["buy"],
                    metadata={"score": score},
                    strategy_name="TestEntry",
                ),
                score,
            )
        )
    return ranked_signals


def test_tail_guard_trims_atr_ranked_signals_to_positive_count_when_larger() -> None:
    engine = _build_engine(mode="atr")
    ranked_signals = _build_ranked_signals([5.0] * 15 + [-1.0] * 5)

    trimmed_signals, tail_guard_rank_limit, positive_rank_score_count = (
        engine._apply_tail_guard_to_ranked_signals(ranked_signals)
    )

    assert positive_rank_score_count == 15
    assert tail_guard_rank_limit == 15
    assert len(trimmed_signals) == 15


def test_tail_guard_uses_base_rank_limit_when_positive_count_is_smaller() -> None:
    engine = _build_engine(mode="atr")
    ranked_signals = _build_ranked_signals([4.0] * 4 + [-1.0] * 16)

    trimmed_signals, tail_guard_rank_limit, positive_rank_score_count = (
        engine._apply_tail_guard_to_ranked_signals(ranked_signals)
    )

    assert positive_rank_score_count == 4
    assert tail_guard_rank_limit == 12
    assert len(trimmed_signals) == 12


def test_tail_guard_does_not_trim_fixed_position_mode() -> None:
    engine = _build_engine(mode="fixed")
    ranked_signals = _build_ranked_signals([5.0] * 15 + [-1.0] * 5)

    trimmed_signals, tail_guard_rank_limit, positive_rank_score_count = (
        engine._apply_tail_guard_to_ranked_signals(ranked_signals)
    )

    assert positive_rank_score_count == 0
    assert tail_guard_rank_limit is None
    assert len(trimmed_signals) == len(ranked_signals)


def test_momentum_exhaustion_enforce_uses_full_rank_pool_before_filtering() -> None:
    engine = _build_engine(
        mode="atr",
        momentum_exhaustion_config={"mode": "enforce", "max_score": 4.0},
    )

    assert engine._rank_buy_signal_top_k(SimpleNamespace(max_positions=2)) is None


def test_momentum_exhaustion_shadow_keeps_rank_pool_limit() -> None:
    engine = _build_engine(
        mode="fixed",
        momentum_exhaustion_config={"mode": "shadow", "max_score": 4.0},
    )

    assert engine._rank_buy_signal_top_k(SimpleNamespace(max_positions=2)) == 4


def test_momentum_exhaustion_filters_high_ranked_signals_before_allocation() -> None:
    engine = _build_engine(
        mode="atr",
        momentum_exhaustion_config={"mode": "enforce", "max_score": 4.0},
    )
    ranked_signals = _build_ranked_signals([5.0, 4.0, 3.0])

    kept, filtered_count, shadowed_count = (
        engine._apply_momentum_exhaustion_to_ranked_signals(ranked_signals)
    )

    assert [ticker for ticker, _signal, _priority in kept] == ["0002", "0003"]
    assert filtered_count == 1
    assert shadowed_count == 0
    assert ranked_signals[0][1].metadata["momentum_exhaustion_filtered"] is True
    assert ranked_signals[1][1].metadata["momentum_exhaustion_blocked"] is False


def test_momentum_exhaustion_shadow_keeps_ranked_signals_for_allocation() -> None:
    engine = _build_engine(
        mode="atr",
        momentum_exhaustion_config={"mode": "shadow", "max_score": 4.0},
    )
    ranked_signals = _build_ranked_signals([5.0, 4.0])

    kept, filtered_count, shadowed_count = (
        engine._apply_momentum_exhaustion_to_ranked_signals(ranked_signals)
    )

    assert [ticker for ticker, _signal, _priority in kept] == ["0001", "0002"]
    assert filtered_count == 0
    assert shadowed_count == 1
    assert ranked_signals[0][1].metadata["momentum_exhaustion_filtered"] is False


def test_strategy_evaluator_passes_tail_guard_config_to_backtest_engine(
    monkeypatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}

    class FakePortfolioBacktestEngine:
        def __init__(self, *args, **kwargs) -> None:
            captured["tail_guard_config"] = kwargs.get("tail_guard_config")
            captured["momentum_exhaustion_config"] = kwargs.get(
                "momentum_exhaustion_config"
            )
            self.daily_snapshots = []
            self.last_pending_buy_signals = {}
            self.last_pending_sell_signals = {}
            self.last_final_cash_jpy = 0.0
            self.last_final_open_positions = []
            self.last_processed_date = "2024-01-31"

        def backtest_portfolio_strategy(self, **kwargs):
            return SimpleNamespace(
                total_return_pct=0.0,
                sharpe_ratio=0.0,
                max_drawdown_pct=0.0,
                num_trades=0,
                win_rate_pct=0.0,
                avg_gain_pct=0.0,
                avg_loss_pct=0.0,
                capacity_regime_mode="off",
                capacity_regime_version="",
                capacity_final_tier="",
                capacity_peak_tier="",
                capacity_effective_equity_jpy=0.0,
                capacity_peak_equity_jpy=0.0,
                capacity_effective_max_positions=0,
                capacity_effective_max_position_pct=0.0,
                capacity_participation_cap_pct=0.0,
                capacity_min_turnover_20_jpy=0.0,
                capacity_blocked_buys=0,
                capacity_liquidity_blocked_buys=0,
                capacity_trimmed_buys=0,
                capacity_avg_participation_pct=0.0,
                capacity_p95_participation_pct=0.0,
                capacity_cash_drag_jpy=0.0,
            )

    monkeypatch.setattr(
        portfolio_engine_module,
        "PortfolioBacktestEngine",
        FakePortfolioBacktestEngine,
    )
    monkeypatch.setattr(
        strategy_loader_module,
        "load_strategy_pair",
        lambda entry_strategy, exit_strategy: (
            SimpleNamespace(strategy_name=entry_strategy),
            SimpleNamespace(strategy_name=exit_strategy),
        ),
    )
    monkeypatch.setattr(
        strategy_loader_module,
        "load_ranking_strategy",
        lambda ranking_strategy: SimpleNamespace(name=ranking_strategy),
    )
    monkeypatch.setattr(
        strategy_evaluator_module,
        "load_config",
        lambda: {"production": {"tail_guard": {"enabled": True, "max_rank": 12}}},
    )

    momentum_config = {"mode": "enforce", "max_score": 4.0}
    evaluator = StrategyEvaluator(
        data_root="data",
        output_dir=str(tmp_path),
        momentum_exhaustion_config=momentum_config,
    )
    monkeypatch.setattr(evaluator, "_load_monitor_list", lambda: ["7203"])
    monkeypatch.setattr(evaluator, "_get_capacity_regime_mode", lambda: "off")
    monkeypatch.setattr(evaluator, "_get_capacity_regime", lambda: None)
    monkeypatch.setattr(
        evaluator,
        "_get_portfolio_sizing_config",
        lambda: PortfolioSizingConfig(mode="atr", max_positions=7, max_position_pct=0.18),
    )
    monkeypatch.setattr(evaluator, "_get_starting_capital", lambda: 9_000_000)
    monkeypatch.setattr(evaluator, "_build_seeded_positions", lambda strategy_name: [])
    monkeypatch.setattr(evaluator, "_build_initial_pending_signals", lambda: ({}, {}))
    monkeypatch.setattr(evaluator, "_record_trade_rows", lambda **kwargs: None)
    monkeypatch.setattr(evaluator, "_build_evaluation_run_snapshot", lambda **kwargs: {})

    result = evaluator._run_single_backtest(
        period_label="2024",
        start_date="2024-01-01",
        end_date="2024-01-31",
        entry_strategy="Entry",
        exit_strategy="Exit",
        entry_filter_name="default",
        entry_filter_config={},
        topix_return=0.0,
        preloaded_cache=None,
        ranking_strategy="momentum",
    )

    assert captured["tail_guard_config"] == {"enabled": True, "max_rank": 12}
    assert captured["momentum_exhaustion_config"] == momentum_config
    assert result.ranking_strategy == "momentum"
