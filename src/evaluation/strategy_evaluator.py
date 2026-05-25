"""
策略综合评价器
按年度、按市场环境评估策略组合表现

Performance Optimization:
- Preloaded data cache to eliminate repeated disk IO
"""

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import time
from collections import defaultdict

import pandas as pd

from src.analysis.signals import SignalAction, TradingSignal
from src.backtest.lot_size_manager import LotSizeManager
from src.backtest.entry_reference import normalize_entry_reference_mode
from src.backtest.fill_buffer import normalize_fill_buffer_pct
from src.evaluation.trade_indicator_enrichment import write_enriched_trades_sidecar
from src.evaluation.replay_seed import (
    ReplaySeed,
    build_replay_pending_signal,
    build_seeded_backtest_position,
)
from src.config.capacity import parse_capacity_regime, parse_evaluation_capacity_mode
from src.config.service import load_config
from src.config.runtime import CONFIG_ENV_VAR, GDRIVE_DEFAULT_CONFIG_FILE, get_config_file_path
from src.data.market_data_builder import MarketDataBuilder
from src.data.stock_data_manager import StockDataManager
from src.evaluation.scoring import apply_prs_train_score, candidate_key_columns, positive_ratio, robust_inverse_norm, robust_norm, summarize_prs_train_metrics
from src.overlays import OverlayManager
from src.production.report_builder import ReportBuilder
from src.production.signal_generator import Signal as ProductionSignal
from src.production.state_manager import (
    Position as ProductionPosition,
    ProductionState,
    StrategyGroupState,
)
from src.utils.atr_position_sizing import (
    AtrSizingInput,
    PortfolioSizingConfig,
    calculate_atr_position_size,
    parse_portfolio_sizing_config,
)
from src.utils.strategy_loader import get_strategy_complexity_penalty


@dataclass
class AnnualStrategyResult:
    """单个策略在单个年度/时间段的回测结果"""

    period: str  # "2021" 或 "2021-Q1" 或 "2021-01"
    start_date: str  # "2021-01-01"
    end_date: str  # "2021-12-31"
    entry_strategy: str  # "SimpleScorerStrategy"
    exit_strategy: str  # "LayeredExitStrategy"
    entry_filter: str  # "default" / "trend_strict" ...
    return_pct: float  # 策略收益率
    topix_return_pct: Optional[float]  # TOPIX收益率（可能为None）
    alpha: Optional[float]  # 超额收益率（无TOPIX数据时为None）
    sharpe_ratio: float
    max_drawdown_pct: float
    num_trades: int
    win_rate_pct: float
    avg_gain_pct: float
    avg_loss_pct: float
    capacity_regime_mode: str = "off"
    capacity_regime_version: str = ""
    capacity_final_tier: str = ""
    capacity_peak_tier: str = ""
    capacity_effective_equity_jpy: float = 0.0
    capacity_peak_equity_jpy: float = 0.0
    capacity_effective_max_positions: int = 0
    capacity_effective_max_position_pct: float = 0.0
    capacity_participation_cap_pct: float = 0.0
    capacity_min_turnover_20_jpy: float = 0.0
    capacity_blocked_buys: int = 0
    capacity_liquidity_blocked_buys: int = 0
    capacity_trimmed_buys: int = 0
    capacity_avg_participation_pct: float = 0.0
    capacity_p95_participation_pct: float = 0.0
    capacity_cash_drag_jpy: float = 0.0
    exit_confirmation_days: int = 1
    ranking_strategy: str = "default"
    buy_fill_mode: str = "next_open"
    entry_reference_mode: str = "raw_fill"
    fill_buffer_enabled: bool = False
    fill_buffer_pct: float = 0.0


TRADE_EXPORT_COLUMNS = [
    "period",
    "start_date",
    "end_date",
    "market_regime",
    "topix_return_pct",
    "entry_strategy",
    "exit_strategy",
    "entry_filter",
    "ranking_strategy",
    "exit_confirmation_days",
    "buy_fill_mode",
    "entry_reference_mode",
    "fill_buffer_enabled",
    "fill_buffer_pct",
    "ticker",
    "entry_date",
    "entry_price",
    "entry_score",
    "entry_confidence",
    "entry_metadata_json",
    "exit_date",
    "exit_price",
    "exit_reason",
    "exit_urgency",
    "holding_days",
    "shares",
    "return_pct",
    "return_jpy",
    "peak_price",
    "position_quantity_before_exit",
    "position_quantity_after_exit",
    "exit_sell_percentage",
    "exit_is_full_exit",
    "exit_is_partial_exit",
    "capacity_regime_version",
    "capacity_tier_name",
    "capacity_effective_equity_jpy",
    "capacity_order_cap_jpy",
    "capacity_turnover_jpy",
    "capacity_participation_pct",
    "exit_metadata_json",
]


LAST_DAY_SIGNAL_COLUMNS = [
    "period",
    "requested_end_date",
    "snapshot_date",
    "entry_strategy",
    "exit_strategy",
    "entry_filter",
    "ranking_strategy",
    "signal_type",
    "ticker",
    "action",
    "confidence",
    "strategy_name",
    "reasons_json",
    "metadata_json",
]


LAST_DAY_POSITION_COLUMNS = [
    "period",
    "requested_end_date",
    "snapshot_date",
    "entry_strategy",
    "exit_strategy",
    "entry_filter",
    "ranking_strategy",
    "ticker",
    "quantity",
    "entry_date",
    "entry_price",
    "signal_entry_price",
    "peak_price",
    "current_price",
    "market_value",
]


DAILY_SIGNAL_COLUMNS = [
    "period",
    "requested_end_date",
    "snapshot_date",
    "entry_strategy",
    "exit_strategy",
    "entry_filter",
    "ranking_strategy",
    "signal_type",
    "ticker",
    "action",
    "confidence",
    "strategy_name",
    "reasons_json",
    "metadata_json",
]


DAILY_POSITION_COLUMNS = [
    "period",
    "requested_end_date",
    "snapshot_date",
    "entry_strategy",
    "exit_strategy",
    "entry_filter",
    "ranking_strategy",
    "ticker",
    "quantity",
    "entry_date",
    "entry_price",
    "signal_entry_price",
    "peak_price",
    "current_price",
    "market_value",
    "cash_jpy",
    "total_equity_jpy",
]


EXIT_REASON_DETAIL_COLUMNS = [
    "trade_scope",
    "period",
    "market_regime",
    "entry_strategy",
    "exit_strategy",
    "entry_filter",
    "exit_confirmation_days",
    "exit_urgency",
    "exit_reason",
    "trade_count",
    "period_trade_total",
    "trade_ratio",
    "avg_return_pct",
    "avg_holding_days",
    "win_rate_pct",
    "total_return_jpy",
]

EXIT_TRIGGER_SUMMARY_COLUMNS = EXIT_REASON_DETAIL_COLUMNS

EXIT_URGENCY_SUMMARY_COLUMNS = [
    "trade_scope",
    "period",
    "market_regime",
    "entry_strategy",
    "exit_strategy",
    "entry_filter",
    "exit_confirmation_days",
    "exit_urgency",
    "trade_count",
    "period_trade_total",
    "trade_ratio",
    "avg_return_pct",
    "avg_holding_days",
    "win_rate_pct",
    "total_return_jpy",
    "gross_profit_jpy",
    "gross_loss_jpy",
]

EXIT_URGENCY_CONTRIBUTION_COLUMNS = [
    "trade_scope",
    "entry_strategy",
    "exit_strategy",
    "entry_filter",
    "exit_confirmation_days",
    "exit_urgency",
    "trade_count",
    "strategy_trade_total",
    "trade_ratio",
    "avg_return_pct",
    "avg_holding_days",
    "win_rate_pct",
    "total_return_jpy",
    "gross_profit_jpy",
    "gross_loss_jpy",
    "strategy_total_return_jpy",
    "return_contribution_ratio",
]


def _fmt_pct(value: Any, digits: int = 2) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value):.{digits}f}%"


def _fmt_num(value: Any, digits: int = 2) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value):.{digits}f}"


def _fmt_ratio(value: Any, digits: int = 1) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value) * 100:.{digits}f}%"


def _fmt_jpy(value: Any) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value):,.0f}"


class MarketRegime:
    """市场环境分类"""

    BEAR_MARKET = "熊市 (TOPIX < 0%)"
    MILD_BULL = "温和牛市 (TOPIX 0-25%)"
    STRONG_BULL = "强劲牛市 (TOPIX 25-50%)"
    SUPER_BULL = "超级牛市 (TOPIX 50-75%)"
    EXTREME_BULL = "极端牛市 (TOPIX > 75%)"

    @staticmethod
    def classify(topix_return: Optional[float]) -> str:
        """根据TOPIX收益率分类市场环境"""
        if topix_return is None:
            return "未知市场环境 (TOPIX数据缺失)"

        if topix_return < 0:
            return MarketRegime.BEAR_MARKET
        elif topix_return < 25:
            return MarketRegime.MILD_BULL
        elif topix_return < 50:
            return MarketRegime.STRONG_BULL
        elif topix_return < 75:
            return MarketRegime.SUPER_BULL
        else:
            return MarketRegime.EXTREME_BULL


def _minmax_normalize_series(series: pd.Series, higher_is_better: bool) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").fillna(0.0)
    s_min = float(s.min())
    s_max = float(s.max())
    span = s_max - s_min
    if span <= 1e-12:
        return pd.Series([0.5] * len(s), index=s.index)
    if higher_is_better:
        return (s - s_min) / span
    return (s_max - s) / span


def rank_target20_goal_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    key_cols = candidate_key_columns(df)
    rows = []

    for key, combo_df in df.groupby(key_cols):
        combo_df = combo_df.copy()
        returns = pd.to_numeric(combo_df["return_pct"], errors="coerce").fillna(0.0)
        topix = pd.to_numeric(combo_df["topix_return_pct"], errors="coerce")
        mdd = pd.to_numeric(combo_df["max_drawdown_pct"], errors="coerce").fillna(0.0)

        period_count = int(len(combo_df))
        hit20_rate = float((returns >= 20.0).mean()) if period_count > 0 else 0.0
        shortfall_mean = (
            float((20.0 - returns).clip(lower=0.0).mean()) if period_count > 0 else 20.0
        )
        loss_period_rate = float((returns < 0.0).mean()) if period_count > 0 else 1.0
        worst_period_return = float(returns.min()) if period_count > 0 else -999.0
        mean_return = float(returns.mean()) if period_count > 0 else 0.0
        avg_mdd = float(mdd.mean()) if period_count > 0 else 99.0

        soft_hit20_score = (
            float((returns / 20.0).clip(lower=0.0, upper=1.0).mean())
            if period_count > 0
            else 0.0
        )
        mean_return_component = min(1.0, max(0.0, mean_return / 30.0))
        no_loss_component = 1.0 - loss_period_rate

        bull_mask = topix.notna() & (topix >= 0.0)
        bear_mask = topix.notna() & (topix < 0.0)
        bull_count = int(bull_mask.sum())
        bear_count = int(bear_mask.sum())

        bull_loss_rate = (
            float(((returns < 0.0) & bull_mask).sum()) / bull_count
            if bull_count > 0
            else 0.0
        )
        bear_hit20_rate = (
            float(((returns >= 20.0) & bear_mask).sum()) / bear_count
            if bear_count > 0
            else 0.0
        )

        w_u, w_m, w_p = 0.42, 0.38, 0.20
        base_score = 100.0 * (
            w_u * soft_hit20_score
            + w_m * mean_return_component
            + w_p * no_loss_component
        )

        if worst_period_return >= 0.0:
            penalty_worst = 0.0
        else:
            penalty_worst = min(30.0, abs(worst_period_return) * 2.0)

        penalty_loss_ratio = min(
            10.0, max(0.0, loss_period_rate - 0.20) * 40.0
        )
        penalty_bull_loss = min(25.0, bull_loss_rate * 100.0)
        penalty_avg_mdd = min(8.0, max(0.0, avg_mdd - 12.0) * 0.5)
        bonus_bear = 0.0

        risk_penalty_total = (
            penalty_worst
            + penalty_loss_ratio
            + penalty_bull_loss
            + penalty_avg_mdd
        )
        final_score = max(0.0, min(100.0, base_score + bonus_bear - risk_penalty_total))

        row = {
            "period_count": period_count,
            "hit20_rate": hit20_rate,
            "soft_hit20_score": soft_hit20_score,
            "shortfall_mean": shortfall_mean,
            "loss_period_rate": loss_period_rate,
            "bull_loss_rate": bull_loss_rate,
            "bear_hit20_rate": bear_hit20_rate,
            "worst_period_return": worst_period_return,
            "avg_mdd": avg_mdd,
            "mean_return": mean_return,
            "mean_return_component": mean_return_component,
            "no_loss_component": no_loss_component,
            "base_score": base_score,
            "bonus_bear": bonus_bear,
            "penalty_worst": penalty_worst,
            "penalty_loss_ratio": penalty_loss_ratio,
            "penalty_bull_loss": penalty_bull_loss,
            "penalty_avg_mdd": penalty_avg_mdd,
            "risk_penalty_total": risk_penalty_total,
            "target20_score": final_score,
        }
        row.update(dict(zip(key_cols, key)))
        rows.append(row)

    rank_df = pd.DataFrame(rows)
    if rank_df.empty:
        return rank_df

    rank_df = rank_df.sort_values(
        [
            "target20_score",
            "soft_hit20_score",
            "mean_return",
            "hit20_rate",
            "loss_period_rate",
            "worst_period_return",
        ],
        ascending=[False, False, False, False, True, False],
    ).reset_index(drop=True)
    rank_df.insert(0, "rank", range(1, len(rank_df) + 1))
    return rank_df


def rank_legacy_goal_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    working = df.copy()
    working["market_regime"] = working["topix_return_pct"].apply(MarketRegime.classify)

    key_cols = candidate_key_columns(working)
    strategy_performance = {}
    for regime in working["market_regime"].unique():
        regime_df = working[working["market_regime"] == regime].copy()
        has_alpha = (
            regime_df["alpha"].notna().any()
            and regime_df["topix_return_pct"].notna().any()
        )
        if has_alpha and regime_df["alpha"].sum() != 0:
            regime_df["legacy_rank"] = regime_df["alpha"].rank(ascending=False)
        else:
            regime_df["legacy_rank"] = regime_df["return_pct"].rank(ascending=False)

        for _, row in regime_df.iterrows():
            key = tuple(row[col] for col in key_cols)
            if key not in strategy_performance:
                strategy_performance[key] = []
            strategy_performance[key].append(float(row["legacy_rank"]))

    rows = []
    for key, ranks in strategy_performance.items():
        combo_mask = pd.Series(True, index=working.index)
        for index, column in enumerate(key_cols):
            combo_mask &= working[column] == key[index]
        combo_df = working[combo_mask]
        row = {
            "avg_rank": float(sum(ranks) / len(ranks)) if ranks else 999.0,
            "mean_return": float(combo_df["return_pct"].mean()) if not combo_df.empty else 0.0,
            "mean_alpha": float(combo_df["alpha"].mean()) if not combo_df.empty else 0.0,
            "mean_sharpe": float(combo_df["sharpe_ratio"].mean()) if not combo_df.empty else 0.0,
            "mean_win_rate": float(combo_df["win_rate_pct"].mean()) if not combo_df.empty else 0.0,
        }
        row.update(dict(zip(key_cols, key)))
        rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out = out.sort_values(["avg_rank", "mean_return"], ascending=[True, False]).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


