# 策略架构完整重构方案

## 🎯 核心问题诊断

### 当前架构的耦合问题

**问题 1: Exiter 依赖 Scorer 的分数**

```python
# ATRExiter - P3层
if score_value < self.score_threshold:  # ❌ 依赖分数
    return SELL

# LayeredExiter - Layer 2
if score_value < entry_score - buffer:  # ❌ 依赖分数
    return SELL
```

**问题 2: 职责不清**

- Scorer: 既负责买入逻辑，又提供分数给 Exiter
- Exiter: 既负责退出逻辑，又依赖 Scorer 的分数
- 循环依赖：Exiter 需要 Score → Score 来自 Scorer → 但 MACD 策略没有 Score

---

## ✅ 新架构设计：完全解耦

### 架构原则

**1. 单一职责**

- Entry Strategy: 只负责生成买入信号
- Exit Strategy: 只负责生成卖出信号
- Score Utils: 可选的打分工具（非必需）

**2. 独立性**

- Entry 和 Exit 策略互不依赖
- 技术指标类策略（MACD）不使用分数
- 基于分数的退出条件改为技术指标

**3. 可组合性**

- 任意 Entry 策略 + 任意 Exit 策略
- SimpleScorerStrategy + ATRExiter ✅
- MACDCrossoverStrategy + ATRExiter ✅
- SimpleScorerStrategy + LayeredExiter ✅

---

## 🏗️ 新架构层次结构

```
┌─────────────────────────────────────────────────────────────┐
│  Backtest Engine                                             │
│  ├── Entry Strategy Interface                               │
│  └── Exit Strategy Interface                                │
└─────────────────────────────────────────────────────────────┘
                    ↓                      ↓
        ┌───────────────────┐    ┌──────────────────┐
        │  Entry Strategies  │    │  Exit Strategies  │
        └───────────────────┘    └──────────────────┘
                ↓                         ↓
    ┌──────────────────────┐   ┌──────────────────────┐
    │ 1. ScorerStrategy    │   │ 1. ATRExiter         │
    │    - Simple          │   │    - 4层退出逻辑      │
    │    - Enhanced        │   │                      │
    │ 2. MACDCrossover     │   │ 2. LayeredExiter     │
    │ 3. Breakout          │   │    - 6层退出逻辑      │
    │ 4. ...更多策略       │   │ 3. ...更多策略       │
    └──────────────────────┘   └──────────────────────┘
                ↓
    ┌──────────────────────┐
    │  Score Utils         │
    │  (可选，仅被Scorer   │
    │   Strategy使用)      │
    └──────────────────────┘
```

---

## 📝 具体改造方案

### 1. Entry Strategy - 统一接口

```python
# src/analysis/strategies/base_strategy.py

@dataclass
class TradingSignal:
    """统一的交易信号"""
    action: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0.0-1.0
    reasons: List[str]
    metadata: Dict[str, Any]
    strategy_name: str

@dataclass
class MarketData:
    """封装市场数据"""
    ticker: str
    current_date: pd.Timestamp
    df_features: pd.DataFrame
    df_trades: pd.DataFrame
    df_financials: pd.DataFrame
    metadata: dict

class BaseStrategy(ABC):
    """Entry策略基类"""

    @abstractmethod
    def generate_signal(self, market_data: MarketData) -> TradingSignal:
        """生成买入信号"""
        pass
```

### 2. Score Utils - 独立工具函数

