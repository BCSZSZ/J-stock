# 最终策略架构设计 v2.0

## 🎯 核心设计理念

### 关键认知

**用户洞察：**

> "Exit Strategy 也应该负责生成卖出信号，具体策略（是否看分数、独立检测市场数据）不需要限定，应该在接口处保持开放。Score Utils 作为可选工具，可以在决定买入信号时被调用，也可以在决定卖出信号时被调用。"

### 统一的信号生成模式

```
┌──────────────────────────────────────┐
│  Entry Strategy                       │
│  └─ generate_entry_signal()          │
│      → TradingSignal(BUY/HOLD)       │
└──────────────────────────────────────┘
           ↓ (可选调用)
┌──────────────────────────────────────┐
│  Score Utils (工具函数集)             │
│  - calculate_technical_score()       │
│  - calculate_institutional_score()   │
│  - calculate_fundamental_score()     │
│  - calculate_composite_score()       │
└──────────────────────────────────────┘
           ↑ (可选调用)
┌──────────────────────────────────────┐
│  Exit Strategy                        │
│  └─ generate_exit_signal()           │
│      → TradingSignal(SELL/HOLD)      │
└──────────────────────────────────────┘
```

**设计原则：**

1. ✅ Entry 和 Exit 地位平等 - 都是"信号生成器"
2. ✅ 接口保持开放 - 内部实现自由选择
3. ✅ Score Utils 是工具 - 不是强制依赖
4. ✅ 策略自主决定 - 用分数/技术指标/两者混合

---

## 🏗️ 完整架构图

```
                    Backtest Engine
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
   Entry API           Score Utils          Exit API
       │                   │                   │
generate_entry_signal() (可选工具)  generate_exit_signal()
       │                   │                   │
       ↓                   ↓                   ↓
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Entry Strategies│ │  Pure Functions  │ │ Exit Strategies │
│                 │ │                  │ │                 │
│ 1. Scorer       │←│- tech_score      │→│ 1. ATR Exit     │
│    (用Utils)    │ │- inst_score      │ │    (纯技术)     │
│                 │ │- fund_score      │ │                 │
│ 2. MACD         │ │- composite_score │ │ 2. Score Exit   │
│    (纯技术)     │ │                  │ │    (用Utils)    │
│                 │ │                  │ │                 │
│ 3. Breakout     │ │                  │ │ 3. Layered Exit │
│    (纯技术)     │ │                  │ │    (混合)       │
└─────────────────┘ └─────────────────┘ └─────────────────┘

策略组合矩阵: 3 Entry × 3 Exit = 9 种组合
每种组合对Score Utils的使用完全独立
```

---

## 📝 核心组件设计

### 1. 统一信号定义

```python
# src/analysis/signals.py

from dataclasses import dataclass, field
from typing import List, Dict, Any
from enum import Enum
import pandas as pd

class SignalAction(Enum):
    """交易信号动作"""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

@dataclass
class TradingSignal:
    """
    统一的交易信号
    Entry和Exit都返回此格式
    """
    action: SignalAction           # BUY/SELL/HOLD
    confidence: float              # 0.0-1.0 信号强度
    reasons: List[str]             # 触发原因列表
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外数据
    strategy_name: str = "Unknown"

    def __str__(self):
        return (f"[{self.strategy_name}] {self.action.value} "
                f"(confidence={self.confidence:.2f}): "
                f"{', '.join(self.reasons)}")

@dataclass
class MarketData:
    """
    封装所有市场数据
    传递给Entry和Exit策略
    """
    ticker: str
    current_date: pd.Timestamp
    df_features: pd.DataFrame       # 技术指标
    df_trades: pd.DataFrame         # 机构交易
    df_financials: pd.DataFrame     # 财务数据
    metadata: dict                  # 元数据

    @property
    def latest_price(self) -> float:
        """当前价格"""
        return self.df_features.iloc[-1]['Close']

    @property
    def latest_features(self) -> pd.Series:
        """最新技术指标"""
        return self.df_features.iloc[-1]

@dataclass
class Position:
    """
    持仓信息（传递给Exit策略）
    """
    ticker: str
    entry_price: float
    entry_date: pd.Timestamp
    quantity: int
    entry_signal: TradingSignal     # 保存入场信号（含分数等metadata）
    peak_price_since_entry: float = None

    def __post_init__(self):
        if self.peak_price_since_entry is None:
            self.peak_price_since_entry = self.entry_price

    @property
    def current_pnl_pct(self, current_price: float) -> float:
        """当前盈亏百分比"""
        return ((current_price / self.entry_price) - 1) * 100
```