def rank_risk60_profit40_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    key_cols = candidate_key_columns(df)
    grouped = (
        df.groupby(key_cols)
        .agg(
            avg_return=("return_pct", "mean"),
            avg_alpha=("alpha", "mean"),
            avg_mdd=("max_drawdown_pct", "mean"),
            worst_year_return=("return_pct", "min"),
            period_count=("period", "nunique"),
            positive_alpha_ratio=("alpha", lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean())),
        )
        .reset_index()
    )

    grouped["avg_alpha"] = pd.to_numeric(grouped["avg_alpha"], errors="coerce").fillna(0.0)
    grouped["positive_alpha_ratio"] = pd.to_numeric(
        grouped["positive_alpha_ratio"], errors="coerce"
    ).fillna(0.0)

    grouped["mdd_inverse_norm"] = _minmax_normalize_series(grouped["avg_mdd"], higher_is_better=False)
    grouped["worst_year_return_norm"] = _minmax_normalize_series(
        grouped["worst_year_return"], higher_is_better=True
    )
    grouped["avg_alpha_norm"] = _minmax_normalize_series(grouped["avg_alpha"], higher_is_better=True)
    grouped["positive_alpha_ratio_norm"] = _minmax_normalize_series(
        grouped["positive_alpha_ratio"], higher_is_better=True
    )

    grouped["risk60_profit40_score"] = (
        grouped["mdd_inverse_norm"] * 0.35
        + grouped["worst_year_return_norm"] * 0.25
        + grouped["avg_alpha_norm"] * 0.25
        + grouped["positive_alpha_ratio_norm"] * 0.15
    )

    grouped = grouped.sort_values(
        ["risk60_profit40_score", "avg_alpha"],
        ascending=[False, False],
    ).reset_index(drop=True)
    grouped.insert(0, "rank", range(1, len(grouped) + 1))
    return grouped