```python
# src/analysis/scoring_utils.py

def calculate_composite_score(
    df_features: pd.DataFrame,
    df_trades: pd.DataFrame,
    df_financials: pd.DataFrame,
    metadata: dict,
    weights: Dict[str, float]
) -> Tuple[float, Dict[str, float]]:
    """
    计算综合分数和各组件分数

    Returns:
        (total_score, breakdown)
        - total_score: 0-100综合分
        - breakdown: {"technical": 65, "institutional": 70, ...}
    """
    tech_score = calculate_technical_score(df_features)
    inst_score = calculate_institutional_score(df_trades, ...)
    fund_score = calculate_fundamental_score(df_financials)
    vol_score = calculate_volatility_score(df_features)

    total = (tech_score * weights["technical"] +
             inst_score * weights["institutional"] +
             fund_score * weights["fundamental"] +
             vol_score * weights["volatility"])

    breakdown = {
        "technical": tech_score,
        "institutional": inst_score,
        "fundamental": fund_score,
        "volatility": vol_score
    }

    return total, breakdown


def calculate_technical_score(df_features: pd.DataFrame) -> float:
    """纯函数：计算技术分数"""
    latest = df_features.iloc[-1]
    score = 50.0

    # 1. Trend Alignment
    if latest['Close'] > latest['EMA_20'] > latest['EMA_50'] > latest['EMA_200']:
        score += 20
    elif latest['Close'] > latest['EMA_200']:
        score += 10
    elif latest['Close'] < latest['EMA_200']:
        score -= 20

    # 2. RSI
    rsi = latest['RSI']
    if 40 <= rsi <= 65:
        score += 10
    elif rsi > 75:
        score -= 10
    elif rsi < 30:
        score += 5

    # 3. MACD
    if latest['MACD_Hist'] > 0:
        score += 10
        if latest['MACD'] > 0:
            score += 5

    return np.clip(score, 0, 100)

# ... 其他calculate_xxx_score函数
```

### 3. Entry Strategies - 实现

#### 3.1 ScorerStrategy（包装旧 Scorer）

```python
# src/analysis/strategies/scorer_strategy.py

class SimpleScorerStrategy(BaseStrategy):
    """Simple打分策略"""

    def __init__(self, buy_threshold: float = 65.0):
        self.threshold = buy_threshold
        self.weights = {
            "technical": 0.4,
            "institutional": 0.3,
            "fundamental": 0.2,
            "volatility": 0.1
        }

    def generate_signal(self, market_data: MarketData) -> TradingSignal:
        from src.analysis.scoring_utils import calculate_composite_score

        score, breakdown = calculate_composite_score(
            market_data.df_features,
            market_data.df_trades,
            market_data.df_financials,
            market_data.metadata,
            self.weights
        )

        if score >= self.threshold:
            return TradingSignal(
                action="BUY",
                confidence=score / 100,
                reasons=[f"Composite score {score:.1f} >= {self.threshold}"],
                metadata={"score": score, "breakdown": breakdown},
                strategy_name="SimpleScorer"
            )

        return TradingSignal(
            action="HOLD",
            confidence=0.0,
            reasons=["Score below threshold"],
            metadata={"score": score},
            strategy_name="SimpleScorer"
        )


class EnhancedScorerStrategy(BaseStrategy):
    """Enhanced打分策略"""

    def __init__(self, buy_threshold: float = 65.0):
        self.threshold = buy_threshold
        self.weights = {
            "technical": 0.35,
            "institutional": 0.35,  # 增强版更重视机构
            "fundamental": 0.20,
            "volatility": 0.10
        }

    def generate_signal(self, market_data: MarketData) -> TradingSignal:
        # 与SimpleScorerStrategy类似，但权重不同
        ...
```

#### 3.2 MACDCrossoverStrategy（新策略）

```python
# src/analysis/strategies/macd_crossover.py

class MACDCrossoverStrategy(BaseStrategy):
    """MACD金叉策略"""

    def __init__(self,
                 confirm_with_volume: bool = True,
                 confirm_with_trend: bool = True):
        self.confirm_volume = confirm_with_volume
        self.confirm_trend = confirm_with_trend

    def generate_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features

        if len(df) < 2:
            return TradingSignal(action="HOLD", confidence=0.0,
                               reasons=["Insufficient data"],
                               strategy_name="MACDCrossover")

        # 检测MACD金叉
        macd_hist_prev = df.iloc[-2]['MACD_Hist']
        macd_hist_now = df.iloc[-1]['MACD_Hist']

        golden_cross = macd_hist_prev < 0 and macd_hist_now > 0

        if not golden_cross:
            return TradingSignal(action="HOLD", confidence=0.0,
                               reasons=["No MACD golden cross"],
                               strategy_name="MACDCrossover")

        # 确认条件
        reasons = ["MACD golden cross detected"]
        confidence = 0.7

        # 可选：成交量确认
        if self.confirm_volume:
            volume_now = df.iloc[-1]['Volume']
            volume_avg = df['Volume'].rolling(20).mean().iloc[-1]
            if volume_now > volume_avg * 1.2:
                reasons.append("Volume confirmation (+20%)")
                confidence += 0.1
            else:
                confidence -= 0.1

        # 可选：趋势确认
        if self.confirm_trend:
            price = df.iloc[-1]['Close']
            ema_200 = df.iloc[-1]['EMA_200']
            if price > ema_200:
                reasons.append("Above EMA200 (uptrend)")
                confidence += 0.1
            else:
                reasons.append("Below EMA200 (caution)")
                confidence -= 0.2

        confidence = np.clip(confidence, 0.0, 1.0)

        if confidence >= 0.6:
            return TradingSignal(
                action="BUY",
                confidence=confidence,
                reasons=reasons,
                metadata={
                    "macd_hist": macd_hist_now,
                    "volume_ratio": volume_now / volume_avg if self.confirm_volume else None
                },
                strategy_name="MACDCrossover"
            )

        return TradingSignal(action="HOLD", confidence=confidence,
                           reasons=reasons, strategy_name="MACDCrossover")
```

