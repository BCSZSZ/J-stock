from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


EntrySignalLabelMode = Literal["signal_close", "next_open"]
EntrySignalEntryFilterMode = Literal["auto", "off", "atr", "single", "grid"]
PositionSizingMode = Literal["fixed", "atr"]
TailGuardRankLimitMode = Literal["max", "min"]
SignalStrengthMetric = Literal["rank_score", "score", "confidence"]
MomentumExhaustionMode = Literal["off", "shadow", "enforce"]
MomentumExhaustionThresholdMethod = Literal["absolute"]
IndustryFilterMode = Literal["off", "shadow", "enforce"]


class EntrySignalAnalysisRequest(BaseModel):
    entry_strategies: list[str]
    tickers: list[str]
    start_date: date
    end_date: date
    horizons: list[int] = Field(default_factory=lambda: [1, 3, 5])
    primary_horizon: int = 5
    primary_horizons: list[int] = Field(default_factory=list)
    label_mode: EntrySignalLabelMode = "next_open"
    ranking_strategy: str = "momentum"
    entry_filter_mode: EntrySignalEntryFilterMode = "auto"
    entry_filter_names: list[str] = Field(default_factory=list)
    position_sizing_mode: PositionSizingMode = "atr"
    risk_per_trade_pct: float | None = None
    atr_stop_multiple: float | None = None
    atr_ratio_min: float | None = None
    atr_ratio_max: float | None = None
    tail_guard_enabled: bool | None = None
    tail_guard_max_rank: int | None = None
    tail_guard_rank_limit_mode: TailGuardRankLimitMode | None = None
    momentum_exhaustion_mode: MomentumExhaustionMode | None = None
    momentum_exhaustion_max_score: float | None = None
    momentum_exhaustion_threshold_method: MomentumExhaustionThresholdMethod = "absolute"
    industry_filter_mode: IndustryFilterMode | None = None
    max_buy_per_industry_per_day: int | None = None
    max_total_positions_per_industry: int | None = None
    industry_reference_file: str | None = None
    data_root: str = "data"
    output_dir: str = "entry_signal_analysis"

    @property
    def normalized_horizons(self) -> list[int]:
        return sorted({int(value) for value in self.horizons if int(value) > 0})

    @property
    def normalized_primary_horizons(self) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for value in self.primary_horizons:
            parsed = int(value)
            if parsed <= 0 or parsed in seen:
                continue
            seen.add(parsed)
            normalized.append(parsed)
        return normalized or [int(self.primary_horizon)]

    @model_validator(mode="after")
    def validate_horizons(self) -> "EntrySignalAnalysisRequest":
        if not self.normalized_horizons:
            raise ValueError("horizons must contain at least one positive integer")
        requested_primary_horizons = self.normalized_primary_horizons
        invalid_primary_horizons = [
            value for value in requested_primary_horizons if value not in self.normalized_horizons
        ]
        if invalid_primary_horizons:
            invalid_values = ", ".join(str(value) for value in invalid_primary_horizons)
            raise ValueError(f"primary_horizons must be included in horizons: {invalid_values}")
        if self.primary_horizon not in self.normalized_horizons:
            self.primary_horizon = requested_primary_horizons[0]
        self.primary_horizons = requested_primary_horizons
        self.primary_horizon = self.primary_horizons[0]
        return self


class EntrySignalAnalysisArtifacts(BaseModel):
    output_dir: str
    candidates_csv: str
    selected_csv: str
    daily_summary_csv: str
    strategy_summary_csv: str
    summary_json: str
    report_md: str
    manifest_json: str


class EntrySignalAnalysisDatasetManifest(BaseModel):
    dataset_id: str
    generated_at: str
    output_dir: str
    candidates_csv: str
    selected_csv: str
    daily_summary_csv: str
    strategy_summary_csv: str
    summary_json: str
    report_md: str
    entry_strategies: list[str]
    universe_size: int
    start_date: str
    end_date: str
    horizons: list[int]
    primary_horizon: int
    primary_horizons: list[int] = Field(default_factory=list)
    label_mode: EntrySignalLabelMode
    ranking_strategy: str
    entry_filter_mode: EntrySignalEntryFilterMode
    entry_filter_names: list[str]
    effective_entry_filter_mode: EntrySignalEntryFilterMode | None = None
    effective_entry_filter_names: list[str] = Field(default_factory=list)
    candidate_count: int
    selected_count: int
    request: dict[str, object]