### 2. Entry Strategy 基类

```python
# src/analysis/strategies/base_entry_strategy.py

from abc import ABC, abstractmethod
from ..signals import TradingSignal, MarketData

class BaseEntryStrategy(ABC):
    """
    Entry策略基类

    职责：分析MarketData，生成买入或持有信号
    实现自由：
    - 可以调用Score Utils
    - 可以使用纯技术指标
    - 可以混合使用
    """

    def __init__(self, strategy_name: str = "BaseEntry"):
        self.strategy_name = strategy_name

    @abstractmethod
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """
        生成入场信号

        Args:
            market_data: 完整市场数据

        Returns:
            TradingSignal: action=BUY表示买入，action=HOLD表示观望

        注意：
        - 返回的metadata中可以包含任何信息（如score、指标值等）
        - 这些信息会保存到Position.entry_signal中
        - Exit策略可以通过Position访问这些信息
        """
        pass
```

### 3. Exit Strategy 基类

```python
# src/analysis/strategies/base_exit_strategy.py

from abc import ABC, abstractmethod
from ..signals import TradingSignal, MarketData, Position

class BaseExitStrategy(ABC):
    """
    Exit策略基类

    职责：分析持仓+市场数据，生成卖出或持有信号
    实现自由：
    - 可以调用Score Utils
    - 可以使用纯技术指标
    - 可以混合使用
    - 可以访问Entry信号的metadata（如入场分数）
    """

    def __init__(self, strategy_name: str = "BaseExit"):
        self.strategy_name = strategy_name

    @abstractmethod
    def generate_exit_signal(
        self,
        position: Position,
        market_data: MarketData
    ) -> TradingSignal:
        """
        生成退出信号

        Args:
            position: 当前持仓信息（含入场价格、日期、Entry信号）
            market_data: 当前市场数据

        Returns:
            TradingSignal: action=SELL表示卖出，action=HOLD表示持有

        注意：
        - 可以通过position.entry_signal.metadata访问入场时的信息
        - 例如：entry_score = position.entry_signal.metadata.get('score')
        - 完全自主决定是否使用这些信息
        """
        pass

    def update_position(self, position: Position, current_price: float):
        """
        更新持仓信息（如peak price）
        子类可重写
        """
        if current_price > position.peak_price_since_entry:
            position.peak_price_since_entry = current_price
```

---

## 🛠️ Score Utils - 可选工具集

