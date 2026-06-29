"""
基于综合打分的Entry策略

使用Score Utils计算综合分数，达到阈值时买入
"""

from typing import Any

import numpy as np
import pandas as pd

from ..base_entry_strategy import BaseEntryStrategy
from ...signals import TradingSignal, SignalAction, MarketData
from ...scoring_utils import calculate_composite_score, check_earnings_risk


class SimpleScorerStrategy(BaseEntryStrategy):
    """
    基于综合打分的Entry策略（Simple权重）
    
    权重: Technical 40%, Institutional 30%, Fundamental 20%, Volatility 10%
    使用Score Utils工具
    
    Args:
        buy_threshold: 买入阈值（默认65分）
    """
    
    def __init__(self, buy_threshold: float = 65.0):
        super().__init__(strategy_name="SimpleScorer")
        self.threshold = buy_threshold
        self.weights = {
            "technical": 0.4,
            "institutional": 0.3,
            "fundamental": 0.2,
            "volatility": 0.1
        }

    precompute_family_key = "composite_scorer_v1"

    def build_precompute_feature_cache(
        self,
        *,
        features: pd.DataFrame,
        trades: pd.DataFrame | None = None,
        financials: pd.DataFrame | None = None,
        metadata: dict[str, Any] | None = None,
        **_unused: object,
    ) -> pd.DataFrame:
        return _build_scorer_precompute_cache(
            features=features,
            trades=trades,
            financials=financials,
            metadata=metadata,
        )

    def precompute_entry_signals(
        self,
        *,
        ticker: str,
        features: pd.DataFrame,
        trades: pd.DataFrame | None = None,
        financials: pd.DataFrame | None = None,
        metadata: dict[str, Any] | None = None,
        feature_cache: pd.DataFrame | None = None,
    ) -> dict[int, TradingSignal]:
        scores = feature_cache
        if scores is None:
            scores = self.build_precompute_feature_cache(
                features=features,
                trades=trades,
                financials=financials,
                metadata=metadata,
            )
        return _precompute_scorer_signals(
            scores=scores,
            weights=self.weights,
            threshold=self.threshold,
            strategy_name=self.strategy_name,
            enhanced=False,
        )
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """生成入场信号"""
        
        # 调用Score Utils计算综合分数
        score, breakdown = calculate_composite_score(
            market_data.df_features,
            market_data.df_trades,
            market_data.df_financials,
            market_data.metadata,
            weights=self.weights,
            current_date=market_data.current_date
        )
        
        # 检查财报风险
        has_earnings_risk, days_until = check_earnings_risk(
            market_data.metadata,
            market_data.current_date
        )
        
        # 财报临近时降低分数
        if has_earnings_risk:
            original_score = score
            score *= 0.8  # 20% penalty
        
        # 判断是否买入
        if score >= self.threshold:
            reasons = [f"Composite score {score:.1f} >= {self.threshold}"]
            reasons.append(f"Tech={breakdown['technical']:.0f}, Inst={breakdown['institutional']:.0f}, "
                          f"Fund={breakdown['fundamental']:.0f}, Vol={breakdown['volatility']:.0f}")
            
            if has_earnings_risk:
                reasons.append(f"Earnings in {days_until} days (penalty applied)")
            
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=min(score / 100, 1.0),
                reasons=reasons,
                metadata={
                    "score": score,
                    "breakdown": breakdown,
                    "earnings_risk": has_earnings_risk
                },
                strategy_name=self.strategy_name
            )
        
        # 观望
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=[f"Score {score:.1f} below threshold {self.threshold}"],
            metadata={"score": score, "breakdown": breakdown},
            strategy_name=self.strategy_name
        )


