"""
增强型MACD Entry策略 - 与MACD正交的多维评分模型

核心逻辑：
- MACD 金叉是触发信号（Trigger）
- 评分制（Scoring Model）：≥2分时执行入场
  * MACD 金叉：触发条件（必需）
  * PBR < 1.0：+1 分（估值锚点）
  * RS > TOPIX：+1 分（板块轮动）
  * Bias < -10%（过往）且正在收窄：+1 分（均值回归）

日本市场特性优化：
- 利用日本市场对 PBR / 25日均线 / 机构回购的关注
- 超跌后的MACD金叉胜率远高于高位震荡的金叉
- 板块联动强，需要RS过滤掉弱势板块中的"假突破"
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from ..base_entry_strategy import BaseEntryStrategy
from ...signals import TradingSignal, SignalAction, MarketData
from ...signals import Position


class MACDEnhancedFundamentalStrategy(BaseEntryStrategy):
    """
    增强型 MACD 入场策略（PBR + RS + Bias 评分制）
    
    Args:
        min_score: 最小评分（默认2，即需要至少2个维度确认）
        pbr_threshold: PBR上限（默认1.0）
        bias_lookback: 乖离率回溯天数检查超卖（默认10）
        bias_oversold_threshold: 超卖乖离率下限（默认-15%）
        bias_recovery_threshold: 收窄到的上限（默认-5%）
    """
    
    def __init__(
        self,
        min_score: float = 2.0,
        pbr_threshold: float = 1.0,
        bias_lookback: int = 10,
        bias_oversold_threshold: float = -15.0,
        bias_recovery_threshold: float = -5.0,
    ):
        super().__init__(strategy_name="MACDEnhancedFundamental")
        self.min_score = min_score
        self.pbr_threshold = pbr_threshold
        self.bias_lookback = bias_lookback
        self.bias_oversold_threshold = bias_oversold_threshold
        self.bias_recovery_threshold = bias_recovery_threshold
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """生成入场信号（基于评分制）"""
        
        df = market_data.df_features
        metadata = market_data.metadata
        current_date = market_data.current_date
        
        if len(df) < max(self.bias_lookback + 1, 50):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name
            )
        
        # ===== 条件0：MACD 金叉（触发条件，必需）=====
        golden_cross = self._check_macd_golden_cross(df)
        
        if not golden_cross:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["No MACD golden cross detected"],
                strategy_name=self.strategy_name
            )
        
        scores = []
        breakdown = {}
        
        # ===== 维度1：PBR < 1.0（估值锚点）=====
        pbr_score = self._score_pbr(metadata)
        scores.append(pbr_score)
        breakdown["pbr"] = pbr_score
        
        # ===== 维度2：RS > TOPIX（相对强度）=====
        rs_score = self._score_relative_strength(df, current_date)
        scores.append(rs_score)
        breakdown["rs"] = rs_score
        
        # ===== 维度3：Bias 乖离率筑底（均值回归）=====
        bias_score = self._score_bias_recovery(df)
        scores.append(bias_score)
        breakdown["bias"] = bias_score
        
        # ===== 评分合成 =====
        total_score = sum(scores)  # 0-3 分（不含MACD触发本身）
        
        # 基础置信度 = MACD金叉提供 0.7
        base_confidence = 0.7
        
        # 每个维度加0.1
        confidence = base_confidence + total_score * 0.1
        confidence = np.clip(confidence, 0.0, 1.0)
        
        reasons = [
            f"MACD golden cross (trigger)",
            f"Score: {total_score:.0f}/3 (PBR:{pbr_score:.0f}, RS:{rs_score:.0f}, Bias:{bias_score:.0f})"
        ]
        
        if total_score >= self.min_score:
            # 满足条件，买入
            reasons.append(f"✓ Score {total_score:.0f} >= {self.min_score}")
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=confidence,
                reasons=reasons,
                metadata={
                    "score": total_score,
                    "breakdown": breakdown,
                    "macd_golden_cross": True,
                    "pbr_confirmed": pbr_score > 0,
                    "rs_confirmed": rs_score > 0,
                    "bias_confirmed": bias_score > 0,
                },
                strategy_name=self.strategy_name
            )
        else:
            # 金叉但评分不足
            reasons.append(f"✗ Score {total_score:.0f} < {self.min_score} (wait for more confirmation)")
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=confidence,
                reasons=reasons,
                metadata={
                    "score": total_score,
                    "breakdown": breakdown,
                    "macd_golden_cross": True,
                    "low_score": True,
                },
                strategy_name=self.strategy_name
            )
    
    # ===== 子逻辑：检测MACD金叉 =====
    def _check_macd_golden_cross(self, df: pd.DataFrame) -> bool:
        """
        检测MACD金叉：MACD_Hist 由负转正
        """
        if len(df) < 2:
            return False
        
        macd_hist_prev = df.iloc[-2].get('MACD_Hist', np.nan)
        macd_hist_now = df.iloc[-1].get('MACD_Hist', np.nan)
        
        if pd.isna(macd_hist_prev) or pd.isna(macd_hist_now):
            return False
        
        return macd_hist_prev < 0 and macd_hist_now > 0
    
    # ===== 维度1：PBR < 1.0 =====
    def _score_pbr(self, metadata: dict) -> float:
        """
        PBR 评分：低于阈值得1分，否则得0分
        
        日本市场特性：
        - 东证(TSE)推动PBR改革（目标：PBR > 1.0）
        - PBR < 1.0 意味着市净率折价，有安全边际
        - metadata 中应包含最近的 BookValuePerShare 和 Close
        """
        try:
            # 尝试从metadata读取PBR
            pbr = metadata.get('pbr')
            if pbr is not None:
                if pbr < self.pbr_threshold:
                    return 1.0  # 得1分
                else:
                    return 0.0
            
            # 如果没有直接PBR，尝试计算（假设metadata包含book_value相关数据）
            # 这里是fallback逻辑，实际数据格式可能需要调整
            return 0.0
        
        except Exception as e:
            # 数据不可用时返回0
            return 0.0
    
    # ===== 维度2：相对强度 RS > TOPIX =====
    def _score_relative_strength(self, df: pd.DataFrame, current_date) -> float:
        """
        相对强度评分：个股 20日表现 vs TOPIX
        
        日本市场特性：
        - 板块联动强（半导体、商社、银行等）
        - 弱势板块中的MACD金叉往往是"假突破"
        - 此处简化：比较个股20日收益 vs 历史平均
        
        NOTE: 完整版本需要实时TOPIX数据，目前用价格强度代替
        """
        try:
            if len(df) < 20:
                return 0.0
            
            # 计算个股20日收益率
            price_20d_ago = df.iloc[-20]['Close']
            price_now = df.iloc[-1]['Close']
            
            if pd.isna(price_20d_ago) or price_20d_ago <= 0:
                return 0.0
            
            stock_return_20d = (price_now - price_20d_ago) / price_20d_ago
            
            # 简化RS逻辑：若近期上涨趋势（>0），则视为相对强势
            # 完整实现应该与TOPIX做对标
            if stock_return_20d > 0:
                return 1.0
            else:
                return 0.0
        
        except Exception:
            return 0.0
    
    # ===== 维度3：Bias 乖离率筑底 =====
    def _score_bias_recovery(self, df: pd.DataFrame) -> float:
        """
        乖离率评分：检测超卖后收窄
        
        逻辑：
        1. 过去 bias_lookback 天内是否触及 < bias_oversold_threshold（如-15%）？
        2. 当前乖离率是否正在收窄（回到 > bias_recovery_threshold，如-5%）？
        3. 如果两者都满足，得1分
        
        日本市场特性：
        - 散户和机构对25日均线有偏执关注
        - 超跌后的第一个MACD金叉胜率远高于高位金叉
        """
        try:
            if len(df) < self.bias_lookback + 1:
                return 0.0
            
            # 计算乖离率（Bias）：(Close - MA25) / MA25
            ma25_col = 'SMA_25' if 'SMA_25' in df.columns else None
            if ma25_col is None:
                # 如果没有预计算的SMA_25，则计算
                df_temp = df.copy()
                df_temp['SMA_25'] = df_temp['Close'].rolling(25).mean()
                ma25 = df_temp['SMA_25']
            else:
                ma25 = df[ma25_col]
            
            close = df['Close']
            bias = (close - ma25) / ma25 * 100  # 百分比
            
            # 检查过去 bias_lookback 天内是否触及超卖
            recent_bias = bias.iloc[-self.bias_lookback:]
            touched_oversold = (recent_bias < self.bias_oversold_threshold).any()
            
            # 检查当前乖离率是否在恢复中（> recovery_threshold）
            current_bias = bias.iloc[-1]
            is_recovering = current_bias > self.bias_recovery_threshold
            
            if touched_oversold and is_recovering:
                return 1.0
            
            return 0.0
        
        except Exception:
            return 0.0