```python
# src/analysis/scoring_utils.py

"""
打分工具函数集

定位：
- 纯工具函数，无状态
- 任何策略都可以选择性调用
- Entry策略可以用（生成买入信号）
- Exit策略也可以用（生成卖出信号）
- 也可以完全不用

使用示例：
    # Entry策略使用
    score, breakdown = calculate_composite_score(...)
    if score >= 65:
        return TradingSignal(action=BUY, metadata={'score': score, ...})

    # Exit策略使用
    current_score, _ = calculate_composite_score(...)
    entry_score = position.entry_signal.metadata.get('score', 0)
    if current_score < entry_score - 15:
        return TradingSignal(action=SELL, ...)
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from datetime import timedelta

# =====================================================================
# 核心打分函数
# =====================================================================

def calculate_technical_score(df_features: pd.DataFrame) -> float:
    """技术面分数 (0-100)"""
    if df_features.empty:
        return 50.0

    latest = df_features.iloc[-1]
    score = 50.0

    # EMA Perfect Order
    if latest['Close'] > latest['EMA_20'] > latest['EMA_50'] > latest['EMA_200']:
        score += 20
    elif latest['Close'] > latest['EMA_200']:
        score += 10
    elif latest['Close'] < latest['EMA_200']:
        score -= 20

    # RSI
    rsi = latest['RSI']
    if 40 <= rsi <= 65:
        score += 10
    elif rsi > 75:
        score -= 10

    # MACD
    if latest['MACD_Hist'] > 0:
        score += 10
        if latest['MACD'] > 0:
            score += 5

    return np.clip(score, 0, 100)


def calculate_institutional_score(
    df_trades: pd.DataFrame,
    current_date: pd.Timestamp,
    lookback_days: int = 35
) -> float:
    """机构流向分数 (0-100)"""
    if df_trades.empty:
        return 50.0

    df_trades = df_trades.copy()
    df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])

    start_date = current_date - timedelta(days=lookback_days)
    recent = df_trades[(df_trades['EnDate'] <= current_date) &
                       (df_trades['EnDate'] >= start_date)]

    if recent.empty:
        return 50.0

    score = 50.0
    net_foreign = recent['FrgnBal'].sum()

    if net_foreign > 0:
        score += 20
        if recent.iloc[-1]['FrgnBal'] > recent['FrgnBal'].mean():
            score += 10
    elif net_foreign < 0:
        score -= 15

    return np.clip(score, 0, 100)


def calculate_fundamental_score(df_financials: pd.DataFrame) -> float:
    """基本面分数 (0-100)"""
    if df_financials.empty or len(df_financials) < 2:
        return 50.0

    df_fins = df_financials.sort_values('DiscDate')
    latest = df_fins.iloc[-1]
    prev = df_fins.iloc[-2]

    score = 50.0

    # 营收增长
    sales = pd.to_numeric(latest.get('Sales', 0), errors='coerce')
    prev_sales = pd.to_numeric(prev.get('Sales', 0), errors='coerce')

    if pd.notna(sales) and pd.notna(prev_sales) and prev_sales > 0:
        growth = (sales / prev_sales - 1) * 100
        if growth > 10:
            score += 15
        elif growth > 5:
            score += 10
        elif growth < -5:
            score -= 15

    # 利润增长
    op = pd.to_numeric(latest.get('OperatingProfit', 0), errors='coerce')
    prev_op = pd.to_numeric(prev.get('OperatingProfit', 0), errors='coerce')

    if pd.notna(op) and pd.notna(prev_op) and prev_op > 0:
        op_growth = (op / prev_op - 1) * 100
        if op_growth > 15:
            score += 20
        elif op_growth > 8:
            score += 12
        elif op_growth < -10:
            score -= 20

    return np.clip(score, 0, 100)


def calculate_volatility_score(df_features: pd.DataFrame) -> float:
    """波动性分数 (0-100) - 低波动=高分"""
    if df_features.empty or len(df_features) < 20:
        return 50.0

    latest = df_features.iloc[-1]
    score = 50.0

    atr_current = latest['ATR']
    atr_avg = df_features['ATR'].tail(60).mean()
    atr_std = df_features['ATR'].tail(60).std()

    if pd.notna(atr_avg) and pd.notna(atr_std) and atr_std > 0:
        atr_zscore = (atr_current - atr_avg) / atr_std

        if atr_zscore < -0.5:
            score += 20
        elif atr_zscore > 1.0:
            score -= 20

    return np.clip(score, 0, 100)


def calculate_composite_score(
    df_features: pd.DataFrame,
    df_trades: pd.DataFrame,
    df_financials: pd.DataFrame,
    metadata: dict,
    weights: Dict[str, float] = None,
    current_date: pd.Timestamp = None
) -> Tuple[float, Dict[str, float]]:
    """
    综合分数计算

    Returns:
        (total_score, breakdown)
    """
    if weights is None:
        weights = {
            "technical": 0.4,
            "institutional": 0.3,
            "fundamental": 0.2,
            "volatility": 0.1
        }

    if current_date is None:
        current_date = df_features.index[-1] if not df_features.empty else pd.Timestamp.now()

    tech_score = calculate_technical_score(df_features)
    inst_score = calculate_institutional_score(df_trades, current_date)
    fund_score = calculate_fundamental_score(df_financials)
    vol_score = calculate_volatility_score(df_features)

    total_score = (
        tech_score * weights["technical"] +
        inst_score * weights["institutional"] +
        fund_score * weights["fundamental"] +
        vol_score * weights["volatility"]
    )

    breakdown = {
        "technical": tech_score,
        "institutional": inst_score,
        "fundamental": fund_score,
        "volatility": vol_score
    }

    return total_score, breakdown


# =====================================================================
# 辅助检测函数
# =====================================================================

def check_earnings_risk(metadata: dict, current_date: pd.Timestamp) -> Tuple[bool, int]:
    """检查财报风险"""
    if not metadata or 'earnings_calendar' not in metadata:
        return False, 999

    for event in metadata['earnings_calendar']:
        try:
            evt_date = pd.to_datetime(event['Date'])
            delta = (evt_date - current_date).days
            if 0 <= delta <= 7:
                return True, delta
        except:
            continue

    return False, 999


def detect_institutional_exodus(
    df_trades: pd.DataFrame,
    current_date: pd.Timestamp,
    threshold: float = -50_000_000,
    window_days: int = 14
) -> bool:
    """检测机构大举撤离"""
    if df_trades.empty:
        return False

    df_trades = df_trades.copy()
    df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])

    start_date = current_date - timedelta(days=window_days)
    recent = df_trades[(df_trades['EnDate'] > start_date) &
                       (df_trades['EnDate'] <= current_date)]

    if recent.empty or 'FrgnBal' not in recent.columns:
        return False

    return recent['FrgnBal'].sum() < threshold


def detect_trend_breakdown(df_features: pd.DataFrame) -> Optional[str]:
    """检测趋势破坏（多信号确认）"""
    if len(df_features) < 5:
        return None

    latest = df_features.iloc[-1]
    signals = []

    # 跌破EMA200
    if latest['Close'] < latest['EMA_200']:
        closes_below = (df_features['Close'].tail(3) < df_features['EMA_200'].tail(3)).sum()
        if closes_below >= 2:
            signals.append("Below EMA200")

    # MACD死叉
    if len(df_features) >= 2:
        if df_features.iloc[-2]['MACD_Hist'] > 0 and latest['MACD_Hist'] < 0:
            signals.append("MACD death cross")

    # RSI持续弱势
    if latest['RSI'] < 40 and (df_features['RSI'].tail(5) < 45).sum() >= 4:
        signals.append("Persistent RSI weakness")

    # 成交量萎缩+下跌
    if len(df_features) >= 20:
        volume_avg = df_features['Volume'].tail(20).mean()
        if latest['Volume'] < volume_avg * 0.7:
            price_chg = (latest['Close'] / df_features.iloc[-6]['Close'] - 1) * 100
            if price_chg < -3:
                signals.append("Volume dry-up")

    return " AND ".join(signals) if len(signals) >= 2 else None
```

