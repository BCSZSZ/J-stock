from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.artifacts.tabular import LargeArtifactFormat


EntryExitExecutionMode = Literal["next_open", "signal_close"]
EntryExitSignalScope = Literal["all", "selected"]
EntryExitEntryFilterMode = Literal["auto", "off", "atr", "single", "grid"]
EntryExitTailGuardRankLimitMode = Literal["max", "min"]
EntryExitPartialExitPolicy = Literal["first_sell_full_exit"]
EntryExitMomentumExhaustionMode = Literal["off", "shadow", "enforce"]
EntryExitMomentumExhaustionThresholdMethod = Literal["absolute"]
EntryExitIndustryFilterMode = Literal["off", "shadow", "enforce"]


class EntryExitValidationRequest(BaseModel):
    entry_strategies: list[str]
    exit_strategies: list[str]
    tickers: list[str]
    start_date: date
    end_date: date
    horizons: list[int] = Field(default_factory=lambda: [3, 5, 7, 9, 11])
    primary_horizon: int = 5
    execution_mode: EntryExitExecutionMode = "next_open"
    signal_scope: EntryExitSignalScope = "all"
    ranking_strategy: str = "momentum"
    entry_filter_mode: EntryExitEntryFilterMode = "auto"
    entry_filter_names: list[str] = Field(default_factory=list)
    atr_ratio_min: float | None = None
    atr_ratio_max: float | None = None
    tail_guard_enabled: bool | None = None
    tail_guard_max_rank: int | None = None
    tail_guard_rank_limit_mode: EntryExitTailGuardRankLimitMode | None = None
    momentum_exhaustion_mode: EntryExitMomentumExhaustionMode | None = None
    momentum_exhaustion_max_score: float | None = None
    momentum_exhaustion_threshold_method: EntryExitMomentumExhaustionThresholdMethod = "absolute"
    industry_filter_mode: EntryExitIndustryFilterMode | None = None
    max_buy_per_industry_per_day: int | None = None
    max_total_positions_per_industry: int | None = None
    industry_reference_file: str | None = None
    max_holding_trading_days: int = 60
    partial_exit_policy: EntryExitPartialExitPolicy = "first_sell_full_exit"
    min_samples: int = 30
    data_root: str = "data"
    output_dir: str = "entry_exit_validation"
    large_artifact_format: LargeArtifactFormat = "parquet"

    @property
    def normalized_horizons(self) -> list[int]:
        return sorted({int(value) for value in self.horizons if int(value) > 0})

    @model_validator(mode="after")
    def validate_request(self) -> "EntryExitValidationRequest":
        if not self.entry_strategies:
            raise ValueError("entry_strategies must contain at least one strategy")
        if not self.exit_strategies:
            raise ValueError("exit_strategies must contain at least one strategy")
        if not self.tickers:
            raise ValueError("tickers must contain at least one ticker")
        if not self.normalized_horizons:
            raise ValueError("horizons must contain at least one positive integer")
        if self.primary_horizon not in self.normalized_horizons:
            self.primary_horizon = self.normalized_horizons[0]
        if self.max_holding_trading_days <= 0:
            raise ValueError("max_holding_trading_days must be positive")
        if self.min_samples < 1:
            raise ValueError("min_samples must be positive")
        return self


class EntryExitValidationArtifacts(BaseModel):
    output_dir: str
    selected_trades_csv: str | None = None
    selected_trades_parquet: str | None = None
    combo_summary_csv: str
    combo_tail_metrics_csv: str
    combo_vs_fixed_horizon_csv: str
    combo_by_year_csv: str
    combo_by_market_regime_csv: str
    combo_by_exit_reason_csv: str
    combo_by_signal_bucket_csv: str
    combo_by_month_csv: str
    combo_robustness_ranking_csv: str
    combo_risk_ranking_csv: str
    summary_json: str
    report_md: str
    manifest_json: str


class EntryExitValidationDatasetManifest(BaseModel):
    dataset_id: str
    generated_at: str
    output_dir: str
    selected_trades_csv: str | None = None
    selected_trades_parquet: str | None = None
    combo_summary_csv: str
    combo_tail_metrics_csv: str
    combo_vs_fixed_horizon_csv: str
    combo_by_year_csv: str
    combo_by_market_regime_csv: str
    combo_by_exit_reason_csv: str
    combo_by_signal_bucket_csv: str
    combo_by_month_csv: str
    combo_robustness_ranking_csv: str
    combo_risk_ranking_csv: str
    summary_json: str
    report_md: str
    entry_strategies: list[str]
    exit_strategies: list[str]
    universe_size: int
    start_date: str
    end_date: str
    horizons: list[int]
    primary_horizon: int
    execution_mode: EntryExitExecutionMode
    signal_scope: EntryExitSignalScope
    ranking_strategy: str
    entry_filter_mode: EntryExitEntryFilterMode
    entry_filter_names: list[str]
    effective_entry_filter_mode: EntryExitEntryFilterMode | None = None
    effective_entry_filter_names: list[str] = Field(default_factory=list)
    candidate_count: int
    simulated_trade_count: int
    combination_count: int
    request: dict[str, object]


class EntryExitValidationRunSummary(BaseModel):
    generated_at: str
    request: dict[str, object]
    candidate_count: int
    simulated_trade_count: int
    entry_strategy_count: int
    exit_strategy_count: int
    combination_count: int
    effective_entry_filter_mode: EntryExitEntryFilterMode | None = None
    effective_entry_filter_names: list[str] = Field(default_factory=list)
    market_regime_status: str = "unavailable"
    market_regime_definition: str | None = None
    artifacts: EntryExitValidationArtifacts
    top_robust_combinations: list[dict[str, object]] = Field(default_factory=list)
    top_risk_combinations: list[dict[str, object]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