### 4. Exit Strategies - 重构解耦

#### 4.1 ATRExiter - 移除 Score 依赖

**原 P3 规则：** `if score < 50: SELL`

**改为技术条件：**

```python
# src/analysis/exiters/atr_exiter.py

class ATRExiter(BaseExiter):
    """ATR退出策略 - 完全基于技术指标"""

    def __init__(self,
                 atr_stop_multiplier: float = 2.0,
                 atr_trail_multiplier: float = 3.0,
                 rsi_overbought: float = 70.0):
        # ❌ 移除 score_threshold 参数
        super().__init__(strategy_name="ATR_Exit_v2")
        self.stop_mult = atr_stop_multiplier
        self.trail_mult = atr_trail_multiplier
        self.rsi_overbought = rsi_overbought

    def evaluate_exit(self,
                     position: Position,
                     df_features: pd.DataFrame,
                     df_trades: pd.DataFrame,
                     df_financials: pd.DataFrame,
                     metadata: dict) -> ExitSignal:  # ❌ 移除current_score参数
        """
        4层退出逻辑 - 完全基于市场数据
        """
        latest = self._get_latest_data(df_features)
        current_price = latest['Close']
        current_atr = latest['ATR']
        current_rsi = latest['RSI']
        ema_20 = latest['EMA_20']
        ema_200 = latest['EMA_200']
        current_date = df_features.index[-1]

        peak_price = position.peak_price_since_entry
        if peak_price is None or current_price > peak_price:
            peak_price = current_price

        # P0: Hard Stop Loss (不变)
        stop_loss_level = position.entry_price - (current_atr * self.stop_mult)
        if current_price < stop_loss_level:
            return self._create_signal(..., reason="Hard stop hit", ...)

        # P1: Trailing Stop (不变)
        trailing_stop_level = peak_price - (current_atr * self.trail_mult)
        if current_price < trailing_stop_level:
            return self._create_signal(..., reason="Trailing stop hit", ...)

        # P2: Momentum Exhaustion (不变)
        if current_rsi > self.rsi_overbought and current_price < ema_20:
            return self._create_signal(..., reason="Momentum exhaustion", ...)

        # P3: Trend Breakdown (替代Score Decay)
        # 原来: if score < 50: SELL
        # 现在: 基于技术条件判断趋势破坏
        trend_broken = self._check_trend_breakdown(latest, df_features)
        if trend_broken:
            return self._create_signal(
                position, current_price, current_date,
                action="SELL_100%",
                urgency="HIGH",
                reason=f"Trend breakdown: {trend_broken}",
                triggered_by="P3_TrendBreakdown"
            )

        return self._create_signal(..., action="HOLD", ...)

    def _check_trend_breakdown(self, latest: pd.Series, df_features: pd.DataFrame) -> Optional[str]:
        """
        替代Score Decay的技术条件

        检测趋势破坏的多个信号：
        1. 价格跌破EMA200（长期趋势破坏）
        2. MACD死叉
        3. RSI持续弱势（<40）
        4. 成交量萎缩且价格下跌
        """
        reasons = []

        # 1. 跌破EMA200
        if latest['Close'] < latest['EMA_200']:
            # 确认不是假突破
            if len(df_features) >= 3:
                closes_below = (df_features['Close'].tail(3) < df_features['EMA_200'].tail(3)).sum()
                if closes_below >= 2:  # 3天内至少2天在下方
                    reasons.append("Below EMA200")

        # 2. MACD死叉
        if len(df_features) >= 2:
            macd_hist_prev = df_features.iloc[-2]['MACD_Hist']
            macd_hist_now = latest['MACD_Hist']
            if macd_hist_prev > 0 and macd_hist_now < 0:
                reasons.append("MACD death cross")

        # 3. RSI持续弱势
        if latest['RSI'] < 40:
            if len(df_features) >= 5:
                rsi_weak = (df_features['RSI'].tail(5) < 45).sum()
                if rsi_weak >= 4:  # 5天内4天低于45
                    reasons.append("Persistent RSI weakness")

        # 4. 成交量萎缩 + 价格下跌
        if len(df_features) >= 20:
            volume_avg = df_features['Volume'].tail(20).mean()
            if latest['Volume'] < volume_avg * 0.7:  # 成交量低于均值30%
                price_change_5d = (latest['Close'] / df_features.iloc[-6]['Close'] - 1) * 100
                if price_change_5d < -3:  # 5天跌超3%
                    reasons.append("Volume dry-up with price decline")

        # 需要至少2个信号才确认趋势破坏
        if len(reasons) >= 2:
            return " AND ".join(reasons)

        return None
```