---

## 📊 策略实现示例

### Entry Strategy 1: ScorerStrategy（使用 Score Utils）

```python
# src/analysis/strategies/entry/scorer_strategy.py

from ..base_entry_strategy import BaseEntryStrategy
from ...signals import TradingSignal, SignalAction, MarketData
from ...scoring_utils import calculate_composite_score, check_earnings_risk

class SimpleScorerStrategy(BaseEntryStrategy):
    """基于综合打分的Entry策略（使用Score Utils）"""

    def __init__(self, buy_threshold: float = 65.0):
        super().__init__(strategy_name="SimpleScorer")
        self.threshold = buy_threshold
        self.weights = {
            "technical": 0.4,
            "institutional": 0.3,
            "fundamental": 0.2,
            "volatility": 0.1
        }

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        # 调用Score Utils
        score, breakdown = calculate_composite_score(
            market_data.df_features,
            market_data.df_trades,
            market_data.df_financials,
            market_data.metadata,
            weights=self.weights,
            current_date=market_data.current_date
        )

        # 财报风险调整
        has_risk, days_until = check_earnings_risk(
            market_data.metadata, market_data.current_date
        )
        if has_risk:
            score *= 0.8

        # 生成信号
        if score >= self.threshold:
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=score / 100,
                reasons=[f"Score {score:.1f} >= {self.threshold}"],
                metadata={"score": score, "breakdown": breakdown},  # 保存分数
                strategy_name=self.strategy_name
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=[f"Score {score:.1f} below threshold"],
            metadata={"score": score},
            strategy_name=self.strategy_name
        )
```