def rank_prs_train_df(
    df: pd.DataFrame,
    complexity_penalty_resolver: Optional[Callable[[str, str], float]] = None,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    resolver = complexity_penalty_resolver or get_strategy_complexity_penalty
    train_summary_df = summarize_prs_train_metrics(df)
    return apply_prs_train_score(
        train_summary_df,
        complexity_penalty_resolver=resolver,
    )


def select_rank_df_for_mode(
    df: pd.DataFrame,
    ranking_mode: str,
    complexity_penalty_resolver: Optional[Callable[[str, str], float]] = None,
) -> Tuple[pd.DataFrame, str]:
    if ranking_mode == "legacy":
        return rank_legacy_goal_df(df), "avg_rank"
    if ranking_mode == "risk60_profit40":
        return rank_risk60_profit40_df(df), "risk60_profit40_score"
    if ranking_mode == "prs_train":
        return rank_prs_train_df(
            df,
            complexity_penalty_resolver=complexity_penalty_resolver,
        ), "prs_train_score"
    return rank_target20_goal_df(df), "target20_score"


class StrategyEvaluator:
    """
    策略综合评价器

    功能：
    1. 批量执行年度/时间段回测
    2. 按市场环境分组分析
    3. 生成Markdown报告和CSV数据

    特点：
    - 不修改任何现有代码，只调用portfolio_engine
    - 支持灵活的时间段指定（整年/季度/月度/自定义）
    - 支持verbose模式和缓存优化
    """

    def __init__(
        self,
        data_root: str = "data",
        output_dir: str = "strategy_evaluation",
        monitor_list_file: Optional[str] = None,
        replay_seed: Optional[ReplaySeed] = None,
        verbose: bool = False,
        exit_confirmation_days: int = 1,
        overlay_config: Optional[Dict] = None,
        entry_filter_config: Optional[Dict] = None,
        entry_filter_variants: Optional[List[Tuple[str, Dict]]] = None,
        portfolio_overrides: Optional[Dict] = None,
        use_cache: bool = True,
        ranking_strategies: Optional[List[str]] = None,
        buy_fill_mode: str = "next_open",
        entry_reference_mode: str = "raw_fill",
        fill_buffer_enabled: bool = False,
        fill_buffer_pct: float = 0.02,
        capacity_regime_mode_override: Optional[str] = None,
    ):
        """
        Initialize strategy evaluator.

        Args:
            data_root: Root directory for data files
            output_dir: Output directory for results
            verbose: Enable detailed progress output
            overlay_config: Configuration for overlay manager
            entry_filter_config: Entry secondary filter configuration
            entry_filter_variants: Named filter variants for evaluation combinations
            use_cache: Enable data preloading cache for performance (default: True)
        """
        self.data_root = data_root
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[AnnualStrategyResult] = []
        self.trade_results: List[Dict[str, Any]] = []
        self._results_df_cache: Optional[pd.DataFrame] = None
        self._trade_results_df_cache: Optional[pd.DataFrame] = None
        self.verbose = verbose  # 详细输出模式
        self.use_cache = use_cache  # Data cache flag
        self.exit_confirmation_days = max(1, int(exit_confirmation_days))
        self.buy_fill_mode = str(buy_fill_mode or "next_open").strip().lower()
        self.entry_reference_mode = normalize_entry_reference_mode(
            entry_reference_mode
        )
        self.fill_buffer_enabled = bool(fill_buffer_enabled)
        self.fill_buffer_pct = normalize_fill_buffer_pct(fill_buffer_pct)
        self.monitor_list_file = monitor_list_file
        self.replay_seed = replay_seed
        self.entry_filter_config = entry_filter_config or {}
        self.entry_filter_variants = self._normalize_entry_filter_variants(
            entry_filter_variants
        )
        self.portfolio_overrides = portfolio_overrides or {}
        self.overlay_config = overlay_config or {}
        self.ranking_strategies = ranking_strategies or ["default"]
        self.replay_run_snapshots: List[Dict[str, object]] = []
        self.evaluation_run_snapshots: List[Dict[str, object]] = []
        self.evaluation_daily_snapshots: List[Dict[str, object]] = []
        self.capacity_regime_mode_override = (
            str(parse_evaluation_capacity_mode(capacity_regime_mode_override))
            if capacity_regime_mode_override is not None
            else None
        )

        self.overlay_manager = OverlayManager.from_config(
            self.overlay_config,
            data_root=self.data_root,
        )

        # 计时统计（单次run_evaluation内）
        self._timing_counters: Dict[str, float] = defaultdict(float)
        self._timing_counts: Dict[str, int] = defaultdict(int)
        self.last_timing_summary: Dict[str, object] = {}

        # 缓存层（单次运行内有效）
        self._monitor_list_cache = None  # Monitor list 缓存
        self._topix_cache: Dict[Tuple[str, str], Optional[float]] = {}  # TOPIX 缓存
        self._portfolio_limits_cache: Optional[Tuple[int, float]] = None
        self._portfolio_sizing_cache: Optional[PortfolioSizingConfig] = None
        self._starting_capital_cache: Optional[int] = None
        self._capacity_mode_cache: Optional[str] = None
        self._capacity_regime_cache = None

    def _build_seeded_positions(self, strategy_name: str):
        if self.replay_seed is None:
            return []

        return [
            build_seeded_backtest_position(position, strategy_name)
            for position in self.replay_seed.positions
        ]

    def _build_initial_pending_signals(self):
        if self.replay_seed is None:
            return {}, {}

        buy_signals = {}
        sell_signals = {}
        for priority, order in enumerate(self.replay_seed.pending_orders):
            signal = build_replay_pending_signal(order, priority=priority)
            if order.signal_type == "BUY":
                buy_signals[order.ticker] = signal
                continue
            sell_signals[order.ticker] = signal

        return buy_signals, sell_signals

    def _get_starting_capital(self) -> int:
        """
        Load starting capital from overrides or config.json.

        Priority:
        1) portfolio_overrides.starting_capital_jpy
        2) config.json evaluation.starting_capital_jpy
        3) fallback 8,000,000 JPY
        """
        if self._starting_capital_cache is not None:
            return self._starting_capital_cache

        override_capital = self.portfolio_overrides.get("starting_capital_jpy")
        if override_capital is not None:
            try:
                value = int(override_capital)
                if value > 0:
                    self._starting_capital_cache = value
                    return self._starting_capital_cache
            except Exception:
                pass

        try:
            config = load_config()
            eval_cfg = config.get("evaluation", {})
            value = int(eval_cfg.get("starting_capital_jpy", 8_000_000))
            if value > 0:
                self._starting_capital_cache = value
                return self._starting_capital_cache
        except Exception:
            pass

        self._starting_capital_cache = 8_000_000
        return self._starting_capital_cache

    def _get_capacity_regime_mode(self) -> str:
        if self.capacity_regime_mode_override is not None:
            return self.capacity_regime_mode_override

        if self._capacity_mode_cache is not None:
            return self._capacity_mode_cache

        try:
            config = load_config()
            evaluation_cfg = config.get("evaluation", {})
            self._capacity_mode_cache = str(
                evaluation_cfg.get("capacity_regime_mode", "off")
            )
            return self._capacity_mode_cache
        except Exception:
            self._capacity_mode_cache = "off"
            return self._capacity_mode_cache

    def _get_capacity_regime(self):
        if self._capacity_regime_cache is not None:
            return self._capacity_regime_cache

        try:
            config = load_config()
            self._capacity_regime_cache = parse_capacity_regime(
                config.get("capacity_regime")
            )
            return self._capacity_regime_cache
        except Exception:
            self._capacity_regime_cache = None
            return self._capacity_regime_cache

    def _normalize_entry_filter_variants(
        self, variants: Optional[List[Tuple[str, Dict]]]
    ) -> List[Tuple[str, Dict]]:
        if variants:
            normalized: List[Tuple[str, Dict]] = []
            for idx, item in enumerate(variants, 1):
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    continue
                name, cfg = item
                if not isinstance(cfg, dict):
                    continue
                variant_name = str(name).strip() or f"filter_{idx}"
                normalized.append((variant_name, cfg))
            if normalized:
                return normalized

        return [("default", self.entry_filter_config)]

    def _get_portfolio_limits(self) -> Tuple[int, float]:
        """
        Load portfolio limits from config.json once.

        Returns:
            (max_positions, max_position_pct)
        """
        sizing = self._get_portfolio_sizing_config()
        self._portfolio_limits_cache = (sizing.max_positions, sizing.max_position_pct)
        return self._portfolio_limits_cache

    def _get_portfolio_sizing_config(self) -> PortfolioSizingConfig:
        if self._portfolio_sizing_cache is not None:
            return self._portfolio_sizing_cache

        try:
            config = load_config()
            portfolio_cfg = config.get("portfolio", {})
        except Exception:
            portfolio_cfg = {}

        self._portfolio_sizing_cache = parse_portfolio_sizing_config(
            portfolio_cfg,
            self.portfolio_overrides,
        )
        return self._portfolio_sizing_cache

    def run_evaluation(
        self,
        periods: List[Tuple[str, str, str]],
        entry_strategies: List[str] = None,
        exit_strategies: List[str] = None,
        preloaded_cache_override=None,
    ) -> pd.DataFrame:
        """
        执行批量策略评估（并行优化版本）

        Args:
            periods: [(period_label, start_date, end_date), ...]
                    例如: [("2021", "2021-01-01", "2021-12-31"),
                           ("2022-Q1", "2022-01-01", "2022-03-31")]
            entry_strategies: 入场策略列表（默认全部）
            exit_strategies: 出场策略列表（默认全部）

        Returns:
            DataFrame包含所有回测结果
        """
        from src.utils.strategy_loader import ENTRY_STRATEGIES, EXIT_STRATEGIES

        self.results = []
        self.trade_results = []
        self._results_df_cache = None
        self._trade_results_df_cache = None
        self.evaluation_run_snapshots = []
        self.evaluation_daily_snapshots = []

        # 默认使用全部策略
        if entry_strategies is None:
            entry_strategies = list(ENTRY_STRATEGIES.keys())
        if exit_strategies is None:
            exit_strategies = list(EXIT_STRATEGIES.keys())

        def _fmt_hms(total_seconds: float) -> str:
            sec = max(0, int(total_seconds))
            h = sec // 3600
            m = (sec % 3600) // 60
            s = sec % 60
            return f"{h:02d}:{m:02d}:{s:02d}"

        def _log_step(message: str) -> None:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

        _log_step("evaluator: run_evaluation 启动")
        run_started = time.perf_counter()
        self._timing_counters = defaultdict(float)
        self._timing_counts = defaultdict(int)

        def _phase_timer_start() -> float:
            return time.perf_counter()

        def _phase_timer_end(name: str, started: float):
            self._timing_counters[name] += time.perf_counter() - started
            self._timing_counts[name] += 1

        _log_step("evaluator: 开始加载 monitor list")
        phase_started = _phase_timer_start()
        tickers = self._load_monitor_list()
        _phase_timer_end("phase_load_monitor_list", phase_started)
        _log_step(f"evaluator: monitor list 完成 (tickers={len(tickers)})")

        total_backtests = (
            len(periods)
            * len(entry_strategies)
            * len(exit_strategies)
            * len(self.entry_filter_variants)
            * len(self.ranking_strategies)
        )

        # 总是显示的基本信息
        print(f"\n{'=' * 80}")
        print("🎯 策略综合评价")
        print(f"{'=' * 80}")
        print(f"   时间段数量: {len(periods)}")
        print(f"   入场策略: {len(entry_strategies)}个")
        print(f"   出场策略: {len(exit_strategies)}个")
        print(f"   入场过滤器: {len(self.entry_filter_variants)}个")
        print(f"   排序策略: {len(self.ranking_strategies)}个")
        print(f"   总回测次数: {total_backtests}")
        print(f"   数据缓存: {'启用' if self.use_cache else '禁用'}")
        print(f"   输出模式: {'详细' if self.verbose else '简洁'}")
        print(f"{'=' * 80}\n")

        # Step 1: Preload data cache (if enabled)
        preloaded_cache = preloaded_cache_override
        if preloaded_cache is not None:
            memory_dict = preloaded_cache.get_memory_usage()
            total_mb = sum(memory_dict.values())
            print(f"📦 复用预加载数据缓存: {len(tickers)}只股票, {total_mb:.2f} MB\n")
            _log_step(f"evaluator: 复用外部数据缓存 ({total_mb:.2f} MB)")
        elif self.use_cache:
            _log_step("evaluator: 开始预加载数据缓存")
            phase_started = _phase_timer_start()
            print("📦 预加载数据缓存...")
            try:
                preloaded_cache = self._prepare_preloaded_cache(
                    tickers=tickers,
                    periods=periods,
                    entry_strategies=entry_strategies,
                    exit_strategies=exit_strategies,
                )

                memory_dict = preloaded_cache.get_memory_usage()
                total_mb = sum(memory_dict.values())
                print(f"✅ 缓存加载完成: {len(tickers)}只股票, {total_mb:.2f} MB\n")
                include_trades, include_financials, include_metadata = (
                    self._resolve_aux_preload_flags(
                        entry_strategies=entry_strategies,
                        exit_strategies=exit_strategies,
                        entry_mapping=ENTRY_STRATEGIES,
                        exit_mapping=EXIT_STRATEGIES,
                    )
                )
                print(
                    "   缓存内容: "
                    f"trades={'on' if include_trades else 'off'}, "
                    f"financials={'on' if include_financials else 'off'}, "
                    f"metadata={'on' if include_metadata else 'off'}"
                )
                _log_step(f"evaluator: 数据缓存完成 ({total_mb:.2f} MB)")
            except Exception as e:
                print(f"⚠️  缓存加载失败，继续串行并禁用缓存: {e}\n")
                preloaded_cache = None
                _log_step("evaluator: 缓存加载失败，已禁用缓存")
            _phase_timer_end("phase_preload_cache", phase_started)
        else:
            _log_step("evaluator: 数据缓存关闭")

        # Step 2: Prepare TOPIX cache
        _log_step("evaluator: 开始预加载 TOPIX")
        phase_started = _phase_timer_start()
        print("📊 预加载TOPIX基准数据...")
        for period_label, start_date, end_date in periods:
            cache_key = (start_date, end_date)
            if cache_key not in self._topix_cache:
                self._topix_cache[cache_key] = self._get_topix_return(
                    start_date, end_date
                )
        print("✅ TOPIX数据缓存完成\n")
        _phase_timer_end("phase_preload_topix", phase_started)
        _log_step("evaluator: TOPIX 预加载完成")

        # Step 3: Create task list
        phase_started = _phase_timer_start()
        tasks = []
        for period_label, start_date, end_date in periods:
            topix_return = self._topix_cache.get((start_date, end_date))
            for entry in entry_strategies:
                for exit in exit_strategies:
                    for filter_name, filter_cfg in self.entry_filter_variants:
                        for ranking_name in self.ranking_strategies:
                            tasks.append(
                                {
                                    "period_label": period_label,
                                    "start_date": start_date,
                                    "end_date": end_date,
                                    "entry_strategy": entry,
                                    "exit_strategy": exit,
                                    "entry_filter": filter_name,
                                    "entry_filter_config": filter_cfg,
                                    "topix_return": topix_return,
                                    "ranking_strategy": ranking_name,
                                }
                            )
        _phase_timer_end("phase_build_tasks", phase_started)
        _log_step(f"evaluator: 任务列表完成 (tasks={len(tasks)})")

        # Step 4: Execute backtests (serial)
        phase_started = _phase_timer_start()
        print(f"🚀 开始执行 {len(tasks)} 个回测任务...", flush=True)
        print("   进度字段: 时间, 完成数/总数, 成功, 失败, 百分比, 已耗时, 吞吐, ETA, 预计完成时刻", flush=True)
        completed = 0
        success_count = 0
        error_count = 0
        run_started_monotonic = time.monotonic()
        last_progress_print = run_started_monotonic

        for task in tasks:
            completed += 1
            progress = (completed / total_backtests) * 100

            if self.verbose:
                print(
                    f"[{completed}/{total_backtests} {progress:.1f}%] "
                    f"{task['entry_strategy']} × {task['exit_strategy']} × {task['entry_filter']}"
                    f" × rank:{task['ranking_strategy']}... ",
                    end="",
                    flush=True,
                )

            try:
                result = self._run_single_backtest(
                    period_label=task["period_label"],
                    start_date=task["start_date"],
                    end_date=task["end_date"],
                    entry_strategy=task["entry_strategy"],
                    exit_strategy=task["exit_strategy"],
                    entry_filter_name=task["entry_filter"],
                    entry_filter_config=task["entry_filter_config"],
                    topix_return=task["topix_return"],
                    preloaded_cache=preloaded_cache,
                    ranking_strategy=task["ranking_strategy"],
                )

                self.results.append(result)
                self._results_df_cache = None
                success_count += 1

                if self.verbose:
                    alpha_str = (
                        f"{result.alpha:>6.2f}%"
                        if result.alpha is not None
                        else "   N/A "
                    )
                    print(f"✓ Return: {result.return_pct:>6.2f}%, Alpha: {alpha_str}")
            except Exception as e:
                error_count += 1
                if self.verbose:
                    print(f"✗ Error: {str(e)}")

            # 简洁模式：周期性输出进度+ETA，避免长时间无反馈
            if not self.verbose:
                now = time.monotonic()
                should_print = (
                    completed == total_backtests
                    or completed == 1
                    or completed % 10 == 0
                    or (now - last_progress_print) >= 5.0
                )

                if should_print:
                    elapsed_sec = now - run_started_monotonic
                    speed = (completed / elapsed_sec) if elapsed_sec > 0 else 0.0

                    eta_str = "warming-up"
                    finish_str = "warming-up"
                    if completed >= 5 and speed > 0:
                        eta_sec = (total_backtests - completed) / speed
                        eta_str = _fmt_hms(eta_sec)
                        finish_str = (datetime.now() + timedelta(seconds=eta_sec)).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )

                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] "
                        f"[{completed}/{total_backtests}] "
                        f"ok={success_count} err={error_count} "
                        f"({progress:.1f}%) "
                        f"elapsed={_fmt_hms(elapsed_sec)} "
                        f"speed={speed:.3f} task/s "
                        f"ETA={eta_str} "
                        f"finish={finish_str}",
                        flush=True,
                    )
                    last_progress_print = now

        _phase_timer_end("phase_execute_tasks", phase_started)

        total_elapsed_sec = time.monotonic() - run_started_monotonic
        avg_sec_per_task = (
            total_elapsed_sec / completed if completed > 0 else 0.0
        )
        print(f"\n{'=' * 80}", flush=True)
        print(f"✅ 评估完成！共 {len(self.results)}/{total_backtests} 个回测成功", flush=True)
        print(
            f"   执行统计: elapsed={_fmt_hms(total_elapsed_sec)}, "
            f"avg={avg_sec_per_task:.2f}s/task, ok={success_count}, err={error_count}",
            flush=True,
        )

        total_phases = [
            "phase_load_monitor_list",
            "phase_preload_cache",
            "phase_preload_topix",
            "phase_build_tasks",
            "phase_execute_tasks",
        ]
        print("\n⏱️ 阶段耗时明细:", flush=True)
        for key in total_phases:
            sec = self._timing_counters.get(key, 0.0)
            pct = (sec / total_elapsed_sec * 100.0) if total_elapsed_sec > 0 else 0.0
            print(f"   - {key}: {sec:.2f}s ({pct:.1f}%)", flush=True)

        per_task_keys = [
            "task_strategy_load",
            "task_monitor_list_load",
            "task_engine_init",
            "task_engine_backtest",
        ]
        if completed > 0:
            print("\n⏱️ 单任务关键子步骤累计:", flush=True)
            for key in per_task_keys:
                sec = self._timing_counters.get(key, 0.0)
                avg = sec / completed
                print(f"   - {key}: total={sec:.2f}s, avg={avg:.4f}s/task", flush=True)

        self.last_timing_summary = {
            "total_elapsed_sec": time.perf_counter() - run_started,
            "completed_tasks": completed,
            "success_count": success_count,
            "error_count": error_count,
            "phase_seconds": {k: float(self._timing_counters.get(k, 0.0)) for k in total_phases},
            "task_step_seconds": {
                k: float(self._timing_counters.get(k, 0.0)) for k in per_task_keys
            },
        }
        print(f"{'=' * 80}\n", flush=True)
        _log_step("evaluator: run_evaluation 结束")

        return self._create_results_dataframe()

    def _prepare_preloaded_cache(
        self,
        tickers: List[str],
        periods: List[Tuple[str, str, str]],
        entry_strategies: List[str],
        exit_strategies: List[str],
    ):
        from src.backtest.data_cache import BacktestDataCache
        from src.utils.strategy_loader import ENTRY_STRATEGIES, EXIT_STRATEGIES

        preloaded_cache = BacktestDataCache(data_root=self.data_root)

        min_date = min(p[1] for p in periods)
        max_date = max(p[2] for p in periods)
        include_trades, include_financials, include_metadata = (
            self._resolve_aux_preload_flags(
                entry_strategies=entry_strategies,
                exit_strategies=exit_strategies,
                entry_mapping=ENTRY_STRATEGIES,
                exit_mapping=EXIT_STRATEGIES,
            )
        )

        preloaded_cache.preload_tickers(
            tickers=tickers,
            start_date=min_date,
            end_date=max_date,
            optimize_memory=True,
            include_trades=include_trades,
            include_financials=include_financials,
            include_metadata=include_metadata,
        )
        return preloaded_cache

    @staticmethod
    def _resolve_aux_preload_flags(
        entry_strategies: List[str],
        exit_strategies: List[str],
        entry_mapping: Dict[str, str],
        exit_mapping: Dict[str, str],
    ) -> Tuple[bool, bool, bool]:
        """
        Determine whether auxiliary datasets should be preloaded based on
        selected strategy modules.
        """

        from src.utils.strategy_loader import (
            entry_strategy_uses_only_feature_data,
            exit_strategy_uses_only_feature_data,
        )

        def _entry_feature_only(name: str) -> bool:
            return entry_strategy_uses_only_feature_data(
                strategy_name=name,
                module_path=entry_mapping.get(name, ""),
            )

        def _exit_feature_only(name: str) -> bool:
            return exit_strategy_uses_only_feature_data(
                strategy_name=name,
                module_path=exit_mapping.get(name, ""),
            )

        if entry_strategies and exit_strategies:
            all_feature_only = all(_entry_feature_only(e) for e in entry_strategies) and all(
                _exit_feature_only(x) for x in exit_strategies
            )
            if all_feature_only:
                return False, False, False

        return True, True, True

    def _run_single_backtest(
        self,
        period_label: str,
        start_date: str,
        end_date: str,
        entry_strategy: str,
        exit_strategy: str,
        entry_filter_name: str,
        entry_filter_config: Dict,
        topix_return: float,
        preloaded_cache=None,
        ranking_strategy: str = "default",
    ) -> AnnualStrategyResult:
        """
        執行単個策略的回測

        Args:
            preloaded_cache: Optional BacktestDataCache instance for performance
            ranking_strategy: 信号排序策略名称
        """
        from src.backtest.portfolio_engine import PortfolioBacktestEngine
        from src.utils.strategy_loader import (
            load_strategy_pair,
            load_ranking_strategy,
        )

        # 加載策略实例
        phase_started = time.perf_counter()
        entry, exit_inst = load_strategy_pair(entry_strategy, exit_strategy)
        ranker = load_ranking_strategy(ranking_strategy)
        self._timing_counters["task_strategy_load"] += time.perf_counter() - phase_started

        # 加载监视列表
        phase_started = time.perf_counter()
        tickers = self._load_monitor_list()
        self._timing_counters["task_monitor_list_load"] += time.perf_counter() - phase_started

        # 运行回测
        capacity_mode = self._get_capacity_regime_mode()
        capacity_regime = self._get_capacity_regime()
        position_sizing_config = self._get_portfolio_sizing_config()
        if capacity_mode == "enforce" and capacity_regime is not None:
            initial_tier = capacity_regime.tiers[0]
            if position_sizing_config.mode == "fixed":
                position_sizing_config = replace(
                    position_sizing_config,
                    max_positions=initial_tier.max_positions,
                    max_position_pct=initial_tier.max_position_pct,
                )
        else:
            self._get_portfolio_limits()
        phase_started = time.perf_counter()
        initial_pending_buy_signals, initial_pending_sell_signals = (
            self._build_initial_pending_signals()
        )
        engine = PortfolioBacktestEngine(
            data_root=self.data_root,
            starting_capital=(
                self.replay_seed.baseline_total_equity_jpy
                if self.replay_seed is not None
                else self._get_starting_capital()
            ),
            initial_cash=(
                self.replay_seed.starting_cash_jpy
                if self.replay_seed is not None
                else None
            ),
            seeded_positions=self._build_seeded_positions(entry.strategy_name),
            max_positions=position_sizing_config.max_positions,
            max_position_pct=position_sizing_config.max_position_pct,
            position_sizing_config=position_sizing_config,
            capacity_regime=capacity_regime,
            capacity_regime_mode=capacity_mode,
            exit_confirmation_days=self.exit_confirmation_days,
            overlay_manager=self.overlay_manager,
            preloaded_cache=preloaded_cache,  # Pass cache to engine
            entry_filter_config=entry_filter_config,
            signal_ranker=ranker,
            buy_fill_mode=self.buy_fill_mode,
            entry_reference_mode=self.entry_reference_mode,
            fill_buffer_enabled=self.fill_buffer_enabled,
            fill_buffer_pct=self.fill_buffer_pct,
            initial_pending_buy_signals=initial_pending_buy_signals,
            initial_pending_sell_signals=initial_pending_sell_signals,
        )
        self._timing_counters["task_engine_init"] += time.perf_counter() - phase_started

        phase_started = time.perf_counter()
        result = engine.backtest_portfolio_strategy(
            tickers=tickers,
            entry_strategy=entry,
            exit_strategy=exit_inst,
            start_date=start_date,
            end_date=end_date,
            show_signal_ranking=False,
            show_signal_details=False,
            compute_benchmark=False,
        )
        self._timing_counters["task_engine_backtest"] += time.perf_counter() - phase_started

        self._record_trade_rows(
            result=result,
            period_label=period_label,
            start_date=start_date,
            end_date=end_date,
            topix_return=topix_return,
            entry_strategy=entry_strategy,
            exit_strategy=exit_strategy,
            entry_filter_name=entry_filter_name,
            ranking_strategy=ranking_strategy,
        )

        run_snapshot = self._build_evaluation_run_snapshot(
            engine=engine,
            period_label=period_label,
            start_date=start_date,
            end_date=end_date,
            entry_strategy=entry_strategy,
            exit_strategy=exit_strategy,
            entry_filter_name=entry_filter_name,
            ranking_strategy=ranking_strategy,
        )
        self.evaluation_run_snapshots.append(run_snapshot)
        self.evaluation_daily_snapshots.append(
            {
                "period": period_label,
                "start_date": start_date,
                "end_date": end_date,
                "entry_strategy": entry_strategy,
                "exit_strategy": exit_strategy,
                "entry_filter": entry_filter_name,
                "ranking_strategy": ranking_strategy,
                "daily_snapshots": list(getattr(engine, "daily_snapshots", []) or []),
            }
        )

        if self.replay_seed is not None:
            self.replay_run_snapshots.append(
                {
                    **run_snapshot,
                    "starting_cash_jpy": float(self.replay_seed.starting_cash_jpy),
                    "baseline_total_equity_jpy": float(
                        self.replay_seed.baseline_total_equity_jpy
                    ),
                    "initial_pending_orders": [
                        asdict(order) for order in self.replay_seed.pending_orders
                    ],
                    "executed_orders": list(engine.last_execution_events),
                }
            )

        # 计算alpha：如果没有TOPIX数据，则设为None
        alpha = None
        if topix_return is not None:
            alpha = result.total_return_pct - topix_return

        # 提取结果并构造数据对象
        return AnnualStrategyResult(
            period=period_label,
            start_date=start_date,
            end_date=end_date,
            entry_strategy=entry_strategy,
            exit_strategy=exit_strategy,
            entry_filter=entry_filter_name,
            return_pct=result.total_return_pct,
            topix_return_pct=topix_return,
            alpha=alpha,
            sharpe_ratio=result.sharpe_ratio,
            max_drawdown_pct=result.max_drawdown_pct,
            num_trades=result.num_trades,
            win_rate_pct=result.win_rate_pct,
            avg_gain_pct=result.avg_gain_pct,
            avg_loss_pct=result.avg_loss_pct,
            capacity_regime_mode=result.capacity_regime_mode,
            capacity_regime_version=result.capacity_regime_version,
            capacity_final_tier=result.capacity_final_tier,
            capacity_peak_tier=result.capacity_peak_tier,
            capacity_effective_equity_jpy=result.capacity_effective_equity_jpy,
            capacity_peak_equity_jpy=result.capacity_peak_equity_jpy,
            capacity_effective_max_positions=result.capacity_effective_max_positions,
            capacity_effective_max_position_pct=result.capacity_effective_max_position_pct,
            capacity_participation_cap_pct=result.capacity_participation_cap_pct,
            capacity_min_turnover_20_jpy=result.capacity_min_turnover_20_jpy,
            capacity_blocked_buys=result.capacity_blocked_buys,
            capacity_liquidity_blocked_buys=result.capacity_liquidity_blocked_buys,
            capacity_trimmed_buys=result.capacity_trimmed_buys,
            capacity_avg_participation_pct=result.capacity_avg_participation_pct,
            capacity_p95_participation_pct=result.capacity_p95_participation_pct,
            capacity_cash_drag_jpy=result.capacity_cash_drag_jpy,
            exit_confirmation_days=self.exit_confirmation_days,
            ranking_strategy=ranking_strategy,
            buy_fill_mode=self.buy_fill_mode,
            entry_reference_mode=self.entry_reference_mode,
            fill_buffer_enabled=self.fill_buffer_enabled,
            fill_buffer_pct=self.fill_buffer_pct,
        )

    def _build_evaluation_run_snapshot(
        self,
        engine,
        period_label: str,
        start_date: str,
        end_date: str,
        entry_strategy: str,
        exit_strategy: str,
        entry_filter_name: str,
        ranking_strategy: str,
    ) -> Dict[str, object]:
        return {
            "period": period_label,
            "start_date": start_date,
            "end_date": end_date,
            "snapshot_date": engine.last_processed_date,
            "entry_strategy": entry_strategy,
            "exit_strategy": exit_strategy,
            "entry_filter": entry_filter_name,
            "ranking_strategy": ranking_strategy,
            "next_pending_buy_signals": self._serialize_signal_map(
                engine.last_pending_buy_signals
            ),
            "next_pending_sell_signals": self._serialize_signal_map(
                engine.last_pending_sell_signals
            ),
            "final_cash_jpy": float(engine.last_final_cash_jpy),
            "final_open_positions": [
                asdict(position) for position in engine.last_final_open_positions
            ],
        }

    def _get_topix_return(self, start_date: str, end_date: str) -> Optional[float]:
        """
        计算TOPIX在指定时间段的收益率
        调用现有的benchmark_manager（不修改）
        如果无法获取数据，返回 None
        """
        from src.data.benchmark_manager import BenchmarkManager

        manager = BenchmarkManager(client=None, data_root=self.data_root)

        try:
            result = manager.calculate_benchmark_return(
                start_date=start_date, end_date=end_date, use_cached=True
            )
            return result  # 返回实际结果（可能是None）
        except Exception as e:
            print(f"⚠️ 无法获取TOPIX数据: {e}")
            return None

    def _load_monitor_list(self) -> List[str]:
        """加载监视列表（单次运行内缓存，从 config.json 指定的唯一真源读取）"""
        # 返回缓存（如果存在）
        if self._monitor_list_cache is not None:
            return self._monitor_list_cache

        seeded_tickers = [
            position.ticker for position in (self.replay_seed.positions if self.replay_seed else ())
        ]

        def _merge_seeded_tickers(base_tickers: List[str]) -> List[str]:
            merged: List[str] = []
            for ticker in list(base_tickers) + seeded_tickers:
                normalized = str(ticker).strip()
                if normalized and normalized not in merged:
                    merged.append(normalized)
            self._monitor_list_cache = merged
            return self._monitor_list_cache

        # 从 config.json 读取配置
        try:
            if self.monitor_list_file:
                monitor_file = Path(self.monitor_list_file)
            else:
                config_path = get_config_file_path()
                if config_path.exists():
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                        monitor_file = Path(config["data"]["monitor_list_file"])
                else:
                    # Config 不存在时回退到默认路径
                    monitor_file = Path(self.data_root) / "monitor_list.json"
        except Exception:
            monitor_file = Path(self.data_root) / "monitor_list.json"

        if not monitor_file.exists():
            raise FileNotFoundError(f"监视列表文件不存在: {monitor_file}")

        # JSON format
        if monitor_file.suffix == ".json":
            with open(monitor_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                tickers = []
                if isinstance(data, dict):
                    raw_tickers = data.get("tickers") or data.get("symbols") or data.get("stocks")
                    if isinstance(raw_tickers, list):
                        for item in raw_tickers:
                            if isinstance(item, dict) and item.get("code") is not None:
                                tickers.append(str(item["code"]).strip())
                            elif item is not None:
                                tickers.append(str(item).strip())
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("code") is not None:
                            tickers.append(str(item["code"]).strip())
                        elif item is not None:
                            tickers.append(str(item).strip())
                return _merge_seeded_tickers([ticker for ticker in tickers if ticker])

        # CSV format
        if monitor_file.suffix == ".csv":
            df = pd.read_csv(monitor_file)
            for col in ["code", "Code", "ticker", "Ticker", "symbol", "Symbol"]:
                if col in df.columns:
                    values = [str(v).strip() for v in df[col].tolist() if pd.notna(v)]
                    return _merge_seeded_tickers([v for v in values if v])
            raise ValueError(
                f"CSV股票池文件缺少代码列（支持 code/Code/ticker/Ticker/symbol/Symbol）: {monitor_file}"
            )

        # TXT format (legacy support)
        tickers = []
        with open(monitor_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    tickers.append(line)
        return _merge_seeded_tickers(tickers)

    def _create_results_dataframe(self) -> pd.DataFrame:
        """将结果转换为DataFrame"""
        if not self.results:
            return pd.DataFrame()

        if self._results_df_cache is not None:
            return self._results_df_cache

        self._results_df_cache = pd.DataFrame([asdict(r) for r in self.results])
        return self._results_df_cache

    @staticmethod
    def _safe_json_dumps(value: Any) -> str:
        try:
            return json.dumps(
                value if value is not None else {},
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            )
        except Exception:
            return "{}"

    @staticmethod
    def _serialize_trading_signal(ticker: str, signal) -> Dict[str, Any]:
        return {
            "ticker": ticker,
            "action": getattr(getattr(signal, "action", None), "value", None),
            "confidence": float(getattr(signal, "confidence", 0.0) or 0.0),
            "reasons": list(getattr(signal, "reasons", []) or []),
            "strategy_name": str(getattr(signal, "strategy_name", "") or ""),
            "metadata": json.loads(
                StrategyEvaluator._safe_json_dumps(
                    getattr(signal, "metadata", {}) or {}
                )
            ),
        }

    @staticmethod
    def _serialize_signal_map(signal_map: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            StrategyEvaluator._serialize_trading_signal(ticker, signal)
            for ticker, signal in signal_map.items()
        ]

    @staticmethod
    def _load_replay_report_runtime_config() -> Dict[str, object]:
        try:
            return load_config()
        except Exception:
            return {}

    @staticmethod
    def _extract_replay_report_buffers(raw_config: Dict[str, object]) -> Tuple[float, float]:
        production_cfg = raw_config.get("production")
        if not isinstance(production_cfg, dict):
            production_cfg = {}

        buy_price_buffer_pct = float(
            production_cfg.get("report_buy_price_buffer_pct", 0.02) or 0.02
        )
        sell_price_buffer_pct = float(
            production_cfg.get("report_sell_price_buffer_pct", 0.02) or 0.02
        )
        buy_price_buffer_pct = min(max(buy_price_buffer_pct, 0.0), 0.20)
        sell_price_buffer_pct = min(max(sell_price_buffer_pct, 0.0), 0.20)
        return buy_price_buffer_pct, sell_price_buffer_pct

    def _get_replay_report_portfolio_limits(self) -> Tuple[int, float]:
        if self._get_portfolio_sizing_config().unlimited_positions:
            return 1_000_000, 0.0

        max_positions, max_position_pct = self._get_portfolio_limits()
        if not self.results:
            return max_positions, max_position_pct

        latest_result = self.results[-1]
        if latest_result.capacity_effective_max_positions > 0:
            max_positions = int(latest_result.capacity_effective_max_positions)
        if latest_result.capacity_effective_max_position_pct > 0:
            max_position_pct = float(latest_result.capacity_effective_max_position_pct)
        return max_positions, max_position_pct

    @staticmethod
    def _load_replay_report_latest_row(
        df_features: pd.DataFrame,
        report_date: str,
    ) -> Optional[pd.Series]:
        if df_features is None or df_features.empty:
            return None

        frame = df_features.copy()
        if "Date" not in frame.columns:
            frame = frame.reset_index()
            index_name = frame.columns[0]
            frame = frame.rename(columns={index_name: "Date"})

        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        frame = frame.dropna(subset=["Date"])
        frame = frame[frame["Date"] <= pd.Timestamp(report_date)]
        if frame.empty:
            return None
        return frame.sort_values("Date").iloc[-1]

    @staticmethod
    def _load_replay_report_close_price(
        df_features: pd.DataFrame,
        report_date: str,
    ) -> Optional[float]:
        latest_row = StrategyEvaluator._load_replay_report_latest_row(
            df_features,
            report_date,
        )
        if latest_row is None or "Close" not in latest_row.index:
            return None
        return float(latest_row["Close"])

    def _load_replay_report_ticker_contexts(
        self,
        data_manager: StockDataManager,
        tickers: List[str],
        report_date: str,
    ) -> Dict[str, Dict[str, object]]:
        contexts: Dict[str, Dict[str, object]] = {}
        for ticker in tickers:
            normalized = str(ticker).strip()
            if not normalized:
                continue

            close_price = None
            atr_value = None
            atr_ratio = None
            ticker_name = normalized
            try:
                df_features = data_manager.load_stock_features(normalized)
                latest_row = self._load_replay_report_latest_row(df_features, report_date)
                if latest_row is not None and "Close" in latest_row.index:
                    close_price = float(latest_row["Close"])
                    raw_atr = latest_row.get("ATR")
                    if raw_atr is not None and not pd.isna(raw_atr):
                        atr_value = float(raw_atr)
                    raw_atr_ratio = latest_row.get("ATR_Ratio")
                    if raw_atr_ratio is not None and not pd.isna(raw_atr_ratio):
                        atr_ratio = float(raw_atr_ratio)
                    elif close_price and atr_value:
                        atr_ratio = float(atr_value) / float(close_price)
            except Exception:
                close_price = None

            try:
                metadata = data_manager.load_metadata(normalized) or {}
                if isinstance(metadata, dict):
                    ticker_name = str(metadata.get("company_name") or normalized)
            except Exception:
                ticker_name = normalized

            contexts[normalized] = {
                "ticker_name": ticker_name,
                "close_price": close_price,
                "atr": atr_value,
                "atr_ratio": atr_ratio,
            }

        return contexts

    @staticmethod
    def _derive_sell_action_label(sell_percentage: float) -> str:
        if sell_percentage >= 0.999:
            return "SELL_100%"
        if sell_percentage >= 0.74:
            return "SELL_75%"
        if sell_percentage >= 0.49:
            return "SELL_50%"
        if sell_percentage >= 0.24:
            return "SELL_25%"
        return "SELL"

    @staticmethod
    def _calculate_replay_report_sell_quantity(
        ticker: str,
        total_qty: int,
        sell_pct: float,
    ) -> int:
        if total_qty <= 0:
            return 0
        if sell_pct >= 0.999:
            return total_qty

        lot_size = LotSizeManager.get_lot_size(ticker)
        raw_qty = total_qty * max(sell_pct, 0.0)
        lots = int((raw_qty + lot_size - 1) // lot_size)
        qty = lots * lot_size
        return min(total_qty, qty)

    def _calculate_replay_report_buy_quantity(
        self,
        ticker: str,
        planning_price: float,
        available_cash: float,
        total_portfolio_value: float,
        max_position_pct: float,
        atr_jpy: float | None = None,
        atr_ratio: float | None = None,
    ) -> Tuple[int, float, int]:
        lot_size = LotSizeManager.get_lot_size(ticker)
        if planning_price <= 0 or lot_size <= 0:
            return 0, 0.0, lot_size

        position_sizing = self._get_portfolio_sizing_config()
        if position_sizing.mode == "atr":
            sizing_result = calculate_atr_position_size(
                AtrSizingInput(
                    ticker=ticker,
                    planning_price=planning_price,
                    portfolio_value_jpy=total_portfolio_value,
                    available_cash_jpy=available_cash,
                    atr_jpy=float(atr_jpy or 0.0),
                    lot_size=lot_size,
                    config=position_sizing.atr,
                    atr_ratio=atr_ratio,
                )
            )
            return sizing_result.quantity, sizing_result.required_capital_jpy, lot_size

        target_position_value = total_portfolio_value * max_position_pct
        max_position_value = min(target_position_value, available_cash)
        lot_value = planning_price * lot_size
        lots = int(max_position_value // lot_value)
        quantity = lots * lot_size
        required_capital = quantity * planning_price
        return quantity, required_capital, lot_size

    def _rank_replay_report_buy_signals(
        self,
        buy_signals: List[Dict[str, Any]],
        report_date: str,
        ranking_strategy: str,
        data_manager: StockDataManager,
    ) -> Dict[str, Dict[str, float]]:
        if not buy_signals:
            return {}

        from src.utils.strategy_loader import load_ranking_strategy

        ranker = load_ranking_strategy(ranking_strategy or "default")
        trading_signals: Dict[str, TradingSignal] = {}
        for raw_signal in buy_signals:
            ticker = str(raw_signal.get("ticker") or "").strip()
            if not ticker:
                continue
            metadata = json.loads(
                self._safe_json_dumps(raw_signal.get("metadata") or {})
            )
            trading_signals[ticker] = TradingSignal(
                action=SignalAction.BUY,
                confidence=float(raw_signal.get("confidence") or 0.0),
                reasons=list(raw_signal.get("reasons") or []),
                metadata=metadata,
                strategy_name=str(raw_signal.get("strategy_name") or ""),
            )

        market_data_dict = {}
        if ranker.requires_market_data():
            for ticker in trading_signals:
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=data_manager,
                    ticker=ticker,
                    current_date=pd.Timestamp(report_date),
                )
                if market_data is not None:
                    market_data_dict[ticker] = market_data

        ranked = ranker.rank_buy_signals(trading_signals, market_data_dict)
        return {
            ticker: {
                "rank": float(index + 1),
                "rank_score": float(priority),
            }
            for index, (ticker, _signal, priority) in enumerate(ranked)
        }

    def _build_replay_last_day_production_style_signals(
        self,
        snapshot: Dict[str, Any],
    ) -> List[ProductionSignal]:
        if self.replay_seed is None:
            return []

        report_date = str(snapshot.get("end_date") or self.replay_seed.report_date)
        raw_config = self._load_replay_report_runtime_config()
        buy_price_buffer_pct, sell_price_buffer_pct = self._extract_replay_report_buffers(
            raw_config
        )
        final_cash_jpy = float(snapshot.get("final_cash_jpy") or 0.0)
        final_positions = list(snapshot.get("final_open_positions") or [])
        raw_buy_signals = list(snapshot.get("next_pending_buy_signals") or [])
        raw_sell_signals = list(snapshot.get("next_pending_sell_signals") or [])

        tickers: List[str] = []
        for position in final_positions:
            ticker = str(position.get("ticker") or "").strip()
            if ticker and ticker not in tickers:
                tickers.append(ticker)
        for raw_signal in raw_buy_signals + raw_sell_signals:
            ticker = str(raw_signal.get("ticker") or "").strip()
            if ticker and ticker not in tickers:
                tickers.append(ticker)

        data_manager = StockDataManager(api_key=None, data_root=self.data_root)
        ticker_contexts = self._load_replay_report_ticker_contexts(
            data_manager=data_manager,
            tickers=tickers,
            report_date=report_date,
        )
        rank_map = self._rank_replay_report_buy_signals(
            buy_signals=raw_buy_signals,
            report_date=report_date,
            ranking_strategy=str(snapshot.get("ranking_strategy") or "default"),
            data_manager=data_manager,
        )

        positions_by_ticker = {
            str(position.get("ticker") or "").strip(): position
            for position in final_positions
            if str(position.get("ticker") or "").strip()
        }
        total_position_value = sum(
            float(position.get("market_value") or 0.0) for position in final_positions
        )
        total_portfolio_value = final_cash_jpy + total_position_value

        sell_signals: List[ProductionSignal] = []
        projected_sell_proceeds = 0.0
        projected_position_count = len(positions_by_ticker)
        report_ts = pd.Timestamp(report_date)

        for raw_signal in raw_sell_signals:
            ticker = str(raw_signal.get("ticker") or "").strip()
            if not ticker:
                continue

            position = positions_by_ticker.get(ticker)
            if position is None:
                continue

            metadata = raw_signal.get("metadata") or {}
            context = ticker_contexts.get(ticker, {})
            close_price = context.get("close_price")
            current_price = float(
                close_price
                if close_price is not None
                else (position.get("current_price") or 0.0)
            )
            position_qty = int(position.get("quantity") or 0)
            if position_qty <= 0 or current_price <= 0:
                continue

            sell_percentage = float(metadata.get("sell_percentage") or 1.0)
            planned_sell_qty = metadata.get("planned_sell_quantity")
            if planned_sell_qty is None:
                planned_sell_qty = self._calculate_replay_report_sell_quantity(
                    ticker=ticker,
                    total_qty=position_qty,
                    sell_pct=sell_percentage,
                )
            planned_sell_qty = max(0, int(planned_sell_qty or 0))
            planned_sell_price = current_price * (1.0 - sell_price_buffer_pct)
            planned_sell_value = planned_sell_qty * planned_sell_price
            entry_price = float(position.get("entry_price") or 0.0)
            entry_date = str(position.get("entry_date") or "")
            holding_days = (
                (report_ts - pd.Timestamp(entry_date)).days if entry_date else 0
            )
            unrealized_pl_pct = (
                ((current_price - entry_price) / entry_price) * 100.0
                if entry_price > 0
                else None
            )

            signal = ProductionSignal(
                group_id=self.replay_seed.group_id,
                ticker=ticker,
                ticker_name=str(context.get("ticker_name") or ticker),
                signal_type="SELL",
                action=self._derive_sell_action_label(sell_percentage),
                confidence=float(raw_signal.get("confidence") or 0.0),
                score=float(metadata.get("score") or 0.0),
                reason="; ".join(raw_signal.get("reasons") or []) or "SELL",
                current_price=current_price,
                close_price=current_price,
                planned_price=float(planned_sell_price),
                planning_price_factor=float(1.0 + buy_price_buffer_pct),
                sell_price_factor=float(1.0 - sell_price_buffer_pct),
                position_qty=position_qty,
                entry_price=entry_price,
                entry_date=entry_date,
                holding_days=holding_days,
                unrealized_pl_pct=unrealized_pl_pct,
                planned_sell_qty=planned_sell_qty,
                planned_sell_value=float(planned_sell_value),
                is_executable=planned_sell_qty > 0,
                is_executable_sell=planned_sell_qty > 0,
                strategy_name=str(raw_signal.get("strategy_name") or ""),
                exit_trigger=(
                    str(metadata.get("trigger"))
                    if metadata.get("trigger") is not None
                    else None
                ),
            )
            sell_signals.append(signal)

            if planned_sell_qty > 0:
                projected_sell_proceeds += planned_sell_value
                if planned_sell_qty >= position_qty:
                    projected_position_count = max(0, projected_position_count - 1)

        planning_cash = final_cash_jpy + projected_sell_proceeds
        max_positions, max_position_pct = self._get_replay_report_portfolio_limits()

        def _buy_sort_key(raw_signal: Dict[str, Any]) -> Tuple[float, float, str]:
            ticker = str(raw_signal.get("ticker") or "").strip()
            ranking = rank_map.get(ticker, {})
            score = float((raw_signal.get("metadata") or {}).get("score") or 0.0)
            return (
                float(ranking.get("rank", 999999.0)),
                -score,
                ticker,
            )

        buy_signals: List[ProductionSignal] = []
        new_positions_opened = 0
        for raw_signal in sorted(raw_buy_signals, key=_buy_sort_key):
            ticker = str(raw_signal.get("ticker") or "").strip()
            if not ticker:
                continue

            metadata = raw_signal.get("metadata") or {}
            context = ticker_contexts.get(ticker, {})
            close_price_value = context.get("close_price")
            close_price = (
                float(close_price_value)
                if close_price_value is not None
                else None
            )
            planning_price = (
                float(close_price) * (1.0 + buy_price_buffer_pct)
                if close_price is not None
                else None
            )
            rank_info = rank_map.get(ticker, {})
            base_reason = "; ".join(raw_signal.get("reasons") or []) or "BUY"

            suggested_qty = 0
            required_capital = 0.0
            lot_size = LotSizeManager.get_lot_size(ticker)
            reason = base_reason

            if ticker in positions_by_ticker:
                reason = f"{base_reason}; Skipped: already in portfolio"
            elif close_price is None or planning_price is None or planning_price <= 0:
                reason = f"{base_reason}; Skipped: missing close price"
            elif projected_position_count + new_positions_opened >= max_positions:
                reason = (
                    f"{base_reason}; Skipped: max positions ({max_positions}) reached"
                )
            else:
                suggested_qty, required_capital, lot_size = (
                    self._calculate_replay_report_buy_quantity(
                        ticker=ticker,
                        planning_price=float(planning_price),
                        available_cash=planning_cash,
                        total_portfolio_value=total_portfolio_value,
                        max_position_pct=max_position_pct,
                        atr_jpy=(
                            float(context["atr"])
                            if context.get("atr") is not None
                            else None
                        ),
                        atr_ratio=(
                            float(context["atr_ratio"])
                            if context.get("atr_ratio") is not None
                            else None
                        ),
                    )
                )
                if suggested_qty > 0:
                    planning_cash = max(0.0, planning_cash - required_capital)
                    new_positions_opened += 1
                else:
                    reason = (
                        f"{base_reason}; SuggestedQty=0: projected cash insufficient "
                        f"for lot size {lot_size}"
                    )

            signal = ProductionSignal(
                group_id=self.replay_seed.group_id,
                ticker=ticker,
                ticker_name=str(context.get("ticker_name") or ticker),
                signal_type="BUY",
                action="BUY",
                confidence=float(raw_signal.get("confidence") or 0.0),
                score=float(metadata.get("score") or 0.0),
                reason=reason,
                current_price=float(planning_price or 0.0),
                close_price=float(close_price or 0.0) if close_price is not None else None,
                planned_price=float(planning_price or 0.0) if planning_price is not None else None,
                planning_price_factor=float(1.0 + buy_price_buffer_pct),
                sell_price_factor=float(1.0 - sell_price_buffer_pct),
                suggested_qty=int(suggested_qty),
                required_capital=float(required_capital),
                rank=(
                    int(rank_info["rank"])
                    if rank_info.get("rank") is not None
                    else None
                ),
                rank_score=(
                    float(rank_info["rank_score"])
                    if rank_info.get("rank_score") is not None
                    else None
                ),
                is_executable=suggested_qty > 0,
                is_executable_buy=suggested_qty > 0,
                strategy_name=str(raw_signal.get("strategy_name") or ""),
            )
            buy_signals.append(signal)

        return sell_signals + buy_signals

    def _build_replay_last_day_production_style_state(
        self,
        snapshot: Dict[str, Any],
    ) -> ProductionState:
        if self.replay_seed is None:
            raise ValueError("Replay seed is required to build replay production-style state")

        baseline_total_equity_jpy = float(
            snapshot.get("baseline_total_equity_jpy")
            or self.replay_seed.baseline_total_equity_jpy
        )
        group = StrategyGroupState(
            id=self.replay_seed.group_id,
            name=self.replay_seed.group_name,
            initial_capital=baseline_total_equity_jpy,
            cash=float(snapshot.get("final_cash_jpy") or 0.0),
            positions=[],
        )
        seeded_scores = {
            position.ticker: float(position.entry_score)
            for position in self.replay_seed.positions
        }
        for position in snapshot.get("final_open_positions") or []:
            ticker = str(position.get("ticker") or "").strip()
            if not ticker:
                continue
            group.positions.append(
                ProductionPosition(
                    ticker=ticker,
                    quantity=int(position.get("quantity") or 0),
                    entry_price=float(position.get("entry_price") or 0.0),
                    entry_date=str(position.get("entry_date") or ""),
                    entry_score=float(seeded_scores.get(ticker, 0.0)),
                    peak_price=float(position.get("peak_price") or 0.0),
                    signal_entry_price=float(
                        position.get("signal_entry_price") or position.get("entry_price") or 0.0
                    ),
                )
            )

        virtual_state_file = self.output_dir / "__replay_virtual_state__.json"
        state = ProductionState(state_file=str(virtual_state_file))
        state.strategy_groups = {group.id: group}
        return state

    def _build_replay_last_day_production_style_artifact(
        self,
        prefix: str,
        timestamp: str,
    ) -> Optional[Dict[str, Any]]:
        if self.replay_seed is None or not self.replay_run_snapshots:
            return None

        snapshot = self.replay_run_snapshots[-1]
        report_date = str(snapshot.get("end_date") or self.replay_seed.report_date)
        signals = self._build_replay_last_day_production_style_signals(snapshot)
        state = self._build_replay_last_day_production_style_state(snapshot)
        report_file = (
            self.output_dir
            / f"{prefix}_replay_last_day_production_style_report_{timestamp}.md"
        )
        builder = ReportBuilder(
            state,
            StockDataManager(api_key=None, data_root=self.data_root),
            initial_capital_override=float(
                snapshot.get("baseline_total_equity_jpy")
                or self.replay_seed.baseline_total_equity_jpy
            ),
            strategy_groups=[
                {
                    "id": self.replay_seed.group_id,
                    "name": self.replay_seed.group_name,
                    "entry_strategy": str(snapshot.get("entry_strategy") or "N/A"),
                    "exit_strategy": str(snapshot.get("exit_strategy") or "N/A"),
                }
            ],
            default_entry_strategy=str(snapshot.get("entry_strategy") or "N/A"),
            default_exit_strategy=str(snapshot.get("exit_strategy") or "N/A"),
        )
        report_md = builder.generate_daily_report(
            signals=signals,
            report_date=report_date,
        )
        builder.save_report(report_md, str(report_file))
        return {
            "report_date": report_date,
            "report_file": str(report_file),
            "signal_count": len(signals),
            "signals": [asdict(signal) for signal in signals],
        }

    def _record_trade_rows(
        self,
        result,
        period_label: str,
        start_date: str,
        end_date: str,
        topix_return: Optional[float],
        entry_strategy: str,
        exit_strategy: str,
        entry_filter_name: str,
        ranking_strategy: str,
    ) -> None:
        market_regime = MarketRegime.classify(topix_return)
        self._trade_results_df_cache = None

        for trade in getattr(result, "trades", []) or []:
            entry_metadata = getattr(trade, "entry_metadata", {}) or {}
            exit_metadata = getattr(trade, "exit_metadata", {}) or {}

            raw_sell_pct = getattr(
                trade,
                "exit_sell_percentage",
                exit_metadata.get("sell_percentage", 1.0),
            )
            try:
                exit_sell_percentage = float(raw_sell_pct)
            except (TypeError, ValueError):
                exit_sell_percentage = 1.0

            exit_is_full_exit = getattr(trade, "exit_is_full_exit", None)
            if exit_is_full_exit is None:
                after_qty = getattr(trade, "position_quantity_after_exit", None)
                if after_qty is not None:
                    exit_is_full_exit = int(after_qty) <= 0
                else:
                    exit_is_full_exit = exit_sell_percentage >= 0.999999
            exit_is_full_exit = bool(exit_is_full_exit)

            self.trade_results.append(
                {
                    "period": period_label,
                    "start_date": start_date,
                    "end_date": end_date,
                    "market_regime": market_regime,
                    "topix_return_pct": topix_return,
                    "entry_strategy": entry_strategy,
                    "exit_strategy": exit_strategy,
                    "entry_filter": entry_filter_name,
                    "ranking_strategy": ranking_strategy,
                    "exit_confirmation_days": self.exit_confirmation_days,
                    "buy_fill_mode": self.buy_fill_mode,
                    "entry_reference_mode": self.entry_reference_mode,
                    "fill_buffer_enabled": self.fill_buffer_enabled,
                    "fill_buffer_pct": self.fill_buffer_pct,
                    "ticker": getattr(trade, "ticker", None),
                    "entry_date": getattr(trade, "entry_date", None),
                    "entry_price": getattr(trade, "entry_price", None),
                    "entry_score": getattr(trade, "entry_score", None),
                    "entry_confidence": getattr(trade, "entry_confidence", None),
                    "entry_metadata_json": self._safe_json_dumps(entry_metadata),
                    "exit_date": getattr(trade, "exit_date", None),
                    "exit_price": getattr(trade, "exit_price", None),
                    "exit_reason": getattr(trade, "exit_reason", None),
                    "exit_urgency": getattr(trade, "exit_urgency", None),
                    "holding_days": getattr(trade, "holding_days", None),
                    "shares": getattr(trade, "shares", None),
                    "return_pct": getattr(trade, "return_pct", None),
                    "return_jpy": getattr(trade, "return_jpy", None),
                    "peak_price": getattr(trade, "peak_price", None),
                    "position_quantity_before_exit": getattr(
                        trade,
                        "position_quantity_before_exit",
                        None,
                    ),
                    "position_quantity_after_exit": getattr(
                        trade,
                        "position_quantity_after_exit",
                        None,
                    ),
                    "exit_sell_percentage": exit_sell_percentage,
                    "exit_is_full_exit": exit_is_full_exit,
                    "exit_is_partial_exit": not exit_is_full_exit,
                    "capacity_regime_version": entry_metadata.get(
                        "capacity_regime_version"
                    ),
                    "capacity_tier_name": entry_metadata.get("capacity_tier_name"),
                    "capacity_effective_equity_jpy": entry_metadata.get(
                        "capacity_effective_equity_jpy"
                    ),
                    "capacity_order_cap_jpy": entry_metadata.get(
                        "capacity_order_cap_jpy"
                    ),
                    "capacity_turnover_jpy": entry_metadata.get(
                        "capacity_turnover_jpy"
                    ),
                    "capacity_participation_pct": entry_metadata.get(
                        "capacity_participation_pct"
                    ),
                    "exit_metadata_json": self._safe_json_dumps(exit_metadata),
                }
            )

    @staticmethod
    def _resolve_config_source_label(config_path: Path) -> str:
        if os.getenv(CONFIG_ENV_VAR):
            return "env"
        if config_path == GDRIVE_DEFAULT_CONFIG_FILE:
            return "gdrive"
        return "local"

    def _write_capacity_snapshot(self, handle, df: pd.DataFrame) -> None:
        config_path = get_config_file_path()
        config_source = self._resolve_config_source_label(config_path)
        capacity_mode = (
            str(df["capacity_regime_mode"].iloc[0])
            if "capacity_regime_mode" in df.columns and not df.empty
            else "off"
        )
        regime_version = (
            str(df["capacity_regime_version"].iloc[0])
            if "capacity_regime_version" in df.columns and not df.empty
            else ""
        )
        final_tiers = []
        if "capacity_final_tier" in df.columns:
            final_tiers = sorted(
                {
                    str(value)
                    for value in df["capacity_final_tier"].dropna()
                    if str(value)
                }
            )
        peak_tiers = []
        if "capacity_peak_tier" in df.columns:
            peak_tiers = sorted(
                {
                    str(value)
                    for value in df["capacity_peak_tier"].dropna()
                    if str(value)
                }
            )

        handle.write("## 1. Capacity Snapshot\n\n")
        handle.write(f"- Config Path: {config_path}\n")
        handle.write(f"- Config Source: {config_source}\n")
        handle.write(f"- Capacity Mode: {capacity_mode}\n")
        handle.write(f"- Capacity Version: {regime_version or 'N/A'}\n")
        handle.write(f"- Run Count: {len(df)}\n")
        if "capacity_effective_equity_jpy" in df.columns:
            handle.write(
                f"- Final Effective Equity Range: ¥{df['capacity_effective_equity_jpy'].min():,.0f} ~ ¥{df['capacity_effective_equity_jpy'].max():,.0f}\n"
            )
        if "capacity_peak_equity_jpy" in df.columns:
            handle.write(
                f"- Peak Effective Equity: ¥{df['capacity_peak_equity_jpy'].max():,.0f}\n"
            )
        if "capacity_effective_max_positions" in df.columns:
            handle.write(
                f"- Effective Max Positions: {int(df['capacity_effective_max_positions'].max())}\n"
            )
        if "capacity_effective_max_position_pct" in df.columns:
            handle.write(
                f"- Effective Max Position Pct: {df['capacity_effective_max_position_pct'].max() * 100:.2f}%\n"
            )
        if "capacity_participation_cap_pct" in df.columns:
            handle.write(
                f"- Participation Cap: {df['capacity_participation_cap_pct'].max() * 100:.2f}%\n"
            )
        if "capacity_min_turnover_20_jpy" in df.columns:
            handle.write(
                f"- Liquidity Floor: ¥{df['capacity_min_turnover_20_jpy'].max():,.0f}\n"
            )
        if "capacity_blocked_buys" in df.columns:
            handle.write(
                f"- Capacity Blocked Buys: {int(df['capacity_blocked_buys'].sum())}\n"
            )
        if "capacity_liquidity_blocked_buys" in df.columns:
            handle.write(
                f"- Liquidity Blocked Buys: {int(df['capacity_liquidity_blocked_buys'].sum())}\n"
            )
        if "capacity_trimmed_buys" in df.columns:
            handle.write(
                f"- Trimmed Buys: {int(df['capacity_trimmed_buys'].sum())}\n"
            )
        if "capacity_avg_participation_pct" in df.columns:
            handle.write(
                f"- Avg Participation: {df['capacity_avg_participation_pct'].mean():.2f}%\n"
            )
        if "capacity_p95_participation_pct" in df.columns:
            handle.write(
                f"- P95 Participation: {df['capacity_p95_participation_pct'].max():.2f}%\n"
            )
        if "capacity_cash_drag_jpy" in df.columns:
            handle.write(
                f"- Capacity Cash Drag: ¥{df['capacity_cash_drag_jpy'].sum():,.0f}\n"
            )
        handle.write(
            f"- Final Tiers Seen: {', '.join(final_tiers) if final_tiers else 'N/A'}\n"
        )
        handle.write(
            f"- Peak Tiers Seen: {', '.join(peak_tiers) if peak_tiers else 'N/A'}\n\n"
        )

    def _create_trade_results_dataframe(self) -> pd.DataFrame:
        if not self.trade_results:
            return pd.DataFrame(columns=TRADE_EXPORT_COLUMNS)

        if self._trade_results_df_cache is not None:
            return self._trade_results_df_cache

        trade_df = pd.DataFrame(self.trade_results)
        for col in TRADE_EXPORT_COLUMNS:
            if col not in trade_df.columns:
                trade_df[col] = pd.NA
        self._trade_results_df_cache = trade_df[TRADE_EXPORT_COLUMNS]
        return self._trade_results_df_cache

    def _create_last_day_signal_dataframe(self) -> pd.DataFrame:
        rows: List[Dict[str, object]] = []
        for snapshot in self.evaluation_run_snapshots:
            for signal_type, key in (
                ("BUY", "next_pending_buy_signals"),
                ("SELL", "next_pending_sell_signals"),
            ):
                signal_rows = snapshot.get(key, []) or []
                if not isinstance(signal_rows, list):
                    continue
                for signal_payload in signal_rows:
                    payload = dict(signal_payload or {})
                    rows.append(
                        {
                            "period": snapshot.get("period"),
                            "requested_end_date": snapshot.get("end_date"),
                            "snapshot_date": snapshot.get("snapshot_date"),
                            "entry_strategy": snapshot.get("entry_strategy"),
                            "exit_strategy": snapshot.get("exit_strategy"),
                            "entry_filter": snapshot.get("entry_filter"),
                            "ranking_strategy": snapshot.get("ranking_strategy"),
                            "signal_type": signal_type,
                            "ticker": payload.get("ticker"),
                            "action": payload.get("action"),
                            "confidence": payload.get("confidence"),
                            "strategy_name": payload.get("strategy_name"),
                            "reasons_json": self._safe_json_dumps(
                                payload.get("reasons", [])
                            ),
                            "metadata_json": self._safe_json_dumps(
                                payload.get("metadata", {})
                            ),
                        }
                    )

        signal_df = pd.DataFrame(rows)
        for col in LAST_DAY_SIGNAL_COLUMNS:
            if col not in signal_df.columns:
                signal_df[col] = pd.NA
        return signal_df[LAST_DAY_SIGNAL_COLUMNS]

    def _create_last_day_position_dataframe(self) -> pd.DataFrame:
        rows: List[Dict[str, object]] = []
        for snapshot in self.evaluation_run_snapshots:
            positions = snapshot.get("final_open_positions", []) or []
            if not isinstance(positions, list):
                continue
            for position in positions:
                payload = dict(position or {})
                rows.append(
                    {
                        "period": snapshot.get("period"),
                        "requested_end_date": snapshot.get("end_date"),
                        "snapshot_date": snapshot.get("snapshot_date"),
                        "entry_strategy": snapshot.get("entry_strategy"),
                        "exit_strategy": snapshot.get("exit_strategy"),
                        "entry_filter": snapshot.get("entry_filter"),
                        "ranking_strategy": snapshot.get("ranking_strategy"),
                        "ticker": payload.get("ticker"),
                        "quantity": payload.get("quantity"),
                        "entry_date": payload.get("entry_date"),
                        "entry_price": payload.get("entry_price"),
                        "signal_entry_price": payload.get("signal_entry_price"),
                        "peak_price": payload.get("peak_price"),
                        "current_price": payload.get("current_price"),
                        "market_value": payload.get("market_value"),
                    }
                )

        position_df = pd.DataFrame(rows)
        for col in LAST_DAY_POSITION_COLUMNS:
            if col not in position_df.columns:
                position_df[col] = pd.NA
        return position_df[LAST_DAY_POSITION_COLUMNS]

    def _create_daily_signal_dataframe(self) -> pd.DataFrame:
        rows: List[Dict[str, object]] = []
        for run_snapshot in self.evaluation_daily_snapshots:
            for daily_snapshot in run_snapshot.get("daily_snapshots", []) or []:
                snapshot_date = daily_snapshot.get("date")
                for signal_type, key in (
                    ("BUY", "pending_buy_signals"),
                    ("SELL", "pending_sell_signals"),
                ):
                    for signal_payload in daily_snapshot.get(key, []) or []:
                        payload = dict(signal_payload or {})
                        rows.append(
                            {
                                "period": run_snapshot.get("period"),
                                "requested_end_date": run_snapshot.get("end_date"),
                                "snapshot_date": snapshot_date,
                                "entry_strategy": run_snapshot.get("entry_strategy"),
                                "exit_strategy": run_snapshot.get("exit_strategy"),
                                "entry_filter": run_snapshot.get("entry_filter"),
                                "ranking_strategy": run_snapshot.get("ranking_strategy"),
                                "signal_type": signal_type,
                                "ticker": payload.get("ticker"),
                                "action": payload.get("action"),
                                "confidence": payload.get("confidence"),
                                "strategy_name": payload.get("strategy_name"),
                                "reasons_json": self._safe_json_dumps(
                                    payload.get("reasons", [])
                                ),
                                "metadata_json": self._safe_json_dumps(
                                    payload.get("metadata", {})
                                ),
                            }
                        )

        signal_df = pd.DataFrame(rows)
        for col in DAILY_SIGNAL_COLUMNS:
            if col not in signal_df.columns:
                signal_df[col] = pd.NA
        return signal_df[DAILY_SIGNAL_COLUMNS]

    def _create_daily_position_dataframe(self) -> pd.DataFrame:
        rows: List[Dict[str, object]] = []
        for run_snapshot in self.evaluation_daily_snapshots:
            for daily_snapshot in run_snapshot.get("daily_snapshots", []) or []:
                snapshot_date = daily_snapshot.get("date")
                cash_jpy = daily_snapshot.get("cash_jpy")
                total_equity_jpy = daily_snapshot.get("total_equity_jpy")
                for position in daily_snapshot.get("open_positions", []) or []:
                    payload = dict(position or {})
                    rows.append(
                        {
                            "period": run_snapshot.get("period"),
                            "requested_end_date": run_snapshot.get("end_date"),
                            "snapshot_date": snapshot_date,
                            "entry_strategy": run_snapshot.get("entry_strategy"),
                            "exit_strategy": run_snapshot.get("exit_strategy"),
                            "entry_filter": run_snapshot.get("entry_filter"),
                            "ranking_strategy": run_snapshot.get("ranking_strategy"),
                            "ticker": payload.get("ticker"),
                            "quantity": payload.get("quantity"),
                            "entry_date": payload.get("entry_date"),
                            "entry_price": payload.get("entry_price"),
                            "signal_entry_price": payload.get("signal_entry_price"),
                            "peak_price": payload.get("peak_price"),
                            "current_price": payload.get("current_price"),
                            "market_value": payload.get("market_value"),
                            "cash_jpy": cash_jpy,
                            "total_equity_jpy": total_equity_jpy,
                        }
                    )

        position_df = pd.DataFrame(rows)
        for col in DAILY_POSITION_COLUMNS:
            if col not in position_df.columns:
                position_df[col] = pd.NA
        return position_df[DAILY_POSITION_COLUMNS]

    @staticmethod
    def _coerce_full_exit_flags(values: pd.Series) -> pd.Series:
        def _normalize(value: Any) -> bool:
            if pd.isna(value):
                return True
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value).strip().lower() in {"true", "1", "yes", "y"}

        return values.map(_normalize)

    @staticmethod
    def _prepare_exit_summary_source_df(
        trades_df: pd.DataFrame,
        full_exit_only: bool = False,
    ) -> pd.DataFrame:
        if trades_df is None or trades_df.empty:
            return pd.DataFrame()

        summary_df = trades_df.copy()
        if "exit_is_full_exit" not in summary_df.columns:
            summary_df["exit_is_full_exit"] = True
        summary_df["exit_is_full_exit"] = StrategyEvaluator._coerce_full_exit_flags(
            summary_df["exit_is_full_exit"]
        )
        if "exit_sell_percentage" not in summary_df.columns:
            summary_df["exit_sell_percentage"] = 1.0
        summary_df["exit_sell_percentage"] = pd.to_numeric(
            summary_df["exit_sell_percentage"],
            errors="coerce",
        ).fillna(1.0)

        if full_exit_only:
            summary_df = summary_df[
                summary_df["exit_sell_percentage"] >= 0.999999
            ].copy()

        if summary_df.empty:
            return pd.DataFrame()

        summary_df["return_pct"] = pd.to_numeric(summary_df["return_pct"], errors="coerce")
        summary_df["holding_days"] = pd.to_numeric(summary_df["holding_days"], errors="coerce")
        summary_df["return_jpy"] = pd.to_numeric(summary_df["return_jpy"], errors="coerce")
        summary_df["exit_confirmation_days"] = pd.to_numeric(
            summary_df["exit_confirmation_days"],
            errors="coerce",
        ).fillna(1).astype(int)

        if "exit_urgency" not in summary_df.columns:
            summary_df["exit_urgency"] = "UNKNOWN"
        summary_df["exit_urgency"] = summary_df["exit_urgency"].fillna("UNKNOWN")

        if "exit_reason" not in summary_df.columns:
            summary_df["exit_reason"] = ""
        summary_df["exit_reason"] = summary_df["exit_reason"].fillna("")

        summary_df["trade_scope"] = (
            "full_sell_signal_only" if full_exit_only else "all_trades"
        )
        return summary_df

    @staticmethod
    def _aggregate_exit_metrics(
        summary_df: pd.DataFrame,
        group_cols: List[str],
        total_cols: List[str],
        total_col_name: str,
    ) -> pd.DataFrame:
        grouped = (
            summary_df.groupby(group_cols, dropna=False)
            .agg(
                trade_count=("ticker", "size"),
                avg_return_pct=("return_pct", "mean"),
                avg_holding_days=("holding_days", "mean"),
                win_rate_pct=(
                    "return_pct",
                    lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean() * 100.0),
                ),
                total_return_jpy=("return_jpy", "sum"),
                gross_profit_jpy=(
                    "return_jpy",
                    lambda s: float(pd.to_numeric(s, errors="coerce").clip(lower=0).sum()),
                ),
                gross_loss_jpy=(
                    "return_jpy",
                    lambda s: float(pd.to_numeric(s, errors="coerce").clip(upper=0).sum()),
                ),
            )
            .reset_index()
        )

        totals = (
            summary_df.groupby(total_cols, dropna=False)
            .size()
            .rename(total_col_name)
            .reset_index()
        )
        return grouped.merge(totals, on=total_cols, how="left")

    @staticmethod
    def build_exit_reason_detail_df(
        trades_df: pd.DataFrame,
        full_exit_only: bool = False,
    ) -> pd.DataFrame:
        summary_df = StrategyEvaluator._prepare_exit_summary_source_df(
            trades_df,
            full_exit_only=full_exit_only,
        )
        if summary_df.empty:
            return pd.DataFrame(columns=EXIT_REASON_DETAIL_COLUMNS)

        combo_cols = [
            "period",
            "market_regime",
            "entry_strategy",
            "exit_strategy",
            "entry_filter",
            "exit_confirmation_days",
        ]
        group_cols = combo_cols + ["exit_urgency", "exit_reason"]

        grouped = StrategyEvaluator._aggregate_exit_metrics(
            summary_df,
            group_cols,
            combo_cols,
            "period_trade_total",
        )
        grouped["trade_ratio"] = grouped["trade_count"] / grouped["period_trade_total"]
        grouped["trade_scope"] = summary_df["trade_scope"].iloc[0]

        overall_base_cols = [
            "entry_strategy",
            "exit_strategy",
            "entry_filter",
            "exit_confirmation_days",
        ]
        overall_group_cols = overall_base_cols + ["exit_urgency", "exit_reason"]
        overall = StrategyEvaluator._aggregate_exit_metrics(
            summary_df,
            overall_group_cols,
            overall_base_cols,
            "period_trade_total",
        )
        overall["trade_ratio"] = overall["trade_count"] / overall["period_trade_total"]
        overall["trade_scope"] = summary_df["trade_scope"].iloc[0]
        overall["period"] = "__ALL__"
        overall["market_regime"] = "ALL"

        summary = pd.concat([overall, grouped], ignore_index=True, sort=False)
        for col in EXIT_REASON_DETAIL_COLUMNS:
            if col not in summary.columns:
                summary[col] = pd.NA

        summary = summary[EXIT_REASON_DETAIL_COLUMNS]
        summary = summary.sort_values(
            ["period", "entry_strategy", "exit_strategy", "trade_count", "exit_urgency"],
            ascending=[True, True, True, False, True],
        ).reset_index(drop=True)
        return summary

    @staticmethod
    def build_exit_urgency_summary_df(
        trades_df: pd.DataFrame,
        full_exit_only: bool = False,
    ) -> pd.DataFrame:
        summary_df = StrategyEvaluator._prepare_exit_summary_source_df(
            trades_df,
            full_exit_only=full_exit_only,
        )
        if summary_df.empty:
            return pd.DataFrame(columns=EXIT_URGENCY_SUMMARY_COLUMNS)

        combo_cols = [
            "period",
            "market_regime",
            "entry_strategy",
            "exit_strategy",
            "entry_filter",
            "exit_confirmation_days",
        ]
        group_cols = combo_cols + ["exit_urgency"]
        grouped = StrategyEvaluator._aggregate_exit_metrics(
            summary_df,
            group_cols,
            combo_cols,
            "period_trade_total",
        )
        grouped["trade_ratio"] = grouped["trade_count"] / grouped["period_trade_total"]
        grouped["trade_scope"] = summary_df["trade_scope"].iloc[0]

        overall_base_cols = [
            "entry_strategy",
            "exit_strategy",
            "entry_filter",
            "exit_confirmation_days",
        ]
        overall_group_cols = overall_base_cols + ["exit_urgency"]
        overall = StrategyEvaluator._aggregate_exit_metrics(
            summary_df,
            overall_group_cols,
            overall_base_cols,
            "period_trade_total",
        )
        overall["trade_ratio"] = overall["trade_count"] / overall["period_trade_total"]
        overall["trade_scope"] = summary_df["trade_scope"].iloc[0]
        overall["period"] = "__ALL__"
        overall["market_regime"] = "ALL"

        summary = pd.concat([overall, grouped], ignore_index=True, sort=False)
        for col in EXIT_URGENCY_SUMMARY_COLUMNS:
            if col not in summary.columns:
                summary[col] = pd.NA

        summary = summary[EXIT_URGENCY_SUMMARY_COLUMNS]
        summary = summary.sort_values(
            ["period", "entry_strategy", "exit_strategy", "trade_count", "exit_urgency"],
            ascending=[True, True, True, False, True],
        ).reset_index(drop=True)
        return summary

    @staticmethod
    def build_exit_urgency_contribution_df(
        trades_df: pd.DataFrame,
        full_exit_only: bool = False,
    ) -> pd.DataFrame:
        summary_df = StrategyEvaluator._prepare_exit_summary_source_df(
            trades_df,
            full_exit_only=full_exit_only,
        )
        if summary_df.empty:
            return pd.DataFrame(columns=EXIT_URGENCY_CONTRIBUTION_COLUMNS)

        base_cols = [
            "entry_strategy",
            "exit_strategy",
            "entry_filter",
            "exit_confirmation_days",
        ]
        group_cols = base_cols + ["exit_urgency"]
        contribution = StrategyEvaluator._aggregate_exit_metrics(
            summary_df,
            group_cols,
            base_cols,
            "strategy_trade_total",
        )
        contribution["trade_ratio"] = (
            contribution["trade_count"] / contribution["strategy_trade_total"]
        )

        strategy_returns = (
            summary_df.groupby(base_cols, dropna=False)["return_jpy"]
            .sum()
            .rename("strategy_total_return_jpy")
            .reset_index()
        )
        contribution = contribution.merge(strategy_returns, on=base_cols, how="left")
        contribution["return_contribution_ratio"] = contribution.apply(
            lambda row: (
                row["total_return_jpy"] / row["strategy_total_return_jpy"]
                if pd.notna(row["strategy_total_return_jpy"])
                and abs(float(row["strategy_total_return_jpy"])) > 1e-9
                else pd.NA
            ),
            axis=1,
        )
        contribution["trade_scope"] = summary_df["trade_scope"].iloc[0]

        for col in EXIT_URGENCY_CONTRIBUTION_COLUMNS:
            if col not in contribution.columns:
                contribution[col] = pd.NA

        contribution = contribution[EXIT_URGENCY_CONTRIBUTION_COLUMNS]
        contribution = contribution.sort_values(
            ["entry_strategy", "exit_strategy", "trade_count", "exit_urgency"],
            ascending=[True, True, False, True],
        ).reset_index(drop=True)
        return contribution

    @staticmethod
    def build_exit_trigger_summary_df(
        trades_df: pd.DataFrame,
        full_exit_only: bool = False,
    ) -> pd.DataFrame:
        return StrategyEvaluator.build_exit_reason_detail_df(
            trades_df,
            full_exit_only=full_exit_only,
        )

    @staticmethod
    def write_exit_summary_markdown(
        output_file: Path,
        exit_reason_detail_df: pd.DataFrame,
        exit_urgency_summary_df: pd.DataFrame,
        exit_urgency_contribution_df: pd.DataFrame,
    ):
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("# 退出结果整理与分析\n\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            if (
                exit_reason_detail_df is None
                or exit_reason_detail_df.empty
                or exit_urgency_summary_df is None
                or exit_urgency_summary_df.empty
                or exit_urgency_contribution_df is None
                or exit_urgency_contribution_df.empty
            ):
                f.write("无可用退出分析数据。\n")
                return

            contribution_df = exit_urgency_contribution_df.copy()
            summary_df = exit_urgency_summary_df.copy()
            detail_df = exit_reason_detail_df.copy()

            contribution_df = contribution_df.sort_values(
                ["entry_strategy", "exit_strategy", "trade_count", "exit_urgency"],
                ascending=[True, True, False, True],
            )
            summary_overall = summary_df[summary_df["period"] == "__ALL__"].copy()
            detail_overall = detail_df[detail_df["period"] == "__ALL__"].copy()

            strategy_keys = (
                contribution_df[
                    [
                        "entry_strategy",
                        "exit_strategy",
                        "entry_filter",
                        "exit_confirmation_days",
                        "trade_scope",
                    ]
                ]
                .drop_duplicates()
                .itertuples(index=False, name=None)
            )
            strategy_keys = list(strategy_keys)

            f.write("## 1. 总体概览\n\n")
            f.write(f"- 策略组合数: {len(strategy_keys)}\n")
            f.write(
                f"- 第一层明细行数: {len(detail_df)}\n"
            )
            f.write(
                f"- 第二层汇总行数: {len(summary_df)}\n"
            )
            f.write(
                f"- 第三层贡献行数: {len(contribution_df)}\n\n"
            )

            f.write("## 2. 策略级退出贡献摘要\n\n")
            for key in strategy_keys:
                entry_strategy, exit_strategy, entry_filter, confirm_days, trade_scope = key
                strat_contrib = contribution_df[
                    (contribution_df["entry_strategy"] == entry_strategy)
                    & (contribution_df["exit_strategy"] == exit_strategy)
                    & (contribution_df["entry_filter"] == entry_filter)
                    & (contribution_df["exit_confirmation_days"] == confirm_days)
                    & (contribution_df["trade_scope"] == trade_scope)
                ].copy()
                if strat_contrib.empty:
                    continue

                strategy_total_return = strat_contrib["strategy_total_return_jpy"].iloc[0]
                strategy_trade_total = strat_contrib["strategy_trade_total"].iloc[0]
                top_positive = strat_contrib.sort_values("total_return_jpy", ascending=False).head(3)
                top_negative = strat_contrib.sort_values("total_return_jpy", ascending=True).head(3)

                f.write(
                    f"### {entry_strategy} × {exit_strategy} × {entry_filter}"
                    f" (confirm={confirm_days}, scope={trade_scope})\n\n"
                )
                f.write(f"- 总退出动作数: {int(strategy_trade_total)}\n")
                f.write(f"- 策略总退出收益: {_fmt_jpy(strategy_total_return)} JPY\n\n")

                f.write("正向贡献 Top 3:\n")
                for _, row in top_positive.iterrows():
                    f.write(
                        f"- {row['exit_urgency']}: {_fmt_jpy(row['total_return_jpy'])} JPY, "
                        f"占策略收益 {_fmt_ratio(row['return_contribution_ratio'])}, "
                        f"次数 {int(row['trade_count'])}\n"
                    )
                f.write("\n")

                f.write("负向贡献 Top 3:\n")
                for _, row in top_negative.iterrows():
                    f.write(
                        f"- {row['exit_urgency']}: {_fmt_jpy(row['total_return_jpy'])} JPY, "
                        f"占策略收益 {_fmt_ratio(row['return_contribution_ratio'])}, "
                        f"次数 {int(row['trade_count'])}\n"
                    )
                f.write("\n")

            f.write("## 3. 第二层退出类型汇总（__ALL__）\n\n")
            for key in strategy_keys:
                entry_strategy, exit_strategy, entry_filter, confirm_days, trade_scope = key
                strat_summary = summary_overall[
                    (summary_overall["entry_strategy"] == entry_strategy)
                    & (summary_overall["exit_strategy"] == exit_strategy)
                    & (summary_overall["entry_filter"] == entry_filter)
                    & (summary_overall["exit_confirmation_days"] == confirm_days)
                    & (summary_overall["trade_scope"] == trade_scope)
                ].copy()
                if strat_summary.empty:
                    continue

                strat_summary = strat_summary.sort_values(
                    ["trade_count", "total_return_jpy"],
                    ascending=[False, False],
                )

                f.write(
                    f"### {entry_strategy} × {exit_strategy} × {entry_filter}"
                    f" (confirm={confirm_days}, scope={trade_scope})\n\n"
                )
                f.write(
                    "| 退出类型 | 次数 | 占比 | 平均收益率 | 平均持有天数 | 胜率 | 总收益(JPY) | 毛盈利(JPY) | 毛亏损(JPY) |\n"
                )
                f.write(
                    "|----------|------|------|------------|--------------|------|--------------|--------------|--------------|\n"
                )
                for _, row in strat_summary.iterrows():
                    f.write(
                        f"| {row['exit_urgency']} | {int(row['trade_count'])} | {_fmt_ratio(row['trade_ratio'])} | "
                        f"{_fmt_pct(row['avg_return_pct'])} | {_fmt_num(row['avg_holding_days'])} | "
                        f"{_fmt_pct(row['win_rate_pct'], 1)} | {_fmt_jpy(row['total_return_jpy'])} | "
                        f"{_fmt_jpy(row['gross_profit_jpy'])} | {_fmt_jpy(row['gross_loss_jpy'])} |\n"
                    )
                f.write("\n")

            f.write("## 4. 第一层退出原因明细（每策略 Top 10）\n\n")
            for key in strategy_keys:
                entry_strategy, exit_strategy, entry_filter, confirm_days, trade_scope = key
                strat_detail = detail_overall[
                    (detail_overall["entry_strategy"] == entry_strategy)
                    & (detail_overall["exit_strategy"] == exit_strategy)
                    & (detail_overall["entry_filter"] == entry_filter)
                    & (detail_overall["exit_confirmation_days"] == confirm_days)
                    & (detail_overall["trade_scope"] == trade_scope)
                ].copy()
                if strat_detail.empty:
                    continue

                strat_detail = strat_detail.sort_values(
                    ["trade_count", "total_return_jpy"],
                    ascending=[False, False],
                ).head(10)

                f.write(
                    f"### {entry_strategy} × {exit_strategy} × {entry_filter}"
                    f" (confirm={confirm_days}, scope={trade_scope})\n\n"
                )
                f.write(
                    "| 退出类型 | 退出原因 | 次数 | 占比 | 平均收益率 | 胜率 | 总收益(JPY) |\n"
                )
                f.write(
                    "|----------|----------|------|------|------------|------|--------------|\n"
                )
                for _, row in strat_detail.iterrows():
                    reason = str(row["exit_reason"]).replace("|", "/")
                    f.write(
                        f"| {row['exit_urgency']} | {reason} | {int(row['trade_count'])} | {_fmt_ratio(row['trade_ratio'])} | "
                        f"{_fmt_pct(row['avg_return_pct'])} | {_fmt_pct(row['win_rate_pct'], 1)} | {_fmt_jpy(row['total_return_jpy'])} |\n"
                    )
                f.write("\n")

    def analyze_by_market_regime(self) -> pd.DataFrame:
        """
        按市场环境分组分析

        Returns:
            按市场环境、策略组合分组的统计结果
        """
        df = self._create_results_dataframe()

        if df.empty:
            return df

        # 添加市场环境分类
        df["market_regime"] = df["topix_return_pct"].apply(MarketRegime.classify)

        # 按市场环境和策略组合分组
        grouped = df.groupby(
            ["market_regime", "entry_strategy", "exit_strategy", "entry_filter"]
        ).agg(
            {
                "return_pct": ["mean", "std", "min", "max"],
                "alpha": ["mean", "std"],
                "sharpe_ratio": "mean",
                "win_rate_pct": "mean",
                "max_drawdown_pct": "mean",
                "period": "count",  # 样本数量
            }
        )

        # 重命名列
        grouped.columns = ["_".join(col).strip() for col in grouped.columns.values]
        grouped = grouped.rename(columns={"period_count": "sample_count"})

        # 按市场环境和平均alpha排序
        grouped = grouped.sort_values(
            ["market_regime", "alpha_mean"], ascending=[True, False]
        )

        return grouped.reset_index()

    def get_top_strategies_by_regime(self, top_n: int = 3) -> Dict[str, pd.DataFrame]:
        """
        找出每种市场环境下表现最好的top N策略

        Args:
            top_n: 每种环境返回的策略数量

        Returns:
            {market_regime: DataFrame of top strategies}
        """
        df = self._create_results_dataframe()

        if df.empty:
            return {}

        df["market_regime"] = df["topix_return_pct"].apply(MarketRegime.classify)

        results = {}
        for regime in sorted(df["market_regime"].unique()):
            regime_df = df[df["market_regime"] == regime]

            # 按alpha排序，取top N
            top_strategies = regime_df.nlargest(top_n, "alpha")[
                [
                    "period",
                    "entry_strategy",
                    "exit_strategy",
                    "entry_filter",
                    "return_pct",
                    "topix_return_pct",
                    "alpha",
                    "sharpe_ratio",
                    "win_rate_pct",
                ]
            ]

            results[regime] = top_strategies

        return results

    def rank_by_target20_goal(self) -> pd.DataFrame:
        return rank_target20_goal_df(self._create_results_dataframe())

    def rank_by_legacy_goal(self) -> pd.DataFrame:
        return rank_legacy_goal_df(self._create_results_dataframe())

    @staticmethod
    def _minmax_normalize_series(series: pd.Series, higher_is_better: bool) -> pd.Series:
        return _minmax_normalize_series(series, higher_is_better)

    def rank_by_risk60_profit40(self) -> pd.DataFrame:
        return rank_risk60_profit40_df(self._create_results_dataframe())

    def rank_by_prs_train(self) -> pd.DataFrame:
        return rank_prs_train_df(
            self._create_results_dataframe(),
            complexity_penalty_resolver=get_strategy_complexity_penalty,
        )

    def save_results(self, prefix: str = "evaluation", ranking_mode: str = "target20"):
        """
        保存结果到文件

        生成：
        1. {prefix}_raw.csv - 原始结果
        2. {prefix}_by_regime.csv - 按市场环境分组
        3. {prefix}_trades.csv - 原始逐笔交易
        4. {prefix}_exit_trigger_summary.csv - 第一层：退出原因明细
        5. {prefix}_exit_urgency_summary.csv - 第二层：退出类型汇总
        6. {prefix}_exit_urgency_contribution.csv - 第三层：退出贡献汇总
        7. {prefix}_report.md - Markdown报告
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. 原始结果CSV
        df = self._create_results_dataframe()
        raw_file = self.output_dir / f"{prefix}_raw_{timestamp}.csv"
        df.to_csv(raw_file, index=False, encoding="utf-8-sig")
        print(f"✅ 原始结果已保存: {raw_file}")

        # 2. 按市场环境分组CSV
        regime_df = self.analyze_by_market_regime()
        regime_file = self.output_dir / f"{prefix}_by_regime_{timestamp}.csv"
        regime_df.to_csv(regime_file, index=False, encoding="utf-8-sig")
        print(f"✅ 市场环境分析已保存: {regime_file}")

        files = {
            "raw": str(raw_file),
            "regime": str(regime_file),
        }

        trade_df = self._create_trade_results_dataframe()
        trades_file = self.output_dir / f"{prefix}_trades_{timestamp}.csv"
        trade_df.to_csv(trades_file, index=False, encoding="utf-8-sig")
        print(f"✅ 原始交易明细已保存: {trades_file}")
        files["trades"] = str(trades_file)

        try:
            indicator_file = write_enriched_trades_sidecar(
                trades_csv=trades_file,
                data_root=self.data_root,
                trades_df=trade_df,
            )
        except Exception as e:
            print(f"⚠️ 交易指标 sidecar 生成失败: {e}")
        else:
            print(f"✅ 交易指标 sidecar 已保存: {indicator_file}")
            files["trades_indicators"] = str(indicator_file)

        last_day_signal_df = self._create_last_day_signal_dataframe()
        last_day_signal_file = self.output_dir / f"{prefix}_last_day_signals_{timestamp}.csv"
        last_day_signal_df.to_csv(
            last_day_signal_file,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"✅ 最后一天待执行信号已保存: {last_day_signal_file}")
        files["last_day_signals"] = str(last_day_signal_file)

        last_day_position_df = self._create_last_day_position_dataframe()
        last_day_position_file = self.output_dir / f"{prefix}_last_day_positions_{timestamp}.csv"
        last_day_position_df.to_csv(
            last_day_position_file,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"✅ 最后一天持仓快照已保存: {last_day_position_file}")
        files["last_day_positions"] = str(last_day_position_file)

        last_day_snapshot_file = self.output_dir / f"{prefix}_last_day_snapshot_{timestamp}.json"
        last_day_snapshot_file.write_text(
            json.dumps(self.evaluation_run_snapshots, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"✅ 最后一天快照已保存: {last_day_snapshot_file}")
        files["last_day_snapshot"] = str(last_day_snapshot_file)

        daily_signal_df = self._create_daily_signal_dataframe()
        daily_signal_file = self.output_dir / f"{prefix}_daily_signals_{timestamp}.csv"
        daily_signal_df.to_csv(
            daily_signal_file,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"✅ 全流程日级信号已保存: {daily_signal_file}")
        files["daily_signals"] = str(daily_signal_file)

        daily_position_df = self._create_daily_position_dataframe()
        daily_position_file = self.output_dir / f"{prefix}_daily_positions_{timestamp}.csv"
        daily_position_df.to_csv(
            daily_position_file,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"✅ 全流程日级持仓已保存: {daily_position_file}")
        files["daily_positions"] = str(daily_position_file)

        daily_snapshot_file = self.output_dir / f"{prefix}_daily_snapshots_{timestamp}.json"
        daily_snapshot_file.write_text(
            json.dumps(self.evaluation_daily_snapshots, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"✅ 全流程日级快照已保存: {daily_snapshot_file}")
        files["daily_snapshots"] = str(daily_snapshot_file)

        exit_reason_detail_df = self.build_exit_reason_detail_df(
            trade_df,
            full_exit_only=False,
        )
        exit_trigger_file = self.output_dir / f"{prefix}_exit_trigger_summary_{timestamp}.csv"
        exit_reason_detail_df.to_csv(exit_trigger_file, index=False, encoding="utf-8-sig")
        print(f"✅ 第一层退出原因明细已保存: {exit_trigger_file}")
        files["exit_trigger_summary"] = str(exit_trigger_file)
        files["exit_reason_detail"] = str(exit_trigger_file)

        exit_urgency_summary_df = self.build_exit_urgency_summary_df(
            trade_df,
            full_exit_only=False,
        )
        exit_urgency_summary_file = self.output_dir / f"{prefix}_exit_urgency_summary_{timestamp}.csv"
        exit_urgency_summary_df.to_csv(
            exit_urgency_summary_file,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"✅ 第二层退出类型汇总已保存: {exit_urgency_summary_file}")
        files["exit_urgency_summary"] = str(exit_urgency_summary_file)

        exit_urgency_contribution_df = self.build_exit_urgency_contribution_df(
            trade_df,
            full_exit_only=False,
        )
        exit_urgency_contribution_file = self.output_dir / f"{prefix}_exit_urgency_contribution_{timestamp}.csv"
        exit_urgency_contribution_df.to_csv(
            exit_urgency_contribution_file,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"✅ 第三层退出贡献汇总已保存: {exit_urgency_contribution_file}")
        files["exit_urgency_contribution"] = str(exit_urgency_contribution_file)

        exit_summary_report_file = self.output_dir / f"{prefix}_exit_summary_report_{timestamp}.md"
        self.write_exit_summary_markdown(
            exit_summary_report_file,
            exit_reason_detail_df,
            exit_urgency_summary_df,
            exit_urgency_contribution_df,
        )
        print(f"✅ 退出结果总结报告已保存: {exit_summary_report_file}")
        files["exit_summary_report"] = str(exit_summary_report_file)

        if ranking_mode == "legacy":
            legacy_rank_df = self.rank_by_legacy_goal()
            legacy_rank_file = self.output_dir / f"{prefix}_legacy_rank_{timestamp}.csv"
            legacy_rank_df.to_csv(legacy_rank_file, index=False, encoding="utf-8-sig")
            print(f"✅ legacy排名已保存: {legacy_rank_file}")
            files["legacy_rank"] = str(legacy_rank_file)

        if ranking_mode == "target20":
            target20_rank_df = self.rank_by_target20_goal()
            target20_rank_file = self.output_dir / f"{prefix}_target20_rank_{timestamp}.csv"
            target20_rank_df.to_csv(target20_rank_file, index=False, encoding="utf-8-sig")
            print(f"✅ 20%目标导向排名已保存: {target20_rank_file}")
            files["target20_rank"] = str(target20_rank_file)

        if ranking_mode == "risk60_profit40":
            risk60_rank_df = self.rank_by_risk60_profit40()
            risk60_rank_file = self.output_dir / f"{prefix}_risk60_profit40_rank_{timestamp}.csv"
            risk60_rank_df.to_csv(risk60_rank_file, index=False, encoding="utf-8-sig")
            print(f"✅ risk60_profit40排名已保存: {risk60_rank_file}")
            files["risk60_profit40_rank"] = str(risk60_rank_file)

        if ranking_mode == "prs_train":
            prs_train_rank_df = self.rank_by_prs_train()
            prs_train_rank_file = self.output_dir / f"{prefix}_prs_train_rank_{timestamp}.csv"
            prs_train_rank_df.to_csv(prs_train_rank_file, index=False, encoding="utf-8-sig")
            print(f"✅ PRS-Train排名已保存: {prs_train_rank_file}")
            files["prs_train_rank"] = str(prs_train_rank_file)

        # 4. Markdown报告
        report_file = self.output_dir / f"{prefix}_report_{timestamp}.md"
        self._generate_markdown_report(report_file, ranking_mode=ranking_mode)
        print(f"✅ 报告已保存: {report_file}")
        files["report"] = str(report_file)

        replay_last_day_production_style = None
        if self.replay_seed is not None:
            replay_last_day_production_style = (
                self._build_replay_last_day_production_style_artifact(
                    prefix=prefix,
                    timestamp=timestamp,
                )
            )
            if replay_last_day_production_style is not None:
                print(
                    "✅ Replay最后一天 production-style 报告已保存: "
                    f"{replay_last_day_production_style['report_file']}"
                )
                files["replay_last_day_production_style_report"] = str(
                    replay_last_day_production_style["report_file"]
                )

        if self.replay_seed is not None:
            replay_sidecar_file = self.output_dir / f"{prefix}_replay_sidecar_{timestamp}.json"
            replay_payload = {
                "replay_seed": {
                    "report_file": self.replay_seed.report_file,
                    "report_date": self.replay_seed.report_date,
                    "replay_start_date": self.replay_seed.replay_start_date,
                    "group_id": self.replay_seed.group_id,
                    "group_name": self.replay_seed.group_name,
                    "starting_cash_jpy": self.replay_seed.starting_cash_jpy,
                    "baseline_total_equity_jpy": self.replay_seed.baseline_total_equity_jpy,
                    "prior_signal_file": self.replay_seed.prior_signal_file,
                    "pending_orders": [
                        asdict(order) for order in self.replay_seed.pending_orders
                    ],
                    "positions": [asdict(position) for position in self.replay_seed.positions],
                },
                "runs": self.replay_run_snapshots,
                "last_day_production_style": replay_last_day_production_style,
            }
            replay_sidecar_file.write_text(
                json.dumps(replay_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"✅ Replay sidecar已保存: {replay_sidecar_file}")
            files["replay_sidecar"] = str(replay_sidecar_file)
        return files

    def _generate_markdown_report(self, output_file: Path, ranking_mode: str = "target20"):
        """生成Markdown格式的评价报告"""
        df = self._create_results_dataframe()

        if df.empty:
            return

        with open(output_file, "w", encoding="utf-8") as f:
            f.write("# 策略综合评价报告\n\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            self._write_capacity_snapshot(f, df)

            # 1. 总体概览
            f.write("## 2. 总体概览\n\n")
            f.write(f"- 评估时段数: {df['period'].nunique()}\n")
            f.write(
                f"- 策略组合数: {len(df.groupby(['entry_strategy', 'exit_strategy', 'entry_filter']))}\n"
            )
            f.write(f"- 总回测次数: {len(df)}\n")
            f.write(f"- 入场策略: {', '.join(df['entry_strategy'].unique())}\n")
            f.write(f"- 出场策略: {', '.join(df['exit_strategy'].unique())}\n\n")
            f.write(f"- 入场过滤器: {', '.join(df['entry_filter'].unique())}\n\n")

            # 2. 时段TOPIX表现
            f.write("## 3. 时段TOPIX表现\n\n")
            period_summary = (
                df.groupby("period")
                .agg(
                    {
                        "topix_return_pct": "first",
                        "start_date": "first",
                        "end_date": "first",
                    }
                )
                .reset_index()
            )
            period_summary["market_regime"] = period_summary["topix_return_pct"].apply(
                MarketRegime.classify
            )

            f.write("| 时段 | 日期范围 | TOPIX收益率 | 市场环境 |\n")
            f.write("|------|---------|------------|----------|\n")
            for _, row in period_summary.iterrows():
                topix_str = (
                    f"{row['topix_return_pct']:.2f}%"
                    if pd.notna(row["topix_return_pct"])
                    else "N/A (数据缺失)"
                )
                f.write(
                    f"| {row['period']} | {row['start_date']} ~ {row['end_date']} | "
                    f"{topix_str} | {row['market_regime']} |\n"
                )
            f.write("\n")

            # 3. 按市场环境分类的最优策略
            f.write("## 4. 按市场环境分类的最优策略\n\n")
            df["market_regime"] = df["topix_return_pct"].apply(MarketRegime.classify)

            for regime in sorted(df["market_regime"].unique()):
                regime_df = df[df["market_regime"] == regime].copy()

                # 按 alpha 排序（有TOPIX数据时）或按 return_pct 排序（无TOPIX数据时）
                has_alpha = (
                    regime_df["alpha"].notna().any()
                    and regime_df["topix_return_pct"].notna().any()
                )
                if has_alpha and regime_df["alpha"].sum() != 0:
                    regime_df = regime_df.sort_values("alpha", ascending=False)
                else:
                    regime_df = regime_df.sort_values("return_pct", ascending=False)

                f.write(f"### {regime}\n\n")
                sample_count = len(regime_df)
                periods = regime_df["period"].unique()
                f.write(f"样本数: {sample_count} (时段: {', '.join(periods)})\n\n")

                # 表头：根据是否有TOPIX数据动态调整
                if (
                    regime_df["topix_return_pct"].notna().any()
                    and regime_df["topix_return_pct"].sum() != 0
                ):
                    f.write(
                        "| 排名 | 时段 | 入场策略 | 出场策略 | 入场过滤器 | 收益率 | 超额收益 | 夏普比率 | 胜率 |\n"
                    )
                    f.write(
                        "|------|------|---------|---------|------------|--------|---------|---------|------|\n"
                    )
                    for idx, (_, row) in enumerate(regime_df.iterrows(), 1):
                        alpha_str = (
                            f"{row['alpha']:.2f}%" if pd.notna(row["alpha"]) else "N/A"
                        )
                        f.write(
                            f"| {idx} | {row['period']} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                            f"{row['return_pct']:.2f}% | {alpha_str} | "
                            f"{row['sharpe_ratio']:.2f} | {row['win_rate_pct']:.1f}% |\n"
                        )
                else:
                    f.write(
                        "| 排名 | 时段 | 入场策略 | 出场策略 | 入场过滤器 | 收益率 | 夏普比率 | 胜率 |\n"
                    )
                    f.write(
                        "|------|------|---------|---------|------------|--------|---------|------|\n"
                    )
                    for idx, (_, row) in enumerate(regime_df.iterrows(), 1):
                        f.write(
                            f"| {idx} | {row['period']} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                            f"{row['return_pct']:.2f}% | "
                            f"{row['sharpe_ratio']:.2f} | {row['win_rate_pct']:.1f}% |\n"
                        )
                f.write("\n")

            # 3.5 策略单位列表
            f.write("## 4.5 策略单位性能汇总\n\n")
            f.write(
                "所有策略组合在各时段、各市场环境下的表现对比（按时段和入场策略分组）：\n\n"
            )

            # 按策略组合分组，显示所有时段数据
            strategies = sorted(
                df.groupby(["entry_strategy", "exit_strategy", "entry_filter"])
                .size()
                .index.tolist()
            )

            f.write(
                "| 时段 | 入场策略 | 出场策略 | 入场过滤器 | 收益率 | 超额收益 | 市场环境 |\n"
            )
            f.write(
                "|------|---------|---------|------------|--------|---------|----------|\n"
            )

            for entry_strat, exit_strat, filter_name in strategies:
                combo_df = df[
                    (df["entry_strategy"] == entry_strat)
                    & (df["exit_strategy"] == exit_strat)
                    & (df["entry_filter"] == filter_name)
                ].sort_values("period")
                for _, row in combo_df.iterrows():
                    alpha_str = (
                        f"{row['alpha']:.2f}%" if pd.notna(row["alpha"]) else "N/A"
                    )
                    f.write(
                        f"| {row['period']} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                        f"{row['return_pct']:.2f}% | {alpha_str} | {row['market_regime']} |\n"
                    )
            f.write("\n")

            if ranking_mode == "legacy":
                f.write("## 4. Legacy 全天候排名\n\n")
                legacy_df = self.rank_by_legacy_goal()
                if legacy_df.empty:
                    f.write("无可用legacy排名数据。\n\n")
                else:
                    f.write(
                        "| 排名 | 入场策略 | 出场策略 | 入场过滤器 | 平均排名 | 平均收益率 | 平均超额收益 | 平均夏普 | 平均胜率 |\n"
                    )
                    f.write(
                        "|------|---------|---------|------------|----------|------------|--------------|----------|----------|\n"
                    )
                    for _, row in legacy_df.iterrows():
                        f.write(
                            f"| {int(row['rank'])} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                            f"{row['avg_rank']:.2f} | {row['mean_return']:.2f}% | {row['mean_alpha']:.2f}% | "
                            f"{row['mean_sharpe']:.2f} | {row['mean_win_rate']:.1f}% |\n"
                        )
                    f.write("\n")

            if ranking_mode == "target20":
                f.write("## 4. 年度20%目标导向排名（不以TOPIX涨跌幅为考核基准）\n\n")
                f.write("排序目标：尽量在每个时段达到20%，尽量避免亏损时段；牛市亏损从出现即重罚，最差时段收益<0即开始扣分。\n\n")

                rank_df = self.rank_by_target20_goal()
                if rank_df.empty:
                    f.write("无可用排名数据。\n")
                    return

                f.write(
                    "| 排名 | 入场策略 | 出场策略 | 入场过滤器 | 目标分(0-100) | 达标率(>=20%) | 平均缺口(%) | 亏损时段占比 | 牛市亏损占比 | 熊市达标率 | 最差时段收益(%) |\n"
                )
                f.write(
                    "|------|---------|---------|------------|---------------|---------------|-------------|--------------|--------------|------------|----------------|\n"
                )

                for _, row in rank_df.iterrows():
                    f.write(
                        f"| {int(row['rank'])} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                        f"{row['target20_score']:.2f} | {row['hit20_rate'] * 100:.1f}% | {row['shortfall_mean']:.2f} | "
                        f"{row['loss_period_rate'] * 100:.1f}% | {row['bull_loss_rate'] * 100:.1f}% | "
                        f"{row['bear_hit20_rate'] * 100:.1f}% | {row['worst_period_return']:.2f}% |\n"
                    )

                f.write("\n")
                f.write("### 推荐策略（Top 3）\n\n")

                for _, row in rank_df.head(3).iterrows():
                    f.write(
                        f"- **#{int(row['rank'])} {row['entry_strategy']} × {row['exit_strategy']} × {row['entry_filter']}**"
                        f" | 目标分={row['target20_score']:.2f}, 达标率={row['hit20_rate'] * 100:.1f}%, "
                        f"平均缺口={row['shortfall_mean']:.2f}%, 亏损时段占比={row['loss_period_rate'] * 100:.1f}%, "
                        f"最差时段={row['worst_period_return']:.2f}%\n"
                    )

            if ranking_mode == "risk60_profit40":
                f.write("## 4. Risk60/Profit40 排名（v2）\n\n")
                f.write("评分公式：0.35*mdd_inverse_norm + 0.25*worst_year_return_norm + 0.25*avg_alpha_norm + 0.15*positive_alpha_ratio_norm\n\n")

                rank_df = self.rank_by_risk60_profit40()
                if rank_df.empty:
                    f.write("无可用排名数据。\n")
                    return

                f.write(
                    "| 排名 | 入场策略 | 出场策略 | 入场过滤器 | 60/40得分 | 平均回撤 | 最差年度收益 | 平均Alpha | 正Alpha占比 | 平均收益率 |\n"
                )
                f.write(
                    "|------|---------|---------|------------|----------|----------|--------------|-----------|-------------|------------|\n"
                )

                for _, row in rank_df.iterrows():
                    f.write(
                        f"| {int(row['rank'])} | {row['entry_strategy']} | {row['exit_strategy']} | {row['entry_filter']} | "
                        f"{row['risk60_profit40_score']:.4f} | {row['avg_mdd']:.2f}% | {row['worst_year_return']:.2f}% | "
                        f"{row['avg_alpha']:.2f}% | {row['positive_alpha_ratio'] * 100:.1f}% | {row['avg_return']:.2f}% |\n"
                    )

                f.write("\n")
                f.write("### 推荐策略（Top 3）\n\n")
                for _, row in rank_df.head(3).iterrows():
                    f.write(
                        f"- **#{int(row['rank'])} {row['entry_strategy']} × {row['exit_strategy']} × {row['entry_filter']}**"
                        f" | 60/40得分={row['risk60_profit40_score']:.4f}, 平均回撤={row['avg_mdd']:.2f}%, "
                        f"最差年度={row['worst_year_return']:.2f}%, 平均Alpha={row['avg_alpha']:.2f}%\n"
                    )


def create_annual_periods(years: List[int]) -> List[Tuple[str, str, str]]:
    """
    创建年度时间段列表

    Args:
        years: [2021, 2022, 2023, ...]

    Returns:
        [("2021", "2021-01-01", "2021-12-31"), ...]
    """
    return [(str(year), f"{year}-01-01", f"{year}-12-31") for year in years]


def create_monthly_periods(
    year: int, months: List[int] = None
) -> List[Tuple[str, str, str]]:
    """
    创建月度时间段列表

    Args:
        year: 年份
        months: 月份列表（默认1-12）

    Returns:
        [("2021-01", "2021-01-01", "2021-01-31"), ...]
    """
    import calendar

    if months is None:
        months = list(range(1, 13))

    periods = []
    for month in months:
        last_day = calendar.monthrange(year, month)[1]
        periods.append(
            (
                f"{year}-{month:02d}",
                f"{year}-{month:02d}-01",
                f"{year}-{month:02d}-{last_day}",
            )
        )

    return periods


def create_quarterly_periods(years: List[int]) -> List[Tuple[str, str, str]]:
    """
    创建季度时间段列表

    Args:
        years: [2021, 2022, ...]

    Returns:
        [("2021-Q1", "2021-01-01", "2021-03-31"), ...]
    """
    periods = []
    quarters = [
        ("Q1", "01-01", "03-31"),
        ("Q2", "04-01", "06-30"),
        ("Q3", "07-01", "09-30"),
        ("Q4", "10-01", "12-31"),
    ]
    today = datetime.now()
    current_year = today.year
    completed_quarters_in_current_year = max(0, (today.month - 1) // 3)

    for year in years:
        if year > current_year:
            continue

        quarter_limit = len(quarters)
        if year == current_year:
            quarter_limit = completed_quarters_in_current_year

        for q_label, start, end in quarters[:quarter_limit]:
            periods.append((f"{year}-{q_label}", f"{year}-{start}", f"{year}-{end}"))

    return periods

