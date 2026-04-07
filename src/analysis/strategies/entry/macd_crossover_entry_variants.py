"""MACD crossover entry variants for five-year fixed-exit comparison."""

import numpy as np
import pandas as pd

from ...signals import MarketData, SignalAction, TradingSignal
from ..base_entry_strategy import BaseEntryStrategy


class _BaseMACDCrossoverFilteredStrategy(BaseEntryStrategy):
    def __init__(
        self,
        strategy_name: str,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
        max_hist_jump_norm: float = 0.0050,
    ):
        super().__init__(strategy_name=strategy_name)
        self.confirm_volume = bool(confirm_with_volume)
        self.confirm_trend = bool(confirm_with_trend)
        self.min_confidence = float(min_confidence)
        self.max_hist_jump_norm = float(max_hist_jump_norm)

    @staticmethod
    def _safe_float(value):
        if pd.isna(value):
            return np.nan
        return float(value)

    def _build_base_metadata(self, latest, macd_hist_now, macd_hist_prev):
        close = self._safe_float(latest.get("Close"))
        hist_jump = macd_hist_now - macd_hist_prev
        hist_jump_norm = np.nan
        if pd.notna(close) and close > 0:
            hist_jump_norm = hist_jump / close

        metadata = {
            "macd_hist": float(macd_hist_now),
            "macd_hist_prev": float(macd_hist_prev),
            "macd_hist_jump": float(hist_jump),
            "macd_hist_jump_norm": self._safe_float(hist_jump_norm),
            "macd": self._safe_float(latest.get("MACD")),
            "macd_signal": self._safe_float(latest.get("MACD_Signal")),
            "close": close,
            "max_hist_jump_norm": self.max_hist_jump_norm,
        }
        return metadata

    def _evaluate_shock_filter(self, latest, metadata):
        hist_jump_norm = metadata.get("macd_hist_jump_norm")
        if pd.notna(hist_jump_norm) and hist_jump_norm > self.max_hist_jump_norm:
            return {
                "reason": (
                    f"Shock cross filtered (jump/price {hist_jump_norm:.4f} > "
                    f"{self.max_hist_jump_norm:.4f})"
                ),
                "metadata": {
                    "shock_filtered": True,
                },
            }
        return None

    def _evaluate_additional_filter(self, latest, metadata):
        return None

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features

        if len(df) < 2:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        macd_hist_prev = self._safe_float(prev.get("MACD_Hist"))
        macd_hist_now = self._safe_float(latest.get("MACD_Hist"))

        if pd.isna(macd_hist_prev) or pd.isna(macd_hist_now):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing MACD histogram"],
                strategy_name=self.strategy_name,
            )

        golden_cross = macd_hist_prev < 0 and macd_hist_now > 0
        metadata = self._build_base_metadata(latest, macd_hist_now, macd_hist_prev)

        if not golden_cross:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["No MACD golden cross"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        shock_block = self._evaluate_shock_filter(latest, metadata)
        if shock_block is not None:
            block_metadata = dict(metadata)
            block_metadata.update(shock_block["metadata"])
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=[shock_block["reason"]],
                metadata=block_metadata,
                strategy_name=self.strategy_name,
            )

        metadata["shock_filtered"] = False
        additional_block = self._evaluate_additional_filter(latest, metadata)
        if additional_block is not None:
            block_metadata = dict(metadata)
            block_metadata.update(additional_block["metadata"])
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=[additional_block["reason"]],
                metadata=block_metadata,
                strategy_name=self.strategy_name,
            )

        reasons = ["MACD golden cross detected"]
        confidence = 0.7

        if self.confirm_volume:
            volume_now = self._safe_float(latest.get("Volume"))
            volume_avg = latest.get("Volume_SMA_20")
            if pd.isna(volume_avg):
                volume_avg = df["Volume"].rolling(20).mean().iloc[-1]
            volume_avg = self._safe_float(volume_avg)

            if pd.notna(volume_now) and pd.notna(volume_avg) and volume_avg > 0:
                volume_ratio = volume_now / volume_avg
                metadata["volume_ratio"] = float(volume_ratio)
                if volume_ratio > 1.2:
                    reasons.append(f"Volume surge (+{(volume_ratio - 1) * 100:.0f}%)")
                    confidence += 0.1
                else:
                    reasons.append(f"Volume normal ({volume_ratio:.2f}x avg)")
                    confidence -= 0.05

        if self.confirm_trend:
            price = self._safe_float(latest.get("Close"))
            ema_200 = self._safe_float(latest.get("EMA_200"))

            if pd.notna(price) and pd.notna(ema_200):
                metadata["ema_200"] = float(ema_200)
                metadata["price_above_ema200"] = bool(price > ema_200)
                if price > ema_200:
                    reasons.append("Above EMA200 (uptrend)")
                    confidence += 0.1
                else:
                    reasons.append("Below EMA200 (caution)")
                    confidence -= 0.15

        confidence = float(np.clip(confidence, 0.0, 1.0))
        metadata["golden_cross"] = True

        if confidence >= self.min_confidence:
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=confidence,
                reasons=reasons,
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        metadata["low_confidence"] = True
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=confidence,
            reasons=reasons
            + [f"Confidence {confidence:.2f} < threshold {self.min_confidence}"],
            metadata=metadata,
            strategy_name=self.strategy_name,
        )