class EnhancedScorerStrategy(BaseEntryStrategy):
    """
    基于综合打分的Entry策略（Enhanced权重）
    
    权重: Technical 35%, Institutional 35%, Fundamental 20%, Volatility 10%
    更重视机构流向
    使用Score Utils工具
    
    Args:
        buy_threshold: 买入阈值（默认65分）
    """
    
    def __init__(self, buy_threshold: float = 65.0):
        super().__init__(strategy_name="EnhancedScorer")
        self.threshold = buy_threshold
        self.weights = {
            "technical": 0.35,
            "institutional": 0.35,  # 更重视机构
            "fundamental": 0.20,
            "volatility": 0.10
        }

    precompute_family_key = "composite_scorer_v1"

    def build_precompute_feature_cache(
        self,
        *,
        features: pd.DataFrame,
        trades: pd.DataFrame | None = None,
        financials: pd.DataFrame | None = None,
        metadata: dict[str, Any] | None = None,
        **_unused: object,
    ) -> pd.DataFrame:
        return _build_scorer_precompute_cache(
            features=features,
            trades=trades,
            financials=financials,
            metadata=metadata,
        )

    def precompute_entry_signals(
        self,
        *,
        ticker: str,
        features: pd.DataFrame,
        trades: pd.DataFrame | None = None,
        financials: pd.DataFrame | None = None,
        metadata: dict[str, Any] | None = None,
        feature_cache: pd.DataFrame | None = None,
    ) -> dict[int, TradingSignal]:
        scores = feature_cache
        if scores is None:
            scores = self.build_precompute_feature_cache(
                features=features,
                trades=trades,
                financials=financials,
                metadata=metadata,
            )
        return _precompute_scorer_signals(
            scores=scores,
            weights=self.weights,
            threshold=self.threshold,
            strategy_name=self.strategy_name,
            enhanced=True,
        )
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """生成入场信号"""
        
        # 调用Score Utils计算综合分数
        score, breakdown = calculate_composite_score(
            market_data.df_features,
            market_data.df_trades,
            market_data.df_financials,
            market_data.metadata,
            weights=self.weights,
            current_date=market_data.current_date
        )
        
        # 检查财报风险（增强版：渐进式惩罚）
        has_earnings_risk, days_until = check_earnings_risk(
            market_data.metadata,
            market_data.current_date
        )
        
        if has_earnings_risk:
            original_score = score
            if days_until <= 1:
                score *= 0.5  # 50% penalty
            elif days_until <= 3:
                score *= 0.7  # 30% penalty
            elif days_until <= 7:
                score *= 0.85  # 15% penalty
        
        # 判断是否买入
        if score >= self.threshold:
            reasons = [f"Enhanced score {score:.1f} >= {self.threshold}"]
            reasons.append(f"Tech={breakdown['technical']:.0f}, Inst={breakdown['institutional']:.0f}, "
                          f"Fund={breakdown['fundamental']:.0f}")
            
            if has_earnings_risk:
                reasons.append(f"Earnings in {days_until} days")
            
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=min(score / 100, 1.0),
                reasons=reasons,
                metadata={
                    "score": score,
                    "breakdown": breakdown,
                    "earnings_risk": has_earnings_risk,
                    "days_until_earnings": days_until
                },
                strategy_name=self.strategy_name
            )
        
        # 观望
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=[f"Score {score:.1f} below threshold {self.threshold}"],
            metadata={"score": score, "breakdown": breakdown},
            strategy_name=self.strategy_name
        )


_TECHNICAL_REQUIRED_COLUMNS = (
    "Close",
    "EMA_20",
    "EMA_50",
    "EMA_200",
    "RSI",
    "MACD_Hist",
    "MACD",
)


