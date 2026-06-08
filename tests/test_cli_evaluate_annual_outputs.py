from pathlib import Path
from datetime import datetime as real_datetime
from types import SimpleNamespace

import pandas as pd

from src.cli import evaluate as evaluate_cli
from src.evaluation.strategy_evaluator import StrategyEvaluator


def _write_features(data_root: Path, ticker: str) -> None:
    features_dir = data_root / "features"
    features_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-01-10", "2025-01-20"]),
            "RSI": [52.0, 61.0],
            "RSI_9": [53.0, 62.0],
            "RSI_14": [52.0, 61.0],
            "RSI_22": [51.0, 60.0],
            "EMA_20": [101.0, 108.0],
            "EMA_50": [99.0, 104.0],
            "EMA_200": [90.0, 94.0],
            "ATR": [2.1, 2.5],
            "ADX_14": [19.0, 25.0],
            "MACD": [0.2, 0.8],
            "MACD_Signal": [0.1, 0.6],
            "MACD_Hist": [0.1, 0.2],
        }
    ).to_parquet(features_dir / f"{ticker}_features.parquet", index=False)


def test_build_annual_continuous_periods_returns_full_span_for_multi_year_mode():
    args = SimpleNamespace(mode="annual", years=[2023, 2021, 2022])
    periods = [
        ("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
    ]

    assert evaluate_cli._build_segmented_continuous_periods(args, periods) == [
        ("2021-2023_continuous", "2021-01-01", "2023-12-31")
    ]


def test_resolve_include_continuous_uses_cli_then_config_default() -> None:
    assert (
        evaluate_cli._resolve_include_continuous(
            SimpleNamespace(include_continuous=None),
            {"include_continuous": False},
        )
        is False
    )
    assert (
        evaluate_cli._resolve_include_continuous(
            SimpleNamespace(include_continuous=None),
            {"include_continuous": True},
        )
        is True
    )
    assert (
        evaluate_cli._resolve_include_continuous(
            SimpleNamespace(include_continuous=False),
            {"include_continuous": True},
        )
        is False
    )


def test_output_run_slug_includes_filter_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        evaluate_cli,
        "_resolve_entry_exit_strategies",
        lambda _args, _eval_cfg, announce=False: (
            ["MACDHist2BarAnySignMaxBiasPct10Entry"],
            ["MVXWL_N3_R0p75_T1p0_D10_B20p0_I1p2"],
        ),
    )
    args = SimpleNamespace(
        mode="annual",
        years=[2025, 2026],
        buy_fill_mode="next_open",
        entry_reference_mode="raw_fill",
        fill_buffer_enabled=False,
        fill_buffer_pct=0.02,
        momentum_exhaustion_mode="enforce",
        momentum_exhaustion_max_score=4.0,
        momentum_exhaustion_threshold_method="absolute",
        industry_filter_mode="enforce",
        max_buy_per_industry_per_day=1,
        max_total_positions_per_industry=3,
        industry_reference_file="data/jpx_final_list.csv",
        ranking_mode="prs_train",
        ranking_strategies=["momentum"],
        entry_filter_mode="atr",
        position_sizing_mode="atr",
        risk_per_trade_pct=0.0078,
        atr_stop_multiple=1.0,
    )

    slug = evaluate_cli._build_output_run_slug("evaluate", args, {})

    assert "mom_enf_s4" in slug
    assert "ind_enf_d1_t3" in slug
    assert "__sig_" in slug
    assert len(slug) <= 180