### Entry Strategy 2: MACDCrossover（不使用 Score Utils）

```python
# src/analysis/strategies/entry/macd_crossover.py

from ..base_entry_strategy import BaseEntryStrategy
from ...signals import TradingSignal, SignalAction, MarketData
import numpy as np

class MACDCrossoverStrategy(BaseEntryStrategy):
    """MACD金叉策略（纯技术指标，不使用Score Utils）"""

    def __init__(self, min_confidence: float = 0.6):
        super().__init__(strategy_name="MACDCrossover")
        self.min_confidence = min_confidence

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features

        if len(df) < 2:
            return TradingSignal(action=SignalAction.HOLD, confidence=0.0,
                               reasons=["Insufficient data"], strategy_name=self.strategy_name)

        # MACD金叉检测
        macd_prev = df.iloc[-2]['MACD_Hist']
        macd_now = df.iloc[-1]['MACD_Hist']
        golden_cross = macd_prev < 0 and macd_now > 0

        if not golden_cross:
            return TradingSignal(action=SignalAction.HOLD, confidence=0.0,
                               reasons=["No golden cross"], strategy_name=self.strategy_name)

        # 信号强度计算
        confidence = 0.7
        reasons = ["MACD golden cross"]

        # 成交量确认
        volume_now = df.iloc[-1]['Volume']
        volume_avg = df['Volume'].rolling(20).mean().iloc[-1]
        if volume_now > volume_avg * 1.2:
            confidence += 0.1
            reasons.append("Volume surge")

        # 趋势确认
        if df.iloc[-1]['Close'] > df.iloc[-1]['EMA_200']:
            confidence += 0.1
            reasons.append("Above EMA200")

        confidence = np.clip(confidence, 0.0, 1.0)

        if confidence >= self.min_confidence:
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=confidence,
                reasons=reasons,
                metadata={"macd_hist": macd_now},  # 保存MACD值
                strategy_name=self.strategy_name
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=confidence,
            reasons=reasons + [f"Confidence {confidence:.2f} < threshold"],
            strategy_name=self.strategy_name
        )
```

### Exit Strategy 1: ATRExitStrategy（不使用 Score Utils）

```python
# src/analysis/strategies/exit/atr_exit.py

from ..base_exit_strategy import BaseExitStrategy
from ...signals import TradingSignal, SignalAction, MarketData, Position
from ...scoring_utils import detect_trend_breakdown

class ATRExitStrategy(BaseExitStrategy):
    """ATR退出策略（纯技术指标）"""

    def __init__(self, atr_stop_mult: float = 2.0, atr_trail_mult: float = 3.0):
        super().__init__(strategy_name="ATRExitStrategy")
        self.stop_mult = atr_stop_mult
        self.trail_mult = atr_trail_mult

    def generate_exit_signal(self, position: Position, market_data: MarketData) -> TradingSignal:
        self.update_position(position, market_data.latest_price)

        latest = market_data.df_features.iloc[-1]
        current_price = latest['Close']
        atr = latest['ATR']

        # P0: Hard Stop
        stop_level = position.entry_price - (atr * self.stop_mult)
        if current_price < stop_level:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=1.0,
                reasons=[f"Hard stop: ¥{current_price:,.0f} < ¥{stop_level:,.0f}"],
                metadata={"trigger": "P0_HardStop"},
                strategy_name=self.strategy_name
            )

        # P1: Trailing Stop
        trail_level = position.peak_price_since_entry - (atr * self.trail_mult)
        if current_price < trail_level:
            profit_pct = ((position.peak_price_since_entry / position.entry_price) - 1) * 100
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.9,
                reasons=[f"Trailing stop (peak profit +{profit_pct:.1f}%)"],
                metadata={"trigger": "P1_TrailingStop"},
                strategy_name=self.strategy_name
            )

        # P2: Momentum Exhaustion
        if latest['RSI'] > 70 and current_price < latest['EMA_20']:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.8,
                reasons=[f"Momentum exhaustion: RSI={latest['RSI']:.1f}"],
                metadata={"trigger": "P2_MomentumExhaustion"},
                strategy_name=self.strategy_name
            )

        # P3: Trend Breakdown（使用Score Utils中的辅助函数）
        trend_break = detect_trend_breakdown(market_data.df_features)
        if trend_break:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.85,
                reasons=[f"Trend breakdown: {trend_break}"],
                metadata={"trigger": "P3_TrendBreakdown"},
                strategy_name=self.strategy_name
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["All levels clear"],
            strategy_name=self.strategy_name
        )
```