def _build_scorer_precompute_cache(
    *,
    features: pd.DataFrame,
    trades: pd.DataFrame | None,
    financials: pd.DataFrame | None,
    metadata: dict[str, Any] | None,
) -> pd.DataFrame:
    if features.empty:
        cache = pd.DataFrame(index=features.index)
        cache.attrs["valid"] = False
        return cache
    if not all(column in features.columns for column in _TECHNICAL_REQUIRED_COLUMNS):
        cache = pd.DataFrame(index=features.index)
        cache.attrs["valid"] = False
        return cache
    if "ATR_Z_60" not in features.columns and "ATR" not in features.columns:
        cache = pd.DataFrame(index=features.index)
        cache.attrs["valid"] = False
        return cache
    trades_frame = trades if trades is not None else pd.DataFrame()
    if not trades_frame.empty and (
        "EnDate" not in trades_frame.columns or "FrgnBal" not in trades_frame.columns
    ):
        cache = pd.DataFrame(index=features.index)
        cache.attrs["valid"] = False
        return cache
    financials_frame = financials if financials is not None else pd.DataFrame()
    if len(financials_frame) >= 2 and "DiscDate" not in financials_frame.columns:
        cache = pd.DataFrame(index=features.index)
        cache.attrs["valid"] = False
        return cache

    cache = pd.DataFrame(
        {
            "technical": _technical_scores(features),
            "institutional": _institutional_scores(
                features.index,
                trades_frame,
            ),
            "fundamental": _fundamental_scores(
                features.index,
                financials_frame,
            ),
            "volatility": _volatility_scores(features),
        },
        index=features.index,
    )
    earnings_risk, days_until = _earnings_risk_series(features.index, metadata or {})
    cache["earnings_risk"] = earnings_risk
    cache["days_until_earnings"] = days_until
    cache.attrs["valid"] = True
    return cache


def _precompute_scorer_signals(
    *,
    scores: pd.DataFrame,
    weights: dict[str, float],
    threshold: float,
    strategy_name: str,
    enhanced: bool,
) -> dict[int, TradingSignal]:
    if scores.empty or not bool(scores.attrs.get("valid", False)):
        return {}

    total_score = (
        scores["technical"] * weights["technical"]
        + scores["institutional"] * weights["institutional"]
        + scores["fundamental"] * weights["fundamental"]
        + scores["volatility"] * weights["volatility"]
    )
    earnings_risk = scores["earnings_risk"].astype(bool)
    days_until = pd.to_numeric(scores["days_until_earnings"], errors="coerce").fillna(999)

    adjusted_score = total_score.copy()
    if enhanced:
        adjusted_score = adjusted_score.where(~(earnings_risk & (days_until <= 1)), adjusted_score * 0.5)
        adjusted_score = adjusted_score.where(
            ~(earnings_risk & (days_until > 1) & (days_until <= 3)),
            adjusted_score * 0.7,
        )
        adjusted_score = adjusted_score.where(
            ~(earnings_risk & (days_until > 3) & (days_until <= 7)),
            adjusted_score * 0.85,
        )
    else:
        adjusted_score = adjusted_score.where(~earnings_risk, adjusted_score * 0.8)

    buy_mask = (adjusted_score >= threshold).fillna(False)
    signals: dict[int, TradingSignal] = {}
    for row_pos in np.flatnonzero(buy_mask.to_numpy(dtype=bool)):
        row_pos_int = int(row_pos)
        score = float(adjusted_score.iloc[row_pos_int])
        breakdown = {
            "technical": float(scores["technical"].iloc[row_pos_int]),
            "institutional": float(scores["institutional"].iloc[row_pos_int]),
            "fundamental": float(scores["fundamental"].iloc[row_pos_int]),
            "volatility": float(scores["volatility"].iloc[row_pos_int]),
        }
        has_risk = bool(earnings_risk.iloc[row_pos_int])
        days = int(days_until.iloc[row_pos_int])

        if enhanced:
            reasons = [f"Enhanced score {score:.1f} >= {threshold}"]
            reasons.append(
                f"Tech={breakdown['technical']:.0f}, Inst={breakdown['institutional']:.0f}, "
                f"Fund={breakdown['fundamental']:.0f}"
            )
            if has_risk:
                reasons.append(f"Earnings in {days} days")
            metadata = {
                "score": score,
                "breakdown": breakdown,
                "earnings_risk": has_risk,
                "days_until_earnings": days,
            }
        else:
            reasons = [f"Composite score {score:.1f} >= {threshold}"]
            reasons.append(
                f"Tech={breakdown['technical']:.0f}, Inst={breakdown['institutional']:.0f}, "
                f"Fund={breakdown['fundamental']:.0f}, Vol={breakdown['volatility']:.0f}"
            )
            if has_risk:
                reasons.append(f"Earnings in {days} days (penalty applied)")
            metadata = {
                "score": score,
                "breakdown": breakdown,
                "earnings_risk": has_risk,
            }

        signals[row_pos_int] = TradingSignal(
            action=SignalAction.BUY,
            confidence=min(score / 100, 1.0),
            reasons=reasons,
            metadata=metadata,
            strategy_name=strategy_name,
        )
    return signals