#### 4.2 LayeredExiter - 移除 Score 依赖

```python
# src/analysis/exiters/layered_exiter.py

class LayeredExiter(BaseExiter):
    """6层退出策略 - 完全基于市场数据"""

    def __init__(self, ...):
        # ❌ 移除所有score相关参数
        # score_exit_buffer_buy, score_exit_buffer_strong
        # institutional_floor, fundamental_floor, technical_floor
        ...

    def evaluate_exit(self,
                     position: Position,
                     df_features: pd.DataFrame,
                     df_trades: pd.DataFrame,
                     df_financials: pd.DataFrame,
                     metadata: dict) -> ExitSignal:  # ❌ 移除current_score参数
        """6层退出逻辑"""

        # Layer 1: Emergency (不变 - 基于财报和机构流向)
        emergency = self._check_emergency(...)
        if emergency:
            return ...

        # Layer 2: 趋势恶化 (替代Score-Based)
        # 原来: if score < entry_score - buffer: SELL
        # 现在: 检测技术/基本面/机构流向恶化
        deterioration = self._check_market_deterioration(
            position, df_features, df_trades, df_financials
        )
        if deterioration:
            return self._create_signal(..., reason=deterioration, ...)

        # Layer 3: 改为"多维度弱化"
        # 原来: if tech_score < 30 or inst_score < 25: SELL
        # 现在: 直接检测技术指标和机构行为
        weakness = self._check_multi_dimensional_weakness(
            df_features, df_trades, df_financials
        )
        if weakness:
            return self._create_signal(..., reason=weakness, ...)

        # Layer 4-6: 保持不变（本就不依赖score）
        ...

    def _check_market_deterioration(self, position, df_features, df_trades, df_financials) -> Optional[str]:
        """
        检测市场恶化（替代Layer 2的Score-Based）

        对比入场时和当前的市场状态
        """
        entry_date = position.entry_date
        current_date = df_features.index[-1]

        # 获取入场时的市场状态
        entry_data = df_features[df_features.index <= entry_date].iloc[-1] if len(df_features[df_features.index <= entry_date]) > 0 else None
        current_data = df_features.iloc[-1]

        if entry_data is None:
            return None

        deteriorations = []

        # 1. 趋势恶化：从上升趋势变为下降趋势
        entry_trend = entry_data['Close'] > entry_data['EMA_200']
        current_trend = current_data['Close'] > current_data['EMA_200']
        if entry_trend and not current_trend:
            deteriorations.append("Trend reversed (above→below EMA200)")

        # 2. 动量恶化：MACD从正转负
        entry_macd = entry_data['MACD_Hist'] > 0
        current_macd = current_data['MACD_Hist'] < 0
        if entry_macd and current_macd:
            deteriorations.append("Momentum lost (MACD+→MACD-)")

        # 3. 机构流向恶化
        if not df_trades.empty:
            df_trades_copy = df_trades.copy()
            df_trades_copy['EnDate'] = pd.to_datetime(df_trades_copy['EnDate'])

            # 入场时1个月的机构流向
            entry_month_start = entry_date - timedelta(days=30)
            entry_month_trades = df_trades_copy[
                (df_trades_copy['EnDate'] > entry_month_start) &
                (df_trades_copy['EnDate'] <= entry_date)
            ]

            # 当前1个月的机构流向
            current_month_start = current_date - timedelta(days=30)
            current_month_trades = df_trades_copy[
                (df_trades_copy['EnDate'] > current_month_start) &
                (df_trades_copy['EnDate'] <= current_date)
            ]

            if not entry_month_trades.empty and not current_month_trades.empty:
                entry_foreign = entry_month_trades['FrgnBal'].sum()
                current_foreign = current_month_trades['FrgnBal'].sum()

                # 从买入变为卖出
                if entry_foreign > 0 and current_foreign < -50_000_000:  # 外资从买变为大举卖出
                    deteriorations.append(f"Foreign reversal (¥{current_foreign/1e6:.0f}M)")

        if len(deteriorations) >= 2:  # 至少2个维度恶化
            return "Market deterioration: " + " AND ".join(deteriorations)

        return None

    def _check_multi_dimensional_weakness(self, df_features, df_trades, df_financials) -> Optional[str]:
        """
        检测多维度弱化（替代Layer 3的Component Breakdown）
        """
        latest = df_features.iloc[-1]
        weaknesses = []

        # 1. 技术面弱化
        tech_weak = (
            latest['RSI'] < 30 or  # 超卖
            (latest['Close'] < latest['EMA_20'] and
             latest['Close'] < latest['EMA_50'])  # 跌破短中期均线
        )
        if tech_weak:
            weaknesses.append("Technical weakness")

        # 2. 机构流向弱化
        if not df_trades.empty:
            df_trades_copy = df_trades.copy()
            df_trades_copy['EnDate'] = pd.to_datetime(df_trades_copy['EnDate'])
            recent = df_trades_copy.tail(10)  # 最近10天
            if not recent.empty and 'FrgnBal' in recent.columns:
                net_foreign = recent['FrgnBal'].sum()
                if net_foreign < -30_000_000:  # 外资净卖出超30M
                    weaknesses.append("Institutional selling")

        # 3. 基本面弱化（财报恶化）
        if not df_financials.empty and len(df_financials) >= 2:
            df_fins = df_financials.sort_values('DiscDate')
            if len(df_fins) >= 2:
                latest_fin = df_fins.iloc[-1]
                prev_fin = df_fins.iloc[-2]

                # 利润下滑
                latest_op = pd.to_numeric(latest_fin.get('OperatingProfit', 0), errors='coerce')
                prev_op = pd.to_numeric(prev_fin.get('OperatingProfit', 0), errors='coerce')

                if pd.notna(latest_op) and pd.notna(prev_op) and prev_op > 0:
                    if latest_op < prev_op * 0.9:  # 利润下滑超10%
                        weaknesses.append("Profit decline")

        if len(weaknesses) >= 2:
            return "Multi-dimensional weakness: " + " + ".join(weaknesses)

        return None
```