### Exit Strategy 2: ScoreBasedExit（使用 Score Utils）

```python
# src/analysis/strategies/exit/score_based_exit.py

from ..base_exit_strategy import BaseExitStrategy
from ...signals import TradingSignal, SignalAction, MarketData, Position
from ...scoring_utils import calculate_composite_score

class ScoreBasedExitStrategy(BaseExitStrategy):
    """基于打分的Exit策略（使用Score Utils）"""

    def __init__(self, score_buffer: float = 15.0):
        super().__init__(strategy_name="ScoreBasedExit")
        self.score_buffer = score_buffer
        self.weights = {
            "technical": 0.4,
            "institutional": 0.3,
            "fundamental": 0.2,
            "volatility": 0.1
        }

    def generate_exit_signal(self, position: Position, market_data: MarketData) -> TradingSignal:
        self.update_position(position, market_data.latest_price)

        # 调用Score Utils计算当前分数
        current_score, breakdown = calculate_composite_score(
            market_data.df_features,
            market_data.df_trades,
            market_data.df_financials,
            market_data.metadata,
            weights=self.weights,
            current_date=market_data.current_date
        )

        # 从Entry信号中获取入场分数（如果有）
        entry_score = position.entry_signal.metadata.get('score', 65.0)

        # 判断分数衰减
        score_decay = entry_score - current_score

        if score_decay > self.score_buffer:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=min(score_decay / 50, 1.0),
                reasons=[
                    f"Score decay: {current_score:.1f} < {entry_score:.1f} - {self.score_buffer}",
                    f"Tech={breakdown['technical']:.0f}, Inst={breakdown['institutional']:.0f}"
                ],
                metadata={
                    "trigger": "ScoreDecay",
                    "current_score": current_score,
                    "entry_score": entry_score
                },
                strategy_name=self.strategy_name
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=[f"Score {current_score:.1f} healthy"],
            metadata={"current_score": current_score},
            strategy_name=self.strategy_name
        )
```

### Exit Strategy 3: LayeredExit（混合使用）

```python
# src/analysis/strategies/exit/layered_exit.py

from ..base_exit_strategy import BaseExitStrategy
from ...signals import TradingSignal, SignalAction, MarketData, Position
from ...scoring_utils import (
    calculate_composite_score,  # 可选使用
    detect_institutional_exodus,
    check_earnings_risk,
    detect_trend_breakdown
)

class LayeredExitStrategy(BaseExitStrategy):
    """
    6层Exit策略（混合使用Score Utils）

    参数use_score_utils控制是否使用打分工具
    """

    def __init__(self, use_score_utils: bool = True, trailing_atr_mult: float = 2.0):
        super().__init__(strategy_name="LayeredExit")
        self.use_score_utils = use_score_utils
        self.trail_mult = trailing_atr_mult

    def generate_exit_signal(self, position: Position, market_data: MarketData) -> TradingSignal:
        self.update_position(position, market_data.latest_price)

        # Layer 1: Emergency
        if detect_institutional_exodus(market_data.df_trades, market_data.current_date):
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=1.0,
                reasons=["EMERGENCY: Foreign exodus"],
                metadata={"trigger": "Layer1_Emergency"},
                strategy_name=self.strategy_name
            )

        # Layer 2: Trend Breakdown
        trend_break = detect_trend_breakdown(market_data.df_features)
        if trend_break:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.9,
                reasons=[f"Trend breakdown: {trend_break}"],
                metadata={"trigger": "Layer2_TrendBreakdown"},
                strategy_name=self.strategy_name
            )

        # Layer 3: Multi-Dimensional Weakness (可选使用Score Utils)
        if self.use_score_utils:
            _, breakdown = calculate_composite_score(
                market_data.df_features,
                market_data.df_trades,
                market_data.df_financials,
                market_data.metadata,
                current_date=market_data.current_date
            )

            weak_count = sum(1 for v in breakdown.values() if v < 35)
            if weak_count >= 2:
                return TradingSignal(
                    action=SignalAction.SELL,
                    confidence=0.85,
                    reasons=["Multi-dimensional weakness detected"],
                    metadata={"trigger": "Layer3_Weakness", "breakdown": breakdown},
                    strategy_name=self.strategy_name
                )

        # Layer 4: Trailing Stop
        latest = market_data.df_features.iloc[-1]
        trail_level = position.peak_price_since_entry - (latest['ATR'] * self.trail_mult)
        if latest['Close'] < trail_level:
            profit_pct = ((position.peak_price_since_entry / position.entry_price) - 1) * 100
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.75,
                reasons=[f"Trailing stop (peak +{profit_pct:.1f}%)"],
                metadata={"trigger": "Layer4_TrailingStop"},
                strategy_name=self.strategy_name
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["All layers clear"],
            strategy_name=self.strategy_name
        )
```