def _technical_scores(features: pd.DataFrame) -> pd.Series:
    close = pd.to_numeric(features["Close"], errors="coerce")
    ema20 = pd.to_numeric(features["EMA_20"], errors="coerce")
    ema50 = pd.to_numeric(features["EMA_50"], errors="coerce")
    ema200 = pd.to_numeric(features["EMA_200"], errors="coerce")
    rsi = pd.to_numeric(features["RSI"], errors="coerce")
    macd_hist = pd.to_numeric(features["MACD_Hist"], errors="coerce")
    macd = pd.to_numeric(features["MACD"], errors="coerce")

    score = pd.Series(50.0, index=features.index, dtype="float64")
    perfect_order = (close > ema20) & (ema20 > ema50) & (ema50 > ema200)
    score += perfect_order.fillna(False).astype(float) * 20.0
    basic_uptrend = (~perfect_order.fillna(False)) & (close > ema200)
    score += basic_uptrend.fillna(False).astype(float) * 10.0
    downtrend = close < ema200
    score -= downtrend.fillna(False).astype(float) * 20.0

    healthy_rsi = (rsi >= 40) & (rsi <= 65)
    score += healthy_rsi.fillna(False).astype(float) * 10.0
    score -= (rsi > 75).fillna(False).astype(float) * 10.0
    score += (rsi < 30).fillna(False).astype(float) * 5.0

    positive_hist = macd_hist > 0
    score += positive_hist.fillna(False).astype(float) * 10.0
    score += (positive_hist.fillna(False) & (macd > 0).fillna(False)).astype(float) * 5.0
    return score.clip(lower=0.0, upper=100.0)


def _institutional_scores(index: pd.Index, trades: pd.DataFrame) -> pd.Series:
    if trades.empty or "EnDate" not in trades.columns or "FrgnBal" not in trades.columns:
        return pd.Series(50.0, index=index, dtype="float64")

    local = trades.copy()
    local["EnDate"] = pd.to_datetime(local["EnDate"], errors="coerce")
    local["FrgnBal"] = pd.to_numeric(local["FrgnBal"], errors="coerce")
    local = local[local["EnDate"].notna()].sort_values("EnDate")
    if local.empty:
        return pd.Series(50.0, index=index, dtype="float64")

    trade_dates = pd.DatetimeIndex(local["EnDate"])
    frgn = local["FrgnBal"].to_numpy(dtype="float64")
    values: list[float] = []
    for current_date in pd.DatetimeIndex(index):
        start_date = current_date - pd.Timedelta(days=35)
        left = int(trade_dates.searchsorted(start_date, side="left"))
        right = int(trade_dates.searchsorted(current_date, side="right"))
        if left >= right:
            values.append(50.0)
            continue
        recent = frgn[left:right]
        net_foreign_flow = float(np.nansum(recent))
        score = 50.0
        if net_foreign_flow > 0:
            score += 20.0
            mean_value = _nanmean_or_nan(recent)
            latest_value = recent[-1]
            if not np.isnan(latest_value) and not np.isnan(mean_value) and latest_value > mean_value:
                score += 10.0
        elif net_foreign_flow < 0:
            score -= 15.0
        values.append(float(np.clip(score, 0.0, 100.0)))
    return pd.Series(values, index=index, dtype="float64")