def test_resolve_output_dir_uses_high_resolution_unique_names(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FixedDatetime:
        @classmethod
        def now(cls):
            return real_datetime(2026, 6, 8, 16, 9, 48, 123456)

    monkeypatch.setattr(evaluate_cli, "datetime", FixedDatetime)
    monkeypatch.setattr(
        evaluate_cli,
        "_build_output_run_slug",
        lambda _run_kind, _args, _eval_cfg: "same_slug",
    )

    first = Path(
        evaluate_cli._resolve_output_dir(
            "evaluate",
            SimpleNamespace(),
            str(tmp_path),
            {},
        )
    )
    second = Path(
        evaluate_cli._resolve_output_dir(
            "evaluate",
            SimpleNamespace(),
            str(tmp_path),
            {},
        )
    )

    assert first.name == "same_slug__160948_123456"
    assert second.name == "same_slug__160948_123456_01"
    assert first != second


def test_run_context_bundle_skips_continuous_when_disabled(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, list[tuple[str, str, str]]]] = []

    def fake_run_once(**kwargs):
        calls.append((kwargs["prefix"], list(kwargs["periods"])))
        return {"raw": str(tmp_path / f"{kwargs['prefix']}_raw.csv")}

    monkeypatch.setattr(evaluate_cli, "_run_once", fake_run_once)
    monkeypatch.setattr(
        evaluate_cli,
        "_write_localized_final_review_report",
        lambda **kwargs: str(tmp_path / "final_review.md"),
    )
    monkeypatch.setattr(
        evaluate_cli,
        "_write_annual_continuous_stability_rank",
        lambda **kwargs: {"continuous_stability_rank": str(tmp_path / "rank.csv")},
    )

    args = SimpleNamespace(mode="annual", years=[2021, 2022], include_continuous=False)
    periods = [
        ("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
    ]

    bundle = evaluate_cli._run_context_bundle(
        args=args,
        config={"evaluation": {"include_continuous": True}},
        periods=periods,
        entry_filter_variants=[("off", {})],
        output_dir=str(tmp_path),
        prefix="strategy_evaluation",
        ranking_mode="prs_train",
    )

    assert bundle is not None
    assert calls == [("strategy_evaluation", periods)]
    assert bundle.continuous is None
    assert bundle.annual_companion is None
    assert bundle.final_report == str(tmp_path / "final_review.md")


def test_annual_continuous_stability_rank_prefers_continuous_then_stability():
    segmented_df = pd.DataFrame(
        [
            {
                "period": period,
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_A",
                "entry_filter": "off",
                "return_pct": value,
                "alpha": value - 5.0,
                "sharpe_ratio": 1.0,
                "max_drawdown_pct": 10.0,
                "num_trades": 10,
                "exit_confirmation_days": 1,
            }
            for period, value in [("2021", 20.0), ("2022", 18.0), ("2023", 19.0)]
        ]
        + [
            {
                "period": period,
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_B",
                "entry_filter": "off",
                "return_pct": value,
                "alpha": value - 5.0,
                "sharpe_ratio": 1.0,
                "max_drawdown_pct": 12.0,
                "num_trades": 10,
                "exit_confirmation_days": 1,
            }
            for period, value in [("2021", 22.0), ("2022", -5.0), ("2023", 8.0)]
        ]
        + [
            {
                "period": period,
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_C",
                "entry_filter": "off",
                "return_pct": value,
                "alpha": value - 5.0,
                "sharpe_ratio": 1.1,
                "max_drawdown_pct": 9.0,
                "num_trades": 10,
                "exit_confirmation_days": 1,
            }
            for period, value in [("2021", 21.0), ("2022", 15.0), ("2023", 14.0)]
        ]
    )

    continuous_df = pd.DataFrame(
        [
            {
                "period": "2021-2023_continuous",
                "start_date": "2021-01-01",
                "end_date": "2023-12-31",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_A",
                "entry_filter": "off",
                "return_pct": 95.0,
                "topix_return_pct": 20.0,
                "alpha": 75.0,
                "sharpe_ratio": 1.6,
                "max_drawdown_pct": 18.0,
                "num_trades": 30,
                "win_rate_pct": 55.0,
                "exit_confirmation_days": 1,
            },
            {
                "period": "2021-2023_continuous",
                "start_date": "2021-01-01",
                "end_date": "2023-12-31",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_B",
                "entry_filter": "off",
                "return_pct": 110.0,
                "topix_return_pct": 20.0,
                "alpha": 90.0,
                "sharpe_ratio": 1.4,
                "max_drawdown_pct": 24.0,
                "num_trades": 30,
                "win_rate_pct": 50.0,
                "exit_confirmation_days": 1,
            },
            {
                "period": "2021-2023_continuous",
                "start_date": "2021-01-01",
                "end_date": "2023-12-31",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_C",
                "entry_filter": "off",
                "return_pct": 110.0,
                "topix_return_pct": 20.0,
                "alpha": 90.0,
                "sharpe_ratio": 1.5,
                "max_drawdown_pct": 20.0,
                "num_trades": 30,
                "win_rate_pct": 52.0,
                "exit_confirmation_days": 1,
            },
        ]
    )

    rank_df = evaluate_cli._build_annual_continuous_stability_rank_df(
        segmented_df=segmented_df,
        continuous_df=continuous_df,
    )

    assert rank_df["exit_strategy"].tolist() == ["MVX_C", "MVX_B", "MVX_A"]
    assert rank_df.iloc[0]["positive_years"] == 3
    assert rank_df.iloc[1]["positive_years"] == 2
    assert "year_return_2021" in rank_df.columns
    assert "year_return_2022" in rank_df.columns
    assert rank_df.iloc[0]["continuous_stability_rank"] == 1


def test_write_annual_continuous_stability_rank_writes_csv_and_report(tmp_path):
    segmented_path = tmp_path / "segmented.csv"
    continuous_path = tmp_path / "continuous.csv"

    pd.DataFrame(
        [
            {
                "period": "2021",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p25_T1p6_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 12.0,
                "alpha": 6.0,
                "sharpe_ratio": 1.1,
                "max_drawdown_pct": 9.0,
                "num_trades": 8,
                "exit_confirmation_days": 1,
            },
            {
                "period": "2022",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p25_T1p6_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 10.0,
                "alpha": 5.0,
                "sharpe_ratio": 1.0,
                "max_drawdown_pct": 11.0,
                "num_trades": 9,
                "exit_confirmation_days": 1,
            },
        ]
    ).to_csv(segmented_path, index=False)

    pd.DataFrame(
        [
            {
                "period": "2021-2022_continuous",
                "start_date": "2021-01-01",
                "end_date": "2022-12-31",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p25_T1p6_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 28.0,
                "topix_return_pct": 12.0,
                "alpha": 16.0,
                "sharpe_ratio": 1.3,
                "max_drawdown_pct": 14.0,
                "num_trades": 17,
                "win_rate_pct": 58.0,
                "exit_confirmation_days": 1,
            },
        ]
    ).to_csv(continuous_path, index=False)

    files = evaluate_cli._write_annual_continuous_stability_rank(
        output_dir=str(tmp_path),
        prefix="annual_eval",
        segmented_raw_path=str(segmented_path),
        continuous_raw_path=str(continuous_path),
    )

    assert files is not None
    assert Path(files["continuous_stability_rank"]).exists()
    assert Path(files["continuous_stability_report"]).exists()


def test_write_combined_position_output_family_writes_indicator_sidecar(tmp_path):
    data_root = tmp_path / "data"
    _write_features(data_root, "7203")

    trade_frames = [
        pd.DataFrame(
            [
                {
                    "ticker": "7203",
                    "entry_date": "2025-01-10",
                    "entry_metadata_json": '{"entry_signal_date": "2025-01-10"}',
                    "exit_date": "2025-01-20",
                    "exit_metadata_json": '{"exit_signal_date": "2025-01-20"}',
                    "entry_strategy": "EntryA",
                    "exit_strategy": "ExitA",
                    "entry_filter": "off",
                    "period": "2025",
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                    "market_regime": "温和牛市 (TOPIX 0-25%)",
                    "topix_return_pct": 12.0,
                    "exit_confirmation_days": 1,
                    "buy_fill_mode": "next_open",
                    "entry_reference_mode": "raw_fill",
                    "fill_buffer_enabled": False,
                    "fill_buffer_pct": 0.0,
                    "entry_price": 100.0,
                    "entry_score": 70.0,
                    "entry_confidence": 0.8,
                    "exit_price": 110.0,
                    "exit_reason": "TP1 hit: +1.0R",
                    "exit_urgency": "P_TP1",
                    "holding_days": 10,
                    "shares": 100,
                    "return_pct": 5.0,
                    "return_jpy": 5000.0,
                    "peak_price": 112.0,
                    "position_quantity_before_exit": 100,
                    "position_quantity_after_exit": 0,
                    "exit_sell_percentage": 1.0,
                    "exit_is_full_exit": True,
                    "exit_is_partial_exit": False,
                    "capacity_regime_version": "",
                    "capacity_tier_name": "",
                    "capacity_effective_equity_jpy": 0.0,
                    "capacity_order_cap_jpy": 0.0,
                    "capacity_turnover_jpy": 0.0,
                    "capacity_participation_pct": 0.0,
                    "ranking_strategy": "default",
                }
            ]
        )
    ]

    files = evaluate_cli._write_combined_position_output_family(
        output_dir=str(tmp_path),
        data_root=str(data_root),
        family_prefix="position_eval_combined",
        raw_frames=[],
        regime_frames=[],
        trade_frames=trade_frames,
    )

    assert Path(files["trades"]).exists()
    assert Path(files["trades_indicators"]).exists()

    indicators_df = pd.read_csv(files["trades_indicators"])
    assert "entry_exec_RSI" in indicators_df.columns
    assert indicators_df.iloc[0]["exit_exec_MACD"] == 0.8


def test_write_localized_annual_final_review_includes_opening_metric_tables(tmp_path):
    segmented_path = tmp_path / "segmented.csv"
    trades_path = tmp_path / "trades.csv"

    pd.DataFrame(
        [
            {
                "period": "2021",
                "start_date": "2021-01-01",
                "end_date": "2021-12-31",
                "entry_strategy": "EntryA",
                "exit_strategy": "ExitA",
                "entry_filter": "off",
                "exit_confirmation_days": 1,
                "buy_fill_mode": "next_open",
                "fill_buffer_enabled": True,
                "fill_buffer_pct": 0.02,
                "return_pct": 10.0,
                "topix_return_pct": 5.0,
                "alpha": 5.0,
                "sharpe_ratio": 1.2,
                "max_drawdown_pct": 5.0,
                "num_trades": 8,
                "win_rate_pct": 50.0,
                "avg_gain_pct": 4.0,
                "avg_loss_pct": -2.0,
            },
            {
                "period": "2022",
                "start_date": "2022-01-01",
                "end_date": "2022-12-31",
                "entry_strategy": "EntryA",
                "exit_strategy": "ExitA",
                "entry_filter": "off",
                "exit_confirmation_days": 1,
                "buy_fill_mode": "next_open",
                "fill_buffer_enabled": True,
                "fill_buffer_pct": 0.02,
                "return_pct": 20.0,
                "topix_return_pct": 6.0,
                "alpha": 14.0,
                "sharpe_ratio": 1.4,
                "max_drawdown_pct": 7.0,
                "num_trades": 10,
                "win_rate_pct": 70.0,
                "avg_gain_pct": 5.0,
                "avg_loss_pct": -2.5,
            },
            {
                "period": "2021",
                "start_date": "2021-01-01",
                "end_date": "2021-12-31",
                "entry_strategy": "EntryB",
                "exit_strategy": "ExitB",
                "entry_filter": "strict",
                "exit_confirmation_days": 2,
                "buy_fill_mode": "next_open",
                "fill_buffer_enabled": True,
                "fill_buffer_pct": 0.02,
                "return_pct": 30.0,
                "topix_return_pct": 5.0,
                "alpha": 25.0,
                "sharpe_ratio": 1.8,
                "max_drawdown_pct": 9.0,
                "num_trades": 6,
                "win_rate_pct": 80.0,
                "avg_gain_pct": 6.0,
                "avg_loss_pct": -3.0,
            },
            {
                "period": "2022",
                "start_date": "2022-01-01",
                "end_date": "2022-12-31",
                "entry_strategy": "EntryB",
                "exit_strategy": "ExitB",
                "entry_filter": "strict",
                "exit_confirmation_days": 2,
                "buy_fill_mode": "next_open",
                "fill_buffer_enabled": True,
                "fill_buffer_pct": 0.02,
                "return_pct": 50.0,
                "topix_return_pct": 6.0,
                "alpha": 44.0,
                "sharpe_ratio": 2.0,
                "max_drawdown_pct": 11.0,
                "num_trades": 7,
                "win_rate_pct": 60.0,
                "avg_gain_pct": 7.0,
                "avg_loss_pct": -3.5,
            },
        ]
    ).to_csv(segmented_path, index=False)

    pd.DataFrame(
        [
            {
                "period": "2021",
                "entry_strategy": "EntryA",
                "exit_strategy": "ExitA",
                "entry_filter": "off",
                "exit_confirmation_days": 1,
                "buy_fill_mode": "next_open",
                "fill_buffer_enabled": True,
                "fill_buffer_pct": 0.02,
                "return_jpy": 1000.0,
                "exit_urgency": "P_TP1",
                "ticker": "1332",
            },
            {
                "period": "2022",
                "entry_strategy": "EntryA",
                "exit_strategy": "ExitA",
                "entry_filter": "off",
                "exit_confirmation_days": 1,
                "buy_fill_mode": "next_open",
                "fill_buffer_enabled": True,
                "fill_buffer_pct": 0.02,
                "return_jpy": 1500.0,
                "exit_urgency": "P_TP2",
                "ticker": "1332",
            },
            {
                "period": "2021",
                "entry_strategy": "EntryB",
                "exit_strategy": "ExitB",
                "entry_filter": "strict",
                "exit_confirmation_days": 2,
                "buy_fill_mode": "next_open",
                "fill_buffer_enabled": True,
                "fill_buffer_pct": 0.02,
                "return_jpy": 2000.0,
                "exit_urgency": "P_TP1",
                "ticker": "1332",
            },
            {
                "period": "2022",
                "entry_strategy": "EntryB",
                "exit_strategy": "ExitB",
                "entry_filter": "strict",
                "exit_confirmation_days": 2,
                "buy_fill_mode": "next_open",
                "fill_buffer_enabled": True,
                "fill_buffer_pct": 0.02,
                "return_jpy": 2500.0,
                "exit_urgency": "P_TP2",
                "ticker": "1332",
            },
        ]
    ).to_csv(trades_path, index=False)

    bundle = evaluate_cli.EvaluationOutputBundle(
        segmented={
            "raw": str(segmented_path),
            "trades": str(trades_path),
        }
    )

    report_path = evaluate_cli._write_localized_final_review_report(
        args=SimpleNamespace(mode="annual"),
        output_dir=str(tmp_path),
        prefix="annual_eval",
        bundle=bundle,
    )

    assert report_path is not None
    report_text = Path(report_path).read_text(encoding="utf-8")

    assert "## 全策略组合年度总览" in report_text
    assert "### 全策略组合 × 年度收益率" in report_text
    assert "### 全策略组合 × 年度胜率" in report_text
    assert "### 全策略组合 × 年度最大回撤" in report_text
    assert "| 入场策略 | 出场策略 | 入场过滤器 | 出场确认天数 | 买入成交模式 | 入场参考价模式 | 成交价缓冲 | 缓冲比例 | 2021 | 2022 | 全期间平均收益率 |" in report_text
    assert "| EntryA | ExitA | off | 1 | next_open | raw_fill | on | 2.00% | 10.00% | 20.00% | 15.00% |" in report_text
    assert "| EntryA | ExitA | off | 1 | next_open | raw_fill | on | 2.00% | 50.00% | 70.00% | 60.00% |" in report_text
    assert "| EntryA | ExitA | off | 1 | next_open | raw_fill | on | 2.00% | 5.00% | 7.00% | 6.00% |" in report_text
    assert report_text.index("## 全策略组合年度总览") < report_text.index("## 策略组合 1")
    assert "### 年度总览" in report_text


def test_precross_entries_use_feature_only_preload_flags():
    include_trades, include_financials, include_metadata = (
        StrategyEvaluator._resolve_aux_preload_flags(
            entry_strategies=["MACDPreCross2BarEntry"],
            exit_strategies=["MVX_N3_R3p25_T1p6_D21_B20p0"],
            entry_mapping={
                "MACDPreCross2BarEntry": (
                    "src.analysis.strategies.entry.macd_precross_momentum_entry."
                    "MACDPreCross2BarEntry"
                )
            },
            exit_mapping={
                "MVX_N3_R3p25_T1p6_D21_B20p0": (
                    "src.analysis.strategies.exit.multiview_grid_exit."
                    "MVX_N3_R3p25_T1p6_D21_B20p0"
                )
            },
        )
    )

    assert (include_trades, include_financials, include_metadata) == (
        False,
        False,
        False,
    )