---

## 🔄 回测引擎集成

```python
# src/backtest/engine.py (核心修改)

from src.analysis.signals import TradingSignal, SignalAction, MarketData, Position
from src.analysis.strategies.base_entry_strategy import BaseEntryStrategy
from src.analysis.strategies.base_exit_strategy import BaseExitStrategy

class BacktestEngine:
    def backtest_strategy(
        self,
        ticker: str,
        entry_strategy,  # BaseEntryStrategy 或 BaseScorer (向后兼容)
        exit_strategy,   # BaseExitStrategy 或 BaseExiter (向后兼容)
        start_date: str,
        end_date: str
    ) -> BacktestResult:
        """
        统一回测接口
        自动检测新/旧策略接口
        """

        # ... 数据加载 ...

        position = None

        for current_date in trading_days:
            # 构建MarketData
            market_data = MarketData(
                ticker=ticker,
                current_date=current_date,
                df_features=df_features_historical,
                df_trades=df_trades_historical,
                df_financials=df_financials_historical,
                metadata=metadata
            )

            if position is None:
                # ===== Entry Logic =====

                if hasattr(entry_strategy, 'generate_entry_signal'):
                    # 新接口
                    signal = entry_strategy.generate_entry_signal(market_data)

                    if signal.action == SignalAction.BUY:
                        pending_buy_signal = signal
                        logger.info(f"{current_date}: {signal}")

                else:
                    # 旧接口（向后兼容）
                    score_result = entry_strategy.evaluate(...)
                    if score_result.total_score >= buy_threshold:
                        # 包装成TradingSignal
                        pending_buy_signal = TradingSignal(
                            action=SignalAction.BUY,
                            confidence=score_result.total_score / 100,
                            reasons=[f"Score {score_result.total_score}"],
                            metadata={"score": score_result.total_score},
                            strategy_name=entry_strategy.strategy_name
                        )

            else:
                # ===== Exit Logic =====

                if hasattr(exit_strategy, 'generate_exit_signal'):
                    # 新接口
                    signal = exit_strategy.generate_exit_signal(position, market_data)

                    if signal.action == SignalAction.SELL:
                        pending_sell_signal = signal
                        logger.info(f"{current_date}: {signal}")

                else:
                    # 旧接口（向后兼容）
                    exit_signal = exit_strategy.evaluate_exit(...)
                    if exit_signal.action != "HOLD":
                        pending_sell_signal = TradingSignal(
                            action=SignalAction.SELL,
                            confidence=0.8,
                            reasons=[exit_signal.reason],
                            metadata={"urgency": exit_signal.urgency},
                            strategy_name=exit_strategy.strategy_name
                        )

            # ===== 执行Pending Orders =====
            if pending_buy_signal and position is None:
                position = Position(
                    ticker=ticker,
                    entry_price=current_open,
                    entry_date=current_date,
                    quantity=shares,
                    entry_signal=pending_buy_signal  # 保存完整信号
                )

            if pending_sell_signal and position is not None:
                # 执行卖出...
                position = None

        # ... 生成回测结果 ...
```