class MACDCrossoverShockFilterV1(_BaseMACDCrossoverFilteredStrategy):
    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
        max_hist_jump_norm: float = 0.0050,
    ):
        super().__init__(
            strategy_name="MACDCrossoverShockFilterV1",
            confirm_with_volume=confirm_with_volume,
            confirm_with_trend=confirm_with_trend,
            min_confidence=min_confidence,
            max_hist_jump_norm=max_hist_jump_norm,
        )


class MACDCrossoverShockOverheatFilterV2(_BaseMACDCrossoverFilteredStrategy):
    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
        max_hist_jump_norm: float = 0.0050,
        max_bb_pctb: float = 0.94,
        max_gap_above_ema20_pct: float = 5.0,
        max_return_20d: float = 0.05,
    ):
        super().__init__(
            strategy_name="MACDCrossoverShockOverheatFilterV2",
            confirm_with_volume=confirm_with_volume,
            confirm_with_trend=confirm_with_trend,
            min_confidence=min_confidence,
            max_hist_jump_norm=max_hist_jump_norm,
        )
        self.max_bb_pctb = float(max_bb_pctb)
        self.max_gap_above_ema20_pct = float(max_gap_above_ema20_pct)
        self.max_return_20d = float(max_return_20d)

    def _evaluate_additional_filter(self, latest, metadata):
        close = self._safe_float(latest.get("Close"))
        ema_20 = self._safe_float(latest.get("EMA_20"))
        bb_pctb = self._safe_float(latest.get("BB_PctB"))
        return_20d = self._safe_float(latest.get("Return_20d"))
        gap_above_ema20_pct = np.nan
        if pd.notna(close) and pd.notna(ema_20) and ema_20 > 0:
            gap_above_ema20_pct = ((close / ema_20) - 1.0) * 100.0

        metadata["bb_pctb"] = bb_pctb
        metadata["ema_20"] = ema_20
        metadata["gap_above_ema20_pct"] = self._safe_float(gap_above_ema20_pct)
        metadata["return_20d"] = return_20d
        metadata["max_bb_pctb"] = self.max_bb_pctb
        metadata["max_gap_above_ema20_pct"] = self.max_gap_above_ema20_pct
        metadata["max_return_20d"] = self.max_return_20d

        if (
            pd.notna(bb_pctb)
            and pd.notna(gap_above_ema20_pct)
            and pd.notna(return_20d)
            and bb_pctb > self.max_bb_pctb
            and gap_above_ema20_pct > self.max_gap_above_ema20_pct
            and return_20d > self.max_return_20d
        ):
            return {
                "reason": (
                    f"Overheat filtered (PctB {bb_pctb:.2f}, gap {gap_above_ema20_pct:.2f}%, "
                    f"return20d {return_20d:.2%})"
                ),
                "metadata": {
                    "overheat_filtered": True,
                },
            }

        metadata["overheat_filtered"] = False
        return None


