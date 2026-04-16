"""
Signal Ranker - 买入信号优先級排序
Ranks buy signals when multiple stocks trigger simultaneously.

Contains concrete ranking strategy implementations and the legacy
SignalRanker wrapper for backward compatibility.
"""

import heapq
import random
from typing import Dict, List, Optional, Tuple

from ..analysis.signals import MarketData, SignalAction, TradingSignal


# ==================== Helper ====================


def _filter_and_rank(
    signals: Dict[str, TradingSignal],
    score_fn: "callable",
    top_k: Optional[int] = None,
) -> List[Tuple[str, TradingSignal, float]]:
    """BUY信号のみ抽出しスコア計算後ソート。"""
    scored: List[Tuple[str, TradingSignal, float]] = []
    for ticker, signal in signals.items():
        if signal.action != SignalAction.BUY:
            continue
        scored.append((ticker, signal, score_fn(ticker, signal)))

    if top_k is not None and top_k > 0 and len(scored) > top_k:
        return heapq.nlargest(top_k, scored, key=lambda x: x[2])
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored


# ==================== Concrete Rankers ====================


class DefaultSignalRanker:
    """按原始 score 降序排列（= 旧 simple_score）。"""

    @property
    def name(self) -> str:
        return "default"

    def requires_market_data(self) -> bool:
        return False

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        return _filter_and_rank(
            signals,
            lambda _t, s: s.metadata.get("score", 50.0),
            top_k,
        )


class RandomSignalRanker:
    """随机排序 — 零假设基线。每次调用产生不同顺序。"""

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)

    @property
    def name(self) -> str:
        return "random"

    def requires_market_data(self) -> bool:
        return False

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        scored = _filter_and_rank(
            signals,
            lambda _t, _s: self._rng.random(),
            top_k=None,
        )
        self._rng.shuffle(scored)
        if top_k is not None and top_k > 0:
            scored = scored[:top_k]
        return scored


class ScoreOnlyRanker:
    """纯 score 降序，无资金/信心权重。与 Default 相同但名称明确。"""

    @property
    def name(self) -> str:
        return "score_only"

    def requires_market_data(self) -> bool:
        return False

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        return _filter_and_rank(
            signals,
            lambda _t, s: s.metadata.get("score", 50.0),
            top_k,
        )


class ConfidenceWeightedRanker:
    """score × confidence"""

    @property
    def name(self) -> str:
        return "confidence_weighted"

    def requires_market_data(self) -> bool:
        return False

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        return _filter_and_rank(
            signals,
            lambda _t, s: s.metadata.get("score", 50.0) * s.confidence,
            top_k,
        )


class RiskAdjustedRanker:
    """score / (1 + ATR/Close × 10)  — 低波動優先。"""

    @property
    def name(self) -> str:
        return "risk_adjusted"

    def requires_market_data(self) -> bool:
        return True

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        def _score(ticker: str, signal: TradingSignal) -> float:
            base = signal.metadata.get("score", 50.0)
            md = market_data_dict.get(ticker)
            if md is None:
                return base
            df = md.df_features
            if df.empty or "ATR" not in df.columns or "Close" not in df.columns:
                return base
            atr = df["ATR"].iloc[-1]
            close = df["Close"].iloc[-1]
            if close == 0:
                return base
            return base / (1 + (atr / close) * 10)

        return _filter_and_rank(signals, _score, top_k)


class CompositeRanker:
    """加权综合評分: score × w_s + confidence × 100 × w_c + vol_bonus × w_v"""

    def __init__(
        self,
        score_weight: float = 0.6,
        confidence_weight: float = 0.2,
        volatility_weight: float = 0.2,
    ) -> None:
        self._sw = score_weight
        self._cw = confidence_weight
        self._vw = volatility_weight

    @property
    def name(self) -> str:
        return "composite"

    def requires_market_data(self) -> bool:
        return True

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        def _score(ticker: str, signal: TradingSignal) -> float:
            base = signal.metadata.get("score", 50.0)
            priority = base * self._sw
            priority += signal.confidence * 100 * self._cw
            md = market_data_dict.get(ticker)
            if md is not None:
                df = md.df_features
                if not df.empty and "ATR" in df.columns and "Close" in df.columns:
                    atr = df["ATR"].iloc[-1]
                    close = df["Close"].iloc[-1]
                    if close > 0:
                        vol = atr / close
                        vol_bonus = (1 - min(vol * 10, 1)) * 100
                        priority += vol_bonus * self._vw
            return priority

        return _filter_and_rank(signals, _score, top_k)