### 5. 回测引擎 - 统一接口

```python
# src/backtest/engine.py

class BacktestEngine:
    def backtest_strategy(
        self,
        ticker: str,
        entry_strategy,  # BaseStrategy 或 BaseScorer (向后兼容)
        exit_strategy: BaseExiter,
        start_date: str = "2021-01-01",
        end_date: str = "2026-01-08"
    ) -> BacktestResult:
        """
        统一回测接口
        支持新Strategy和旧Scorer
        """
        # 加载数据
        df_features, df_trades, df_financials, metadata = self._load_data(ticker)

        # ... 日期过滤 ...

        # 模拟循环
        for current_date in trading_days:
            df_features_historical = df_features[df_features.index <= current_date]
            # ...

            if position is None:
                # === 买入逻辑 ===

                # 检测是新Strategy还是旧Scorer
                if isinstance(entry_strategy, BaseStrategy):
                    # 新Strategy接口
                    market_data = MarketData(
                        ticker=ticker,
                        current_date=current_date,
                        df_features=df_features_historical,
                        df_trades=df_trades_historical,
                        df_financials=df_financials_historical,
                        metadata=metadata
                    )
                    signal = entry_strategy.generate_signal(market_data)

                    if signal.action == "BUY":
                        pending_buy_signal = True
                        pending_buy_score = signal.confidence * 100
                        logger.info(f"BUY SIGNAL: {signal.reasons}")

                else:
                    # 旧Scorer接口（向后兼容）
                    score_result = entry_strategy.evaluate(
                        ticker,
                        df_features_historical,
                        df_trades_historical,
                        df_financials_historical,
                        metadata
                    )

                    if score_result.total_score >= self.buy_threshold:
                        pending_buy_signal = True
                        pending_buy_score = score_result.total_score

            else:
                # === 卖出逻辑 ===
                position.peak_price_since_entry = max(
                    position.peak_price_since_entry, current_close
                )

                # ✅ Exiter不再需要current_score参数
                exit_signal = exit_strategy.evaluate_exit(
                    position,
                    df_features_historical,
                    df_trades_historical,
                    df_financials_historical,
                    metadata
                )

                if exit_signal.action != "HOLD":
                    pending_sell_signal = exit_signal

            # ... 执行pending orders ...
```

