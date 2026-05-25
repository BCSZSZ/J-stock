"""Pydantic response schemas for the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


def _validate_atr_runtime_fields(model: BaseModel) -> BaseModel:
    risk_per_trade_pct = getattr(model, "risk_per_trade_pct", None)
    if risk_per_trade_pct is not None and risk_per_trade_pct <= 0:
        raise ValueError("risk_per_trade_pct must be greater than 0")

    atr_stop_multiple = getattr(model, "atr_stop_multiple", None)
    if atr_stop_multiple is not None and atr_stop_multiple <= 0:
        raise ValueError("atr_stop_multiple must be greater than 0")

    atr_ratio_min = getattr(model, "atr_ratio_min", None)
    if atr_ratio_min is not None and atr_ratio_min < 0:
        raise ValueError("atr_ratio_min must be greater than or equal to 0")

    atr_ratio_max = getattr(model, "atr_ratio_max", None)
    if atr_ratio_max is not None and atr_ratio_max <= 0:
        raise ValueError("atr_ratio_max must be greater than 0")

    if (
        atr_ratio_min is not None
        and atr_ratio_max is not None
        and atr_ratio_min > atr_ratio_max
    ):
        raise ValueError("atr_ratio_min must be less than or equal to atr_ratio_max")
    return model


class HealthResponse(BaseModel):
    status: str
    version: str


class PositionOut(BaseModel):
    ticker: str
    quantity: int
    entry_price: float
    entry_date: str
    entry_score: float
    peak_price: float
    lot_id: str
    current_price: float | None = None
    current_value: float | None = None


class StrategyGroupOut(BaseModel):
    id: str
    name: str
    initial_capital: float
    cash: float
    net_cash_flow: float = 0.0
    total_capital: float = 0.0
    holdings_value: float = 0.0
    current_value: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    positions: list[PositionOut]


class PortfolioResponse(BaseModel):
    groups: list[StrategyGroupOut]
    last_updated: str


class PortfolioHistoryPoint(BaseModel):
    date: str
    total_capital: float
    current_value: float
    total_pnl: float
    total_pnl_pct: float
    topix_value: float | None = None
    nikkei225_value: float | None = None
    normalized_portfolio: float | None = None
    normalized_topix: float | None = None
    normalized_nikkei225: float | None = None


class PortfolioHistoryResponse(BaseModel):
    points: list[PortfolioHistoryPoint]


class SectorPeriodOut(BaseModel):
    key: str
    label: str
    start_date: str
    end_date: str


class SectorPeriodPnLOut(BaseModel):
    period_key: str
    pnl: float
    start_value: float
    end_value: float
    buy_amount: float
    sell_amount: float


class SectorAttributionOut(BaseModel):
    sector: str
    current_value: float
    summary_periods: list[SectorPeriodPnLOut]
    heatmap_periods: list[SectorPeriodPnLOut]


class SectorAttributionResponse(BaseModel):
    as_of_date: str
    summary_periods: list[SectorPeriodOut]
    heatmap_periods: list[SectorPeriodOut]
    sectors: list[SectorAttributionOut]


class TradeEvent(BaseModel):
    date: str
    ticker: str
    action: str
    quantity: int
    price: float
    reason: str | None = None


class SignalOut(BaseModel):
    group_id: str
    ticker: str
    signal_type: str
    action: str
    confidence: float
    score: float
    reason: str | None = None
    current_price: float | None = None
    strategy_name: str | None = None


class StrategyInfo(BaseModel):
    name: str
    type: str
    category: str
    description: str
    parameters: list[dict[str, str]]


class EvaluationRunRequest(BaseModel):
    command: Literal[
        "evaluate",
        "pos-evaluation",
        "walk-forward-evaluate",
        "replay-evaluation",
    ] = (
        "evaluate"
    )
    buy_fill_mode: Literal["next_open", "next_close"] = "next_open"
    buy_fill_modes: list[Literal["next_open", "next_close"]] | None = None
    entry_reference_mode: Literal["raw_fill", "buffered_fill"] = "raw_fill"
    entry_reference_modes: list[Literal["raw_fill", "buffered_fill"]] | None = None
    fill_buffer_enabled: bool = False
    fill_buffer_pct: float = Field(default=0.02, ge=0.0, lt=1.0)
    capacity_regime_mode: Literal["off", "enforce"] | None = None
    override_strategies: bool = False
    entry_strategies: list[str] | None = None
    exit_strategies: list[str] | None = None
    mode: Literal["annual", "quarterly", "monthly", "custom"] = "annual"
    years: list[int] | None = None
    months: list[int] | None = None
    custom_periods: str | None = None
    launch_date: str | None = None
    launch_dates: list[str] | None = None
    min_train_years: int | None = None
    ranking_mode: Literal["prs_train"] | None = "prs_train"
    ranking_strategies: list[str] | None = None
    exit_confirm_days: int | None = None
    enable_overlay: bool = False
    overlay_modes: list[Literal["off", "on"]] | None = None
    entry_filter_mode: Literal["auto", "off", "single", "grid"] = "off"
    entry_filter_names: list[str] | None = None
    position_file: str | None = None
    profile_names: list[str] | None = None
    report_file: str | None = None
    universe_files: list[str] | None = None
    universe_pool_ids: list[str] | None = None
    position_sizing_mode: Literal["fixed", "atr"] | None = None
    risk_per_trade_pct: float | None = None
    atr_stop_multiple: float | None = None
    atr_ratio_min: float | None = None
    atr_ratio_max: float | None = None
    output_dir: str | None = None
    verbose: bool = False

    @model_validator(mode="after")
    def validate_atr_runtime_fields(self) -> "EvaluationRunRequest":
        _validate_atr_runtime_fields(self)
        return self


class EntryAnalysisManualRange(BaseModel):
    label: str | None = None
    min: float | None = None
    max: float | None = None


class EntryAnalysisRule(BaseModel):
    feature: str
    mode: Literal["manual", "sliding", "fixed", "quantile", "categorical"] = "sliding"
    label: str | None = None
    ranges: list[EntryAnalysisManualRange] = Field(default_factory=list)
    min: float | None = None
    max: float | None = None
    window: float | None = None
    step: float | None = None
    bin_width: float | None = None
    quantiles: int | None = None
    include_null: bool = False


class EntryAnalysisRunRequest(BaseModel):
    entry_strategies: list[str] | None = None
    universe_files: list[str] | None = None
    start: str | None = None
    end: str | None = None
    years: list[int] | None = None
    horizons: list[int] = Field(default_factory=lambda: [3, 5, 10])
    primary_horizon: int = 5
    indicator_columns: list[str] | None = None
    rules: list[EntryAnalysisRule] | None = None
    preset_rules: str = "none"
    label_mode: Literal["signal_close", "next_open"] = "signal_close"
    min_samples: int = 30
    include_joint: bool = True
    save_candidates: bool = True
    limit: int | None = None
    data_root: str = "data"
    output_dir: str | None = None


class EntryAnalysisFeatureCondition(BaseModel):
    feature: str
    operator: Literal["between", ">=", ">", "<=", "<", "==", "!=", "is_null", "not_null"] = "between"
    min: float | None = None
    max: float | None = None
    value: str | float | bool | None = None


class EntryAnalysisAggregateRequest(BaseModel):
    conditions: list[EntryAnalysisFeatureCondition] = Field(default_factory=list)
    logic: Literal["all", "any"] = "all"
    horizons: list[int] = Field(default_factory=lambda: [3, 5, 10])
    group_by: str | None = None
    min_samples: int = 1


class ProductionDailyRequest(BaseModel):
    no_fetch: bool = False
    pool_id: str | None = None
    position_sizing_mode: Literal["fixed", "atr"] | None = None
    risk_per_trade_pct: float | None = None
    atr_stop_multiple: float | None = None
    atr_ratio_min: float | None = None
    atr_ratio_max: float | None = None
    confirm: bool = False

    @model_validator(mode="after")
    def validate_atr_runtime_fields(self) -> "ProductionDailyRequest":
        _validate_atr_runtime_fields(self)
        return self


class SetCashRequest(BaseModel):
    group_id: str = "group_main"
    amount: float
    confirm: bool = False


class InputTradeRequest(BaseModel):
    trades: list[TradeEvent]
    confirm: bool = False
    aws_profile: str | None = None