def _fundamental_scores(index: pd.Index, financials: pd.DataFrame) -> pd.Series:
    if financials.empty or "DiscDate" not in financials.columns or len(financials) < 2:
        return pd.Series(50.0, index=index, dtype="float64")

    local = financials.copy()
    local["DiscDate"] = pd.to_datetime(local["DiscDate"], errors="coerce")
    local = local[local["DiscDate"].notna()].sort_values("DiscDate")
    if len(local) < 2:
        return pd.Series(50.0, index=index, dtype="float64")

    disc_dates = pd.DatetimeIndex(local["DiscDate"])
    values: list[float] = []
    for current_date in pd.DatetimeIndex(index):
        right = int(disc_dates.searchsorted(current_date, side="right"))
        if right < 2:
            values.append(50.0)
            continue
        latest = local.iloc[right - 1]
        prev = local.iloc[right - 2]
        score = 50.0

        sales = pd.to_numeric(latest.get("Sales", 0), errors="coerce")
        prev_sales = pd.to_numeric(prev.get("Sales", 0), errors="coerce")
        if pd.notna(sales) and pd.notna(prev_sales) and prev_sales > 0:
            sales_growth = (sales / prev_sales - 1) * 100
            if sales_growth > 10:
                score += 15
            elif sales_growth > 5:
                score += 10
            elif sales_growth < -5:
                score -= 15

        op = pd.to_numeric(latest.get("OperatingProfit", 0), errors="coerce")
        prev_op = pd.to_numeric(prev.get("OperatingProfit", 0), errors="coerce")
        if pd.notna(op) and pd.notna(prev_op) and prev_op > 0:
            op_growth = (op / prev_op - 1) * 100
            if op_growth > 15:
                score += 20
            elif op_growth > 8:
                score += 12
            elif op_growth < -10:
                score -= 20

        forecast_sales = pd.to_numeric(latest.get("FSales", 0), errors="coerce")
        if pd.notna(forecast_sales) and pd.notna(sales) and forecast_sales > 0:
            if sales > forecast_sales * 1.03:
                score += 15
        values.append(float(np.clip(score, 0.0, 100.0)))
    return pd.Series(values, index=index, dtype="float64")


def _volatility_scores(features: pd.DataFrame) -> pd.Series:
    score = pd.Series(50.0, index=features.index, dtype="float64")
    row_numbers = pd.Series(np.arange(len(features)), index=features.index)
    eligible = row_numbers >= 19

    if "ATR_Z_60" in features.columns:
        atr_zscore = pd.to_numeric(features["ATR_Z_60"], errors="coerce")
    else:
        atr_zscore = pd.Series(np.nan, index=features.index, dtype="float64")

    if "ATR" in features.columns:
        atr = pd.to_numeric(features["ATR"], errors="coerce")
        atr_avg = atr.rolling(window=60, min_periods=1).mean()
        atr_std = atr.rolling(window=60, min_periods=1).std()
        fallback_zscore = (atr - atr_avg) / atr_std.where(atr_std > 0)
        atr_zscore = atr_zscore.where(atr_zscore.notna(), fallback_zscore)

    score += (eligible & (atr_zscore < -0.5)).fillna(False).astype(float) * 20.0
    score -= (eligible & (atr_zscore > 1.0)).fillna(False).astype(float) * 20.0
    return score.clip(lower=0.0, upper=100.0)


def _earnings_risk_series(
    index: pd.Index,
    metadata: dict[str, Any],
) -> tuple[pd.Series, pd.Series]:
    raw_events = metadata.get("earnings_calendar") if metadata else None
    if not raw_events:
        return (
            pd.Series(False, index=index, dtype="bool"),
            pd.Series(999, index=index, dtype="int64"),
        )

    events: list[pd.Timestamp] = []
    for event in raw_events:
        try:
            events.append(pd.to_datetime(event["Date"]))
        except Exception:
            continue

    has_risk: list[bool] = []
    days_until: list[int] = []
    for current_date in pd.DatetimeIndex(index):
        found = False
        found_days = 999
        for event_date in events:
            delta = (event_date - current_date).days
            if 0 <= delta <= 7:
                found = True
                found_days = int(delta)
                break
        has_risk.append(found)
        days_until.append(found_days)
    return (
        pd.Series(has_risk, index=index, dtype="bool"),
        pd.Series(days_until, index=index, dtype="int64"),
    )


def _nanmean_or_nan(values: np.ndarray) -> float:
    finite_values = values[~np.isnan(values)]
    if len(finite_values) == 0:
        return float("nan")
    return float(finite_values.mean())