class EntrySignalAnalysisPrimaryStats(BaseModel):
    count: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    win_rate: float | None = None
    avg_return_pct: float | None = None
    median_return_pct: float | None = None
    mean_minus_median_pct: float | None = None
    mean_gt_median: bool | None = None
    avg_loss_pct: float | None = None
    trimmed_mean_1pct_return_pct: float | None = None
    trimmed_mean_5pct_return_pct: float | None = None
    winsorized_mean_1pct_return_pct: float | None = None
    winsorized_mean_5pct_return_pct: float | None = None
    p10_return_pct: float | None = None
    p25_return_pct: float | None = None
    p50_return_pct: float | None = None
    p75_return_pct: float | None = None
    p90_return_pct: float | None = None
    p01_return_pct: float | None = None
    p05_return_pct: float | None = None
    p95_return_pct: float | None = None
    p99_return_pct: float | None = None
    max_return_pct: float | None = None
    min_return_pct: float | None = None
    total_sum_return_pct: float | None = None
    top_1pct_sum_return_pct: float | None = None
    top_5pct_sum_return_pct: float | None = None
    bottom_1pct_sum_return_pct: float | None = None
    bottom_5pct_sum_return_pct: float | None = None
    top_1pct_contribution_ratio: float | None = None
    top_5pct_contribution_ratio: float | None = None
    bottom_1pct_contribution_ratio: float | None = None
    bottom_5pct_contribution_ratio: float | None = None
    net_without_top_1pct_return_pct: float | None = None
    net_without_top_5pct_return_pct: float | None = None
    net_without_bottom_1pct_return_pct: float | None = None
    net_without_bottom_5pct_return_pct: float | None = None


class EntrySignalAnalysisPrimaryGroupSummary(BaseModel):
    group_key: str
    group_label: str
    stats: EntrySignalAnalysisPrimaryStats
    strength_min: float | None = None
    strength_max: float | None = None


class EntrySignalAnalysisPrimaryStrategyRiskRanking(BaseModel):
    rank: int
    group_key: str
    group_label: str
    entry_strategy: str
    entry_filter_name: str
    stats: EntrySignalAnalysisPrimaryStats
    primary_score: int
    secondary_score: int
    avg_loss_rank: int
    p10_rank: int
    p25_rank: int
    median_return_rank: int
    win_rate_rank: int
    count_rank: int


class EntrySignalAnalysisPrimaryStrategyTailRobustnessRanking(BaseModel):
    rank: int
    group_key: str
    group_label: str
    entry_strategy: str
    entry_filter_name: str
    stats: EntrySignalAnalysisPrimaryStats
    primary_score: int
    secondary_score: int
    trimmed_mean_5pct_rank: int
    median_return_rank: int
    top_5pct_contribution_rank: int
    p10_rank: int
    avg_loss_rank: int
    count_rank: int
    avg_return_rank: int


class EntrySignalAnalysisPrimaryHorizonValidation(BaseModel):
    primary_horizon: int
    primary_horizon_label: str
    primary_return_column: str
    signal_strength_metric: SignalStrengthMetric | None = None
    signal_strength_bucket_method: str | None = None
    market_regime_source: str | None = None
    market_regime_status: str = "unavailable"
    market_regime_definition: str | None = None
    overall: EntrySignalAnalysisPrimaryStats
    by_year: list[EntrySignalAnalysisPrimaryGroupSummary] = Field(default_factory=list)
    by_month: list[EntrySignalAnalysisPrimaryGroupSummary] = Field(default_factory=list)
    by_strategy: list[EntrySignalAnalysisPrimaryGroupSummary] = Field(default_factory=list)
    by_strategy_bucket: list[EntrySignalAnalysisPrimaryGroupSummary] = Field(default_factory=list)
    by_market_regime: list[EntrySignalAnalysisPrimaryGroupSummary] = Field(default_factory=list)
    by_entry_filter: list[EntrySignalAnalysisPrimaryGroupSummary] = Field(default_factory=list)
    by_signal_strength_bucket: list[EntrySignalAnalysisPrimaryGroupSummary] = Field(default_factory=list)
    by_strategy_risk: list[EntrySignalAnalysisPrimaryStrategyRiskRanking] = Field(default_factory=list)
    by_strategy_tail_robustness: list[EntrySignalAnalysisPrimaryStrategyTailRobustnessRanking] = Field(default_factory=list)


class EntrySignalAnalysisTopDailyWindows(BaseModel):
    primary_horizon: int
    primary_horizon_label: str
    sort_column: str
    windows: list[dict[str, object]] = Field(default_factory=list)


class EntrySignalAnalysisRunSummary(BaseModel):
    generated_at: str
    request: dict[str, object]
    candidate_count: int
    selected_count: int
    trading_day_count: int
    strategy_count: int
    effective_entry_filter_mode: EntrySignalEntryFilterMode | None = None
    effective_entry_filter_names: list[str] = Field(default_factory=list)
    overall: dict[str, object]
    primary_horizon_validation: EntrySignalAnalysisPrimaryHorizonValidation
    primary_horizon_validations: list[EntrySignalAnalysisPrimaryHorizonValidation] = Field(default_factory=list)
    per_strategy: list[dict[str, object]]
    top_daily_windows: list[dict[str, object]]
    top_daily_windows_by_horizon: list[EntrySignalAnalysisTopDailyWindows] = Field(default_factory=list)
    artifacts: EntrySignalAnalysisArtifacts