---

## 📊 策略组合示例

### 组合 1: 纯打分策略

```python
entry = SimpleScorerStrategy(buy_threshold=65)
exit = ScoreBasedExitStrategy(score_buffer=15)

# 特点：Entry和Exit都使用Score Utils
# 适合：相信综合打分逻辑的投资者
```

### 组合 2: 纯技术策略

```python
entry = MACDCrossoverStrategy()
exit = ATRExitStrategy()

# 特点：完全不使用Score Utils
# 适合：技术分析派，快进快出
```

### 组合 3: 混合策略 A

```python
entry = SimpleScorerStrategy()  # 使用Score Utils
exit = ATRExitStrategy()        # 不使用Score Utils

# 特点：综合打分入场 + 技术止损退出
# 适合：基本面选股 + 技术面风控
```

### 组合 4: 混合策略 B

```python
entry = MACDCrossoverStrategy()  # 不使用Score Utils
exit = LayeredExitStrategy(use_score_utils=True)  # 使用Score Utils

# 特点：技术入场 + 多维度退出
# 适合：技术择时 + 全面风控
```

### 组合 5: 灵活策略

```python
entry = SimpleScorerStrategy()
exit = LayeredExitStrategy(use_score_utils=False)

# 特点：Entry用分数，Exit不用分数
# 适合：分数筛选 + 纯技术风控
```

---

## 🎯 实施计划

### Phase 1: 基础架构 (30 分钟)

```
创建文件:
- src/analysis/signals.py
- src/analysis/strategies/__init__.py
- src/analysis/strategies/base_entry_strategy.py
- src/analysis/strategies/base_exit_strategy.py
```

### Phase 2: Score Utils (40 分钟)

```
创建文件:
- src/analysis/scoring_utils.py
  包含所有打分函数和辅助检测函数
```

### Phase 3: Entry Strategies (40 分钟)

```
创建文件:
- src/analysis/strategies/entry/__init__.py
- src/analysis/strategies/entry/scorer_strategy.py
  (SimpleScorerStrategy + EnhancedScorerStrategy)
- src/analysis/strategies/entry/macd_crossover.py
```

### Phase 4: Exit Strategies (60 分钟)

```
创建文件:
- src/analysis/strategies/exit/__init__.py
- src/analysis/strategies/exit/atr_exit.py
- src/analysis/strategies/exit/score_based_exit.py
- src/analysis/strategies/exit/layered_exit.py
```

### Phase 5: 回测引擎 (40 分钟)

```
修改文件:
- src/backtest/engine.py
  支持新Strategy接口，保持向后兼容
```

### Phase 6: 测试验证 (30 分钟)

```
修改文件:
- start_backtest.py
  支持新策略配置

测试:
- 9种组合回测
- 向后兼容性验证
```

**总计: 约 3.5 小时**

---

## ✅ 架构优势总结

### 1. 完全解耦

- Entry 和 Exit 地位平等
- Score Utils 是可选工具
- 任意 Entry × 任意 Exit 组合

### 2. 接口开放

- Exit 可以选择使用/不使用 Score Utils
- 实现细节完全自由
- 支持混合使用

### 3. 灵活扩展

- 3 Entry × 3 Exit = 9 种初始组合
- 未来添加新策略只需实现接口
- 无需修改现有代码

### 4. 职责清晰

- Entry: 生成买入信号
- Exit: 生成卖出信号
- Score Utils: 提供打分工具（可选）

### 5. 向后兼容

- 旧 Scorer/Exiter 继续工作
- 渐进式迁移
- 对比测试方便

---

## 🚀 准备开始

**架构确认：**
✅ Exit Strategy 生成卖出信号（与 Entry 平等）  
✅ 接口保持开放（可选使用 Score Utils）  
✅ Score Utils 是工具（任何地方可调用）  
✅ 支持 9 种组合（3×3）  
✅ 完全向后兼容

**立即开始实施！**