class MACDCrossoverFollowThroughFilterV3(_BaseMACDCrossoverFilteredStrategy):
    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
        max_ema20_slope_pct: float = 0.25,
        min_prev_hist_norm: float = 0.0010,
        max_hist_now_norm: float = 0.0008,
    ):
        super().__init__(
            strategy_name="MACDCrossoverFollowThroughFilterV3",
            confirm_with_volume=confirm_with_volume,
            confirm_with_trend=confirm_with_trend,
            min_confidence=min_confidence,
            max_hist_jump_norm=1.0,
        )
        self.max_ema20_slope_pct = float(max_ema20_slope_pct)
        self.min_prev_hist_norm = float(min_prev_hist_norm)
        self.max_hist_now_norm = float(max_hist_now_norm)

    def _evaluate_shock_filter(self, latest, metadata):
        return None

    def _compute_followthrough_state(self, latest, metadata):
        close = self._safe_float(latest.get("Close"))
        ema_20 = self._safe_float(latest.get("EMA_20"))
        macd = self._safe_float(latest.get("MACD"))
        macd_signal = self._safe_float(latest.get("MACD_Signal"))
        macd_hist_prev = self._safe_float(metadata.get("macd_hist_prev"))
        macd_hist_now = self._safe_float(metadata.get("macd_hist"))

        ema20_slope_pct = np.nan
        hist_prev_norm = np.nan
        hist_now_norm = np.nan
        prev_ema_20 = np.nan

        if pd.notna(close) and close > 0:
            if pd.notna(macd_hist_prev):
                hist_prev_norm = abs(macd_hist_prev) / close
            if pd.notna(macd_hist_now):
                hist_now_norm = macd_hist_now / close

        if pd.notna(ema_20):
            prev_ema_20 = self._safe_float(latest.get("EMA_20_prev"))
            if pd.isna(prev_ema_20):
                prev_ema_20 = self._safe_float(metadata.get("ema_20_prev"))
            if pd.notna(prev_ema_20) and prev_ema_20 > 0:
                ema20_slope_pct = ((ema_20 / prev_ema_20) - 1.0) * 100.0

        both_below_zero = bool(
            pd.notna(macd) and pd.notna(macd_signal) and macd < 0 and macd_signal < 0
        )
        is_fragile_cross = bool(
            both_below_zero
            and pd.notna(ema20_slope_pct)
            and ema20_slope_pct < self.max_ema20_slope_pct
            and pd.notna(hist_prev_norm)
            and hist_prev_norm > self.min_prev_hist_norm
            and pd.notna(hist_now_norm)
            and hist_now_norm < self.max_hist_now_norm
        )

        metadata["macd_below_zero"] = bool(pd.notna(macd) and macd < 0)
        metadata["macd_signal_below_zero"] = bool(
            pd.notna(macd_signal) and macd_signal < 0
        )
        metadata["both_below_zero"] = both_below_zero
        metadata["ema_20"] = ema_20
        metadata["ema_20_prev"] = prev_ema_20
        metadata["ema20_slope_pct"] = self._safe_float(ema20_slope_pct)
        metadata["hist_prev_norm"] = self._safe_float(hist_prev_norm)
        metadata["hist_now_norm"] = self._safe_float(hist_now_norm)
        metadata["max_ema20_slope_pct"] = self.max_ema20_slope_pct
        metadata["min_prev_hist_norm"] = self.min_prev_hist_norm
        metadata["max_hist_now_norm"] = self.max_hist_now_norm
        metadata["fragile_candidate"] = is_fragile_cross

        return {
            "ema20_slope_pct": self._safe_float(ema20_slope_pct),
            "hist_prev_norm": self._safe_float(hist_prev_norm),
            "hist_now_norm": self._safe_float(hist_now_norm),
            "is_fragile_cross": is_fragile_cross,
        }

    @staticmethod
    def _build_fragile_reason(followthrough_state):
        return (
            "Weak follow-through filtered "
            f"(below zero axis, EMA20 slope {followthrough_state['ema20_slope_pct']:.3f}%, "
            f"prev hist norm {followthrough_state['hist_prev_norm']:.4f}, "
            f"now hist norm {followthrough_state['hist_now_norm']:.4f})"
        )

    def _evaluate_additional_filter(self, latest, metadata):
        followthrough_state = self._compute_followthrough_state(latest, metadata)
        if followthrough_state["is_fragile_cross"]:
            return {
                "reason": self._build_fragile_reason(followthrough_state),
                "metadata": {
                    "followthrough_filtered": True,
                },
            }

        metadata["followthrough_filtered"] = False
        return None

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features

        if len(df) < 2:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1].copy()
        prev = df.iloc[-2]
        latest["EMA_20_prev"] = prev.get("EMA_20")
        wrapped_market_data = MarketData(
            ticker=market_data.ticker,
            current_date=market_data.current_date,
            df_features=pd.concat([df.iloc[:-1], pd.DataFrame([latest], index=[df.index[-1]])]),
            df_trades=market_data.df_trades,
            df_financials=market_data.df_financials,
            metadata=market_data.metadata,
        )
        return super().generate_entry_signal(wrapped_market_data)