---

## 📊 策略组合矩阵

重构后支持的组合（3x2=6 种）：

| Entry Strategy         | Exit Strategy | 说明                 |
| ---------------------- | ------------- | -------------------- |
| SimpleScorerStrategy   | ATRExiter     | ✅ 基础组合          |
| SimpleScorerStrategy   | LayeredExiter | ✅ 简单入场+复杂退出 |
| EnhancedScorerStrategy | ATRExiter     | ✅ 增强入场+简单退出 |
| EnhancedScorerStrategy | LayeredExiter | ✅ 全面组合          |
| MACDCrossoverStrategy  | ATRExiter     | ✅ 技术入场+技术退出 |
| MACDCrossoverStrategy  | LayeredExiter | ✅ 技术入场+全面退出 |

**未来可轻松扩展：**

- BreakoutStrategy + ATRExiter
- RSIDivergenceStrategy + LayeredExiter
- CompositeStrategy(MACD + Breakout) + CustomExiter
- ...

---

## 🎯 实施步骤

### Step 1: 提取 Score Utils (30 分钟)

**文件：** `src/analysis/scoring_utils.py`

- 从 SimpleScorer/EnhancedScorer 提取纯函数
- `calculate_technical_score()`
- `calculate_institutional_score()`
- `calculate_fundamental_score()`
- `calculate_volatility_score()`
- `calculate_composite_score()`

### Step 2: 创建 Strategy 基础 (20 分钟)

**文件：**

- `src/analysis/strategies/__init__.py`
- `src/analysis/strategies/base_strategy.py` - TradingSignal, MarketData, BaseStrategy

### Step 3: 实现 Entry Strategies (30 分钟)

**文件：**

- `src/analysis/strategies/scorer_strategy.py` - SimpleScorerStrategy, EnhancedScorerStrategy
- `src/analysis/strategies/macd_crossover.py` - MACDCrossoverStrategy

### Step 4: 重构 Exiters (40 分钟)

**修改：**

- `src/analysis/exiters/base_exiter.py` - 移除 current_score 参数
- `src/analysis/exiters/atr_exiter.py` - P3 改为\_check_trend_breakdown()
- `src/analysis/exiters/layered_exiter.py` - Layer 2/3 改为市场恶化检测

### Step 5: 修改回测引擎 (30 分钟)

**修改：**

- `src/backtest/engine.py` - 支持 BaseStrategy 和 BaseScorer 双接口

### Step 6: 更新配置和测试 (20 分钟)

**修改：**

- `start_backtest.py` - 支持新策略
- `backtest_config.json` - 添加 MACD 配置
- 运行测试验证 3 个策略

**总时间：2.5-3 小时**

---

## ✅ 重构后的优势

### 1. 完全解耦

- Entry 和 Exit 独立，互不依赖
- Score Utils 变为可选工具
- 任意组合策略

### 2. 职责清晰

- Entry Strategy: 只生成买入信号
- Exit Strategy: 只生成卖出信号
- Score Utils: 只计算分数（工具）

### 3. 易于扩展

- 添加新 Entry 策略：30 分钟
- 添加新 Exit 策略：30 分钟
- 不影响现有代码

### 4. 向后兼容

- 旧 Scorer 通过适配器继续工作
- 回测引擎支持双接口
- 现有回测结果可对比

### 5. 更符合实战

- Exit 不再依赖抽象的"分数"
- 基于具体技术指标和市场行为
- 更容易理解和调试

---

## 🚀 下一步

确认后立即开始实施：

1. ✅ 确认架构设计
2. ✅ 确认 ATRExiter 的 P3 改造（趋势破坏检测）
3. ✅ 确认 LayeredExiter 的 Layer 2/3 改造
4. 🚀 开始编码实施

**准备好开始了吗？**