class MomentumRanker:
    """近期价格動量排序。不依赖 score/confidence。"""

    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        short_weight: float = 0.6,
    ) -> None:
        self._short = short_window
        self._long = long_window
        self._sw = short_weight
        self._lw = 1.0 - short_weight

    @property
    def name(self) -> str:
        return "momentum"

    def requires_market_data(self) -> bool:
        return True

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        def _score(ticker: str, signal: TradingSignal) -> float:
            md = market_data_dict.get(ticker)
            if md is None:
                return 0.0
            df = md.df_features
            if df.empty or "Close" not in df.columns:
                return 0.0
            closes = df["Close"]
            cur = closes.iloc[-1]
            if cur == 0:
                return 0.0
            short_ret = (cur / closes.iloc[-self._short] - 1) * 100 if len(closes) >= self._short else 0.0
            long_ret = (cur / closes.iloc[-self._long] - 1) * 100 if len(closes) >= self._long else 0.0
            return short_ret * self._sw + long_ret * self._lw

        return _filter_and_rank(signals, _score, top_k)


class VolatilityPenaltyRanker:
    """score − ATR/Close 惩罚。高波動直接扣分。"""

    def __init__(self, penalty_scale: float = 500.0) -> None:
        self._k = penalty_scale

    @property
    def name(self) -> str:
        return "volatility_penalty"

    def requires_market_data(self) -> bool:
        return True

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        def _score(ticker: str, signal: TradingSignal) -> float:
            base = signal.metadata.get("score", 50.0)
            md = market_data_dict.get(ticker)
            if md is None:
                return base
            df = md.df_features
            if df.empty or "ATR" not in df.columns or "Close" not in df.columns:
                return base
            atr = df["ATR"].iloc[-1]
            close = df["Close"].iloc[-1]
            if close == 0:
                return base
            return base - (atr / close) * self._k

        return _filter_and_rank(signals, _score, top_k)


class TrendAlignmentRanker:
    """EMA 排列質量 + MACD histogram 强度。纯技術面，不依赖 score。"""

    @property
    def name(self) -> str:
        return "trend_alignment"

    def requires_market_data(self) -> bool:
        return True

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        def _score(ticker: str, signal: TradingSignal) -> float:
            md = market_data_dict.get(ticker)
            if md is None:
                return 0.0
            df = md.df_features
            if df.empty:
                return 0.0
            latest = df.iloc[-1]

            pts = 0.0

            # EMA stack: Close > EMA_20 > EMA_50 > EMA_200
            close = latest.get("Close", 0)
            ema20 = latest.get("EMA_20", 0)
            ema50 = latest.get("EMA_50", 0)
            ema200 = latest.get("EMA_200", 0)
            if close and ema20 and ema50 and ema200:
                if close > ema20 > ema50 > ema200:
                    pts += 40  # perfect order
                elif close > ema20 > ema50:
                    pts += 25
                elif close > ema20:
                    pts += 10

            # MACD histogram strength (normalized)
            hist = latest.get("MACD_Histogram", latest.get("MACD_hist", 0))
            if close and close > 0 and hist:
                norm_hist = (hist / close) * 1000  # per-mille
                pts += max(min(norm_hist * 10, 30), -10)

            # RSI sweet spot (50-65)
            rsi = latest.get("RSI", 50)
            if 50 <= rsi <= 65:
                pts += 20
            elif 40 <= rsi < 50:
                pts += 10
            elif rsi > 75:
                pts -= 10

            return pts

        return _filter_and_rank(signals, _score, top_k)


# ==================== Legacy Wrapper ====================


class SignalRanker:
    """
    旧接口包装器 — 向後兼容。

    内部委托给対応的具体 Ranker 類。新代码应直接使用具体类或通过
    strategy_loader.load_ranking_strategy() 加载。
    """

    _METHOD_MAP: Dict[str, type] = {
        "simple_score": DefaultSignalRanker,
        "default": DefaultSignalRanker,
        "confidence_weighted": ConfidenceWeightedRanker,
        "risk_adjusted": RiskAdjustedRanker,
        "composite": CompositeRanker,
        "random": RandomSignalRanker,
        "momentum": MomentumRanker,
        "volatility_penalty": VolatilityPenaltyRanker,
        "trend_alignment": TrendAlignmentRanker,
        "score_only": ScoreOnlyRanker,
    }

    def __init__(
        self,
        method: str = "simple_score",
        score_weight: float = 0.6,
        confidence_weight: float = 0.2,
        volatility_weight: float = 0.2,
    ) -> None:
        self.method = method
        ranker_cls = self._METHOD_MAP.get(method, DefaultSignalRanker)
        if ranker_cls is CompositeRanker:
            self._delegate = ranker_cls(
                score_weight=score_weight,
                confidence_weight=confidence_weight,
                volatility_weight=volatility_weight,
            )
        else:
            self._delegate = ranker_cls()

    @property
    def name(self) -> str:
        return self._delegate.name

    def requires_market_data(self) -> bool:
        return self._delegate.requires_market_data()

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        return self._delegate.rank_buy_signals(signals, market_data_dict, top_k)

    def get_top_n_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        n: int,
    ) -> List[Tuple[str, TradingSignal, float]]:
        """获取優先級最高的N个信号"""
        return self.rank_buy_signals(signals, market_data_dict, top_k=n)