class MACDCrossoverFragileBelowZeroFilterV4(MACDCrossoverFollowThroughFilterV3):
    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
        max_ema20_slope_pct: float = 0.225,
        min_prev_hist_norm: float = 0.0013,
        max_hist_now_norm: float = 0.0004,
    ):
        super().__init__(
            confirm_with_volume=confirm_with_volume,
            confirm_with_trend=confirm_with_trend,
            min_confidence=min_confidence,
            max_ema20_slope_pct=max_ema20_slope_pct,
            min_prev_hist_norm=min_prev_hist_norm,
            max_hist_now_norm=max_hist_now_norm,
        )
        self.strategy_name = "MACDCrossoverFragileBelowZeroFilterV4"


class MACDCrossoverFragileBelowZeroLowADXFilterV5(
    MACDCrossoverFragileBelowZeroFilterV4
):
    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
        max_ema20_slope_pct: float = 0.225,
        min_prev_hist_norm: float = 0.0013,
        max_hist_now_norm: float = 0.0004,
        max_adx_14: float = 20.0,
    ):
        super().__init__(
            confirm_with_volume=confirm_with_volume,
            confirm_with_trend=confirm_with_trend,
            min_confidence=min_confidence,
            max_ema20_slope_pct=max_ema20_slope_pct,
            min_prev_hist_norm=min_prev_hist_norm,
            max_hist_now_norm=max_hist_now_norm,
        )
        self.max_adx_14 = float(max_adx_14)
        self.strategy_name = "MACDCrossoverFragileBelowZeroLowADXFilterV5"

    def _evaluate_additional_filter(self, latest, metadata):
        followthrough_state = self._compute_followthrough_state(latest, metadata)
        adx_14 = self._safe_float(latest.get("ADX_14"))
        metadata["adx_14"] = adx_14
        metadata["max_adx_14"] = self.max_adx_14
        metadata["low_adx_candidate"] = False

        if not followthrough_state["is_fragile_cross"]:
            metadata["low_adx_filtered"] = False
            metadata["followthrough_filtered"] = False
            return None

        is_low_adx = pd.notna(adx_14) and adx_14 < self.max_adx_14
        metadata["low_adx_candidate"] = bool(is_low_adx)
        metadata["low_adx_filtered"] = bool(is_low_adx)

        if not is_low_adx:
            metadata["followthrough_filtered"] = False
            return None

        return {
            "reason": (
                f"{self._build_fragile_reason(followthrough_state)} with weak ADX {adx_14:.2f} < "
                f"{self.max_adx_14:.2f}"
            ),
            "metadata": {
                "followthrough_filtered": True,
                "low_adx_filtered": True,
            },
        }


