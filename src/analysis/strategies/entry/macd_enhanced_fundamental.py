"""
增强型MACD Entry策略 - RS + Bias 连续评分模型

核心逻辑：
- MACD 金叉是触发信号（Trigger）
- 连续评分制（Continuous Scoring Model）
  * MACD 金叉：触发条件（必需）
  * RS（相对强度）：连续 [0.0-1.0]，权重 0.10（10%）
  * Bias（乖离率）：连续 [0.0-1.0]，权重 0.35（35%）
  
- 置信度计算：confidence = 0.55 + RS_score×0.10 + Bias_score×0.35
  * 范围 [0.55, 1.0]（0.55 = MACD金叉基础，1.0 = 完美信号）
  
- 进场规则：MACD金叉 AND (RS_score > 0.3 OR Bias_score > 0.2)
  * RS > 0.3：相对强度达中上（超额收益 > 6%）
  * Bias > 0.2：从超卖谷底恢复 20%（从-10% → -8% 或更高）

日本市场特性优化：
- Bias（超卖反弹）权重 3.5× RS（板块强势）
- 超跌后的MACD金叉胜率远高于高位震荡的金叉
- 板块联动强，RS用于过滤弱势板块中的"假突破"
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from datetime import datetime, timedelta
from ..base_entry_strategy import BaseEntryStrategy
from ...signals import TradingSignal, SignalAction, MarketData
from ...signals import Position
from src.data.benchmark_manager import BenchmarkManager


class MACDEnhancedFundamentalStrategy(BaseEntryStrategy):
    """
    增强型 MACD 入场策略（RS + Bias 连续评分）
    
    Args:
        base_confidence: MACD金叉基础置信度（默认 0.55）
        rs_weight: RS权重（默认 0.10，占10%）
        bias_weight: Bias权重（默认 0.35，占35%）
        rs_threshold: 进场时RS最小值（默认 0.3）
        bias_threshold: 进场时Bias最小值（默认 0.2）
        
        # RS 参数（20日收益对标）
        rs_excess_threshold: RS 断点阈值（默认 ±20%）
        
        # Bias 参数（阿离率的恢复进度）
        bias_lookback: 乖离率回溯天数检查超卖（默认 10）
        bias_oversold_threshold: 超卖乖离率下限（默认 -10%）
        bias_recovery_threshold: 收窄到的上限（默认 -5%）
    """
    
    def __init__(
        self,
        base_confidence: float = 0.55,
        rs_weight: float = 0.10,
        bias_weight: float = 0.35,
        rs_threshold: float = 0.3,
        bias_threshold: float = 0.2,
        # RS 参数
        rs_excess_threshold: float = 0.20,
        # Bias 参数
        bias_lookback: int = 10,
        bias_oversold_threshold: float = -10.0,
        bias_recovery_threshold: float = -5.0,
    ):
        super().__init__(strategy_name="MACDEnhancedFundamental")
        self.base_confidence = base_confidence
        self.rs_weight = rs_weight
        self.bias_weight = bias_weight
        self.rs_threshold = rs_threshold
        self.bias_threshold = bias_threshold
        
        self.rs_excess_threshold = rs_excess_threshold
        self.bias_lookback = bias_lookback
        self.bias_oversold_threshold = bias_oversold_threshold
        self.bias_recovery_threshold = bias_recovery_threshold
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """
        生成入场信号（基于连续评分制）
        
        流程：
        1. 检查MACD金叉（触发条件）
        2. 计算RS连续评分 [0.0-1.0]
        3. 计算Bias连续评分 [0.0-1.0]
        4. 检查进场门槛：RS > 0.3 OR Bias > 0.2
        5. 计算加权置信度：0.55 + RS×0.10 + Bias×0.35
        """
        
        df = market_data.df_features
        current_date = market_data.current_date
        
        if len(df) < max(self.bias_lookback + 1, 50):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name
            )
        
        # ===== 步骤1：MACD 金叉（触发条件，必需）=====
        golden_cross = self._check_macd_golden_cross(df)
        
        if not golden_cross:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["No MACD golden cross detected"],
                strategy_name=self.strategy_name
            )
        
        # ===== 步骤2：计算RS连续评分 =====
        rs_score = self._score_relative_strength_continuous(df, current_date)
        
        # ===== 步骤3：计算Bias连续评分 =====
        bias_score = self._score_bias_recovery_continuous(df)
        
        # ===== 步骤4：检查进场门槛 =====
        # 至少一个维度达标：RS > 0.3 或 Bias > 0.2
        entry_gate = rs_score > self.rs_threshold or bias_score > self.bias_threshold
        
        # ===== 步骤5：计算加权置信度 =====
        confidence = self.base_confidence + rs_score * self.rs_weight + bias_score * self.bias_weight
        confidence = np.clip(confidence, 0.0, 1.0)
        
        breakdown = {
            "rs_score": round(rs_score, 3),
            "bias_score": round(bias_score, 3),
            "base_confidence": self.base_confidence,
            "rs_contribution": round(rs_score * self.rs_weight, 3),
            "bias_contribution": round(bias_score * self.bias_weight, 3),
        }
        
        reasons = [
            f"MACD golden cross (trigger)",
            f"RS score: {rs_score:.3f} (weight: {self.rs_weight}, contributions: {rs_score * self.rs_weight:.3f})",
            f"Bias score: {bias_score:.3f} (weight: {self.bias_weight}, contributions: {bias_score * self.bias_weight:.3f})",
            f"Confidence: {self.base_confidence} + {rs_score * self.rs_weight:.3f} + {bias_score * self.bias_weight:.3f} = {confidence:.3f}",
        ]
        
        if entry_gate:
            # 满足进场条件
            reasons.append(f"✓ Entry gate passed (RS > {self.rs_threshold} OR Bias > {self.bias_threshold})")
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=confidence,
                reasons=reasons,
                metadata=breakdown,
                strategy_name=self.strategy_name
            )
        else:
            # 金叉但未通过进场门槛
            reasons.append(f"✗ Entry gate failed (RS={rs_score:.3f} <= {self.rs_threshold}, Bias={bias_score:.3f} <= {self.bias_threshold})")
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=confidence,
                reasons=reasons,
                metadata=breakdown,
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
    
    # ===== 维度1：相对强度（RS）连续评分 =====
    def _score_relative_strength_continuous(self, df: pd.DataFrame, current_date) -> float:
        """
        相对强度连续评分：个股 20日收益 vs TOPIX 20日收益
        
        归一化公式（5分段线性）：
        - 超额收益 <= -20%：0.0
        - -20% < 超额收益 < 0%：线性 0.0 → 0.5
        - 0% <= 超额收益 < +20%：线性 0.5 → 1.0
        - 超额收益 >= +20%：1.0
        
        日本市场特性：
        - 板块联动强（半导体、商社、银行等）
        - 弱势板块中的MACD金叉往往是"假突破"
        - 权重：0.10（RS是辅助，主要靠Bias）
        """
        try:
            if len(df) < 20:
                return 0.0
            
            # ===== 步骤1：计算个股20日收益率 =====
            price_20d_ago = df.iloc[-20]['Close']
            price_now = df.iloc[-1]['Close']
            
            if pd.isna(price_20d_ago) or price_20d_ago <= 0 or pd.isna(price_now):
                return 0.0
            
            stock_return_20d = (price_now - price_20d_ago) / price_20d_ago
            
            # ===== 步骤2：获取TOPIX 20日收益率 =====
            try:
                # 获取当前日期对应的数据行
                current_row = df.iloc[-1]
                if 'Date' in current_row.index:
                    entry_date = pd.to_datetime(current_row['Date'])
                elif hasattr(df, 'index') and df.index.name == 'Date':
                    entry_date = pd.to_datetime(df.index[-1])
                else:
                    entry_date = pd.to_datetime(current_date) if current_date else pd.Timestamp.now()
                
                # 计算20天前的日期（交易日约为日历日的70%，留些buffer）
                lookback_date = entry_date - pd.Timedelta(days=28)
                
                # 从 BenchmarkManager 获取 TOPIX 数据
                manager = BenchmarkManager(client=None, data_root='data')
                topix_df = manager.get_topix_data()
                
                if topix_df is None or topix_df.empty:
                    # TOPIX 数据不可用，保守返回0.5（中性）
                    return 0.5
                
                # 过滤 TOPIX 数据到指定日期范围
                topix_df['Date'] = pd.to_datetime(topix_df['Date'])
                topix_recent = topix_df[
                    (topix_df['Date'] >= lookback_date) & 
                    (topix_df['Date'] <= entry_date)
                ].copy().sort_values('Date')
                
                if len(topix_recent) < 2:
                    # 数据不足，保守返回0.5（中性）
                    return 0.5
                
                # 获取TOPIX 20日首尾价格
                topix_price_start = topix_recent.iloc[0]['Close']
                topix_price_end = topix_recent.iloc[-1]['Close']
                
                if pd.isna(topix_price_start) or topix_price_start <= 0:
                    return 0.5
                
                topix_return_20d = (topix_price_end - topix_price_start) / topix_price_start
                
                # ===== 步骤3：计算超额收益 =====
                excess_return = stock_return_20d - topix_return_20d
                
                # ===== 步骤4：应用归一化范围（±20% 断点） =====
                return self._normalize_rs_score(excess_return)
            
            except Exception as e:
                # TOPIX 获取失败时，保守返回0.5（中性）
                return 0.5
        
        except Exception:
            return 0.5
    
    def _normalize_rs_score(self, excess_return: float) -> float:
        """
        RS 超额收益归一化：5分段线性
        
        Args:
            excess_return: 超额收益率（小数，如 0.12 = +12%）
        
        Returns:
            归一化评分 [0.0, 1.0]
        """
        threshold = self.rs_excess_threshold  # 默认 0.20（±20%）
        
        if excess_return <= -threshold:
            return 0.0
        elif excess_return < 0:
            # [-20%, 0%) → [0.0, 0.5)
            progress = (excess_return + threshold) / threshold
            return 0.5 * progress
        elif excess_return < threshold:
            # [0%, +20%) → (0.5, 1.0)
            progress = excess_return / threshold
            return 0.5 + 0.5 * progress
        else:
            # >= +20%
            return 1.0
    
    # ===== 维度2：Bias（乖离率）连续评分 =====
    def _score_bias_recovery_continuous(self, df: pd.DataFrame) -> float:
        """
        Bias（乖离率）连续评分：超卖恢复进度
        
        逻辑：
        1. 过去 bias_lookback 天内是否触及超卖（< -10%）？
        2. 当前乖离率是否正在恢复中？
        3. 如果两者都满足，计算从超卖到恢复的进度百分比 [0.0-1.0]
        
        归一化公式：
        - 当前Bias <= 超卖阈值（-10%）：0.0
        - 当前Bias >= 恢复阈值（-5%）：1.0
        - 在两者之间：线性插值 (current_bias - oversold) / (recovery - oversold)
        
        权重：0.35（35%，Bias是主要Alpha，权重比RS高3.5倍）
        
        日本市场特性：
        - 散户和机构对25日均线有偏执关注
        - 超跌后的第一个MACD金叉胜率远高于高位金叉
        - 乖离率是日本市场最可靠的均值回归指标
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
            
            # 检查过去 bias_lookback 天内是否触及超卖阈值
            recent_bias = bias.iloc[-self.bias_lookback:]
            touched_oversold = (recent_bias < self.bias_oversold_threshold).any()
            
            # 如果最近没有触及超卖，则返回0（不满足超卖反弹的条件）
            if not touched_oversold:
                return 0.0
            
            # 获取当前乖离率
            current_bias = bias.iloc[-1]
            
            # ===== 应用归一化范围 ===== 
            # 从超卖阈值（-10%）到恢复阈值（-5%）的进度
            if current_bias <= self.bias_oversold_threshold:
                return 0.0
            elif current_bias >= self.bias_recovery_threshold:
                return 1.0
            else:
                # 在两者之间：线性插值
                progress = (current_bias - self.bias_oversold_threshold) / \
                          (self.bias_recovery_threshold - self.bias_oversold_threshold)
                return np.clip(progress, 0.0, 1.0)
        
        except Exception:
            return 0.0