class MACDCrossoverFragileBelowZeroDownweightV6(
    MACDCrossoverFragileBelowZeroLowADXFilterV5
):
    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
        max_ema20_slope_pct: float = 0.225,
        min_prev_hist_norm: float = 0.0013,
        max_hist_now_norm: float = 0.0004,
        max_adx_14: float = 20.0,
        base_score: float = 50.0,
        fragile_score: float = 35.0,
        low_adx_score: float = 25.0,
        weak_volume_score: float = 15.0,
        max_weak_volume_ratio: float = 1.1,
    ):
        super().__init__(
            confirm_with_volume=confirm_with_volume,
            confirm_with_trend=confirm_with_trend,
            min_confidence=min_confidence,
            max_ema20_slope_pct=max_ema20_slope_pct,
            min_prev_hist_norm=min_prev_hist_norm,
            max_hist_now_norm=max_hist_now_norm,
            max_adx_14=max_adx_14,
        )
        self.base_score = float(base_score)
        self.fragile_score = float(fragile_score)
        self.low_adx_score = float(low_adx_score)
        self.weak_volume_score = float(weak_volume_score)
        self.max_weak_volume_ratio = float(max_weak_volume_ratio)
        self.strategy_name = "MACDCrossoverFragileBelowZeroDownweightV6"

    def _evaluate_additional_filter(self, latest, metadata):
        followthrough_state = self._compute_followthrough_state(latest, metadata)
        adx_14 = self._safe_float(latest.get("ADX_14"))
        is_low_adx = bool(
            followthrough_state["is_fragile_cross"]
            and pd.notna(adx_14)
            and adx_14 < self.max_adx_14
        )

        metadata["adx_14"] = adx_14
        metadata["max_adx_14"] = self.max_adx_14
        metadata["low_adx_candidate"] = is_low_adx
        metadata["low_adx_filtered"] = False
        metadata["followthrough_filtered"] = False
        return None

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        signal = super().generate_entry_signal(market_data)

        if signal.action != SignalAction.BUY:
            return signal

        fragile_candidate = bool(signal.metadata.get("fragile_candidate"))
        low_adx_candidate = bool(signal.metadata.get("low_adx_candidate"))
        volume_ratio = self._safe_float(signal.metadata.get("volume_ratio"))
        weak_volume_candidate = bool(
            low_adx_candidate
            and pd.notna(volume_ratio)
            and volume_ratio < self.max_weak_volume_ratio
        )

        score = self.base_score
        tier = "base"
        downweight_reason = None

        if weak_volume_candidate:
            score = self.weak_volume_score
            tier = "fragile_low_adx_weak_volume"
            downweight_reason = (
                f"Priority downweighted to {score:.1f} for fragile below-zero cross, "
                f"ADX < {self.max_adx_14:.1f}, and volume ratio {volume_ratio:.2f} < "
                f"{self.max_weak_volume_ratio:.2f}"
            )
        elif low_adx_candidate:
            score = self.low_adx_score
            tier = "fragile_low_adx"
            downweight_reason = (
                f"Priority downweighted to {score:.1f} for fragile below-zero cross with "
                f"ADX {signal.metadata.get('adx_14'):.2f} < {self.max_adx_14:.2f}"
            )
        elif fragile_candidate:
            score = self.fragile_score
            tier = "fragile"
            downweight_reason = (
                f"Priority downweighted to {score:.1f} for fragile below-zero MACD cross"
            )

        signal.metadata["score"] = float(score)
        signal.metadata["base_score"] = self.base_score
        signal.metadata["fragile_score"] = self.fragile_score
        signal.metadata["low_adx_score"] = self.low_adx_score
        signal.metadata["weak_volume_score"] = self.weak_volume_score
        signal.metadata["max_weak_volume_ratio"] = self.max_weak_volume_ratio
        signal.metadata["weak_volume_candidate"] = weak_volume_candidate
        signal.metadata["downweight_tier"] = tier
        signal.metadata["score_downweighted"] = bool(score < self.base_score)

        if downweight_reason is not None:
            signal.reasons = [*signal.reasons, downweight_reason]

        return signal