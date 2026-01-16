# 策略架构重构分析与方案

## 📊 当前问题诊断

### 1. 性能表现差劲

根据最近的回测结果：

- **SimpleScorer + ATRExiter**: -99.95% (vs TOPIX +86.82%)
- **EnhancedScorer + ATRExiter**: +17.38% (vs TOPIX +86.82%)
- **所有策略的 Alpha 均为负值**: -186% 到 -69%
- **Information Ratio 全部为负**: -9.5 到 -3.5

### 2. 架构限制分析

#### 🔴 **Scorer 的局限性**

当前设计：`scorer.evaluate() → ScoreResult(total_score: 0-100)`

**问题：**

1. **过度简化**: 强制将所有买入逻辑压缩成 0-100 分数
2. **缺乏灵活性**: 无法表达"条件组合"（例如：RSI<30 AND MACD 金叉 AND 成交量突破）
3. **难以扩展**:
   - 无法实现"突破策略"（价格突破某个关键位）
   - 无法实现"形态识别"（双底、头肩顶等）
   - 无法实现"事件驱动"（财报后首日、分红前等）
4. **信息丢失**: 只返回一个分数，丢失了触发原因、置信度等关键信息

**示例：当前无法轻松实现**

```python
# ❌ 难以实现：突破策略
if price > resistance_level and volume > avg_volume * 1.5:
    buy_signal = True

# ❌ 难以实现：组合条件
if (MACD_crossover and RSI_divergence) or (earnings_beat and institutional_accumulation):
    buy_signal = True
```

#### 🟡 **Exiter 相对较好**

当前设计：`exiter.evaluate_exit() → ExitSignal(action, urgency, reason)`

**优点：**

- 已经是策略化的（不是打分）
- 支持多种退出条件（硬止损、追踪止损、技术退出等）
- 返回详细信息（action, urgency, reason）

**问题：**

- 只能"被动响应"（持仓后才能调用）
- 无法实现主动卖出信号（如：做空信号、反转信号）

---

## 🎯 重构目标

### 核心理念转变

```
旧模式: Scorer打分(0-100) → 超过阈值买入
新模式: Strategy生成信号(BUY/SELL/HOLD) → 直接执行
```

### 设计原则

1. ✅ **保持向后兼容**: 现有 SimpleScorer、EnhancedScorer 必须能继续工作
2. ✅ **策略化而非打分化**: 策略应该生成明确的"买入/卖出/持有"信号
3. ✅ **可组合性**: 支持策略组合（AND/OR 逻辑）
4. ✅ **信息透明**: 返回触发原因、置信度、风险提示
5. ✅ **易于扩展**: 新策略类型应该很容易添加

---

## 🏗️ 重构方案

### 方案 A: 渐进式重构（推荐）

**阶段 1: 引入新的信号抽象层**

```python
@dataclass
class TradingSignal:
    """统一的交易信号"""
    action: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0.0-1.0 置信度
    reasons: List[str]  # 触发原因列表
    metadata: Dict[str, Any]  # 额外信息（价格、指标值等）
    strategy_name: str

class BaseStrategy(ABC):
    """新的基础策略类"""
    @abstractmethod
    def generate_signal(self, market_data: MarketData) -> TradingSignal:
        """生成交易信号"""
        pass
```

**阶段 2: 包装现有 Scorer 为 Strategy**

```python
class ScorerAdapter(BaseStrategy):
    """适配器：将旧Scorer包装成新Strategy"""
    def __init__(self, scorer: BaseScorer, threshold: float = 65.0):
        self.scorer = scorer
        self.threshold = threshold

    def generate_signal(self, market_data: MarketData) -> TradingSignal:
        score_result = self.scorer.evaluate(...)

        if score_result.total_score >= self.threshold:
            return TradingSignal(
                action="BUY",
                confidence=score_result.total_score / 100,
                reasons=[f"Score {score_result.total_score:.1f} >= {self.threshold}"],
                metadata={"score_breakdown": score_result.breakdown},
                strategy_name=self.scorer.strategy_name
            )
        else:
            return TradingSignal(action="HOLD", confidence=0.0, ...)
```

**阶段 3: 创建新的策略类型**

```python
class BreakoutStrategy(BaseStrategy):
    """突破策略"""
    def generate_signal(self, market_data: MarketData) -> TradingSignal:
        if market_data.price > market_data.resistance and \
           market_data.volume > market_data.avg_volume * 1.5:
            return TradingSignal(
                action="BUY",
                confidence=0.8,
                reasons=["Price breakout", "Volume confirmation"],
                metadata={"breakout_level": market_data.resistance},
                strategy_name="Breakout"
            )
        return TradingSignal(action="HOLD", ...)

class MACDCrossoverStrategy(BaseStrategy):
    """MACD金叉策略"""
    def generate_signal(self, market_data: MarketData) -> TradingSignal:
        if market_data.macd_crossover_today():
            return TradingSignal(
                action="BUY",
                confidence=0.7,
                reasons=["MACD golden cross"],
                ...
            )
        return TradingSignal(action="HOLD", ...)
```

**阶段 4: 组合策略**

```python
class CompositeStrategy(BaseStrategy):
    """组合策略：支持AND/OR逻辑"""
    def __init__(self, strategies: List[BaseStrategy], logic: str = "OR"):
        self.strategies = strategies
        self.logic = logic  # "AND" or "OR"

    def generate_signal(self, market_data: MarketData) -> TradingSignal:
        signals = [s.generate_signal(market_data) for s in self.strategies]

        if self.logic == "AND":
            # 所有策略都必须发出买入信号
            if all(s.action == "BUY" for s in signals):
                return TradingSignal(
                    action="BUY",
                    confidence=min(s.confidence for s in signals),
                    reasons=[r for s in signals for r in s.reasons],
                    strategy_name="Composite_AND"
                )
        elif self.logic == "OR":
            # 任一策略发出买入信号即可
            buy_signals = [s for s in signals if s.action == "BUY"]
            if buy_signals:
                best = max(buy_signals, key=lambda s: s.confidence)
                return best

        return TradingSignal(action="HOLD", ...)
```

---

### 方案 B: 激进式重构（不推荐）

直接废弃 Scorer，全部重写为 Strategy。

**缺点：**

- ❌ 破坏现有代码
- ❌ 回测历史无法对比
- ❌ 工作量巨大

---

## 📋 实施计划（推荐方案 A）

### Phase 1: 基础架构（1-2 天）

**文件结构：**

```
src/analysis/
  strategies/              # 新目录
    __init__.py
    base_strategy.py       # BaseStrategy, TradingSignal
    adapters.py            # ScorerAdapter, ExiterAdapter

  scorers/                 # 保留，标记为legacy
    (现有文件不变)

  exiters/                 # 保留，集成到strategy
    (现有文件不变)
```

**核心类：**

1. `TradingSignal` - 统一信号格式
2. `MarketData` - 封装市场数据
3. `BaseStrategy` - 新策略基类
4. `ScorerAdapter` - 兼容旧 Scorer

### Phase 2: 新策略实现（2-3 天）

实现 3-5 个常见策略类型：

1. **BreakoutStrategy** - 突破策略
2. **MACDCrossoverStrategy** - MACD 金叉/死叉
3. **RSIDivergenceStrategy** - RSI 背离
4. **MeanReversionStrategy** - 均值回归
5. **CompositeStrategy** - 组合策略

### Phase 3: 回测引擎集成（1 天）

修改 `engine.py`：

```python
# 旧接口（保留）
def backtest_strategy(ticker, scorer, exiter, ...):
    ...

# 新接口
def backtest_strategy_v2(ticker, entry_strategy, exit_strategy, ...):
    ...
    signal = entry_strategy.generate_signal(market_data)
    if signal.action == "BUY":
        execute_buy()
    ...
```

### Phase 4: 测试与优化（2-3 天）

1. 单元测试所有新策略
2. 对比新旧策略的回测结果
3. 性能优化（缓存、向量化）
4. 文档编写

---

## 🎨 新 API 使用示例

### 示例 1: 使用旧 Scorer（向后兼容）

```python
from src.analysis.scorers import SimpleScorer
from src.analysis.strategies.adapters import ScorerAdapter

# 包装旧Scorer
scorer = SimpleScorer()
strategy = ScorerAdapter(scorer, threshold=65.0)

# 回测
results = backtest_strategy_v2(
    ticker='7203',
    entry_strategy=strategy,
    exit_strategy=ATRExiter()
)
```

### 示例 2: 使用新策略

```python
from src.analysis.strategies import MACDCrossoverStrategy, BreakoutStrategy

# 单一策略
macd_strategy = MACDCrossoverStrategy()

# 组合策略 (MACD金叉 AND 突破)
combo = CompositeStrategy(
    strategies=[
        MACDCrossoverStrategy(),
        BreakoutStrategy(resistance_window=20)
    ],
    logic="AND"
)

results = backtest_strategy_v2('7203', combo, ATRExiter())
```

### 示例 3: 高级组合

```python
# 多重信号组合
smart_entry = CompositeStrategy([
    ScorerAdapter(EnhancedScorer(), threshold=70),  # 基本面好
    MACDCrossoverStrategy(),                        # 技术信号
    BreakoutStrategy()                              # 突破确认
], logic="AND")  # 三个条件都满足才买入

# 智能退出
smart_exit = CompositeStrategy([
    ATRExiter(),                                    # 止损保护
    RSIDivergenceStrategy(direction="bearish"),    # 顶背离
    MACDCrossoverStrategy(direction="death")       # MACD死叉
], logic="OR")  # 任一条件满足就卖出
```

---

## 🔧 技术实现细节

### 1. MarketData 封装

```python
@dataclass
class MarketData:
    """封装回测所需的所有市场数据"""
    ticker: str
    current_date: pd.Timestamp
    df_features: pd.DataFrame      # 技术指标
    df_trades: pd.DataFrame        # 机构交易
    df_financials: pd.DataFrame    # 财务数据
    metadata: dict                 # 元数据

    # 便捷属性
    @property
    def latest_price(self) -> float:
        return self.df_features.iloc[-1]['Close']

    @property
    def latest_rsi(self) -> float:
        return self.df_features.iloc[-1]['RSI']

    def macd_crossover_today(self) -> bool:
        """检测MACD金叉"""
        if len(self.df_features) < 2:
            return False
        hist = self.df_features['MACD_Hist'].values
        return hist[-2] < 0 and hist[-1] > 0

    def price_above_resistance(self, window: int = 20) -> bool:
        """检测价格突破阻力位"""
        resistance = self.df_features['High'].rolling(window).max().iloc[-2]
        return self.latest_price > resistance
```

### 2. 策略注册系统

```python
class StrategyRegistry:
    """策略注册中心，便于配置文件使用"""
    _strategies = {}

    @classmethod
    def register(cls, name: str, strategy_class):
        cls._strategies[name] = strategy_class

    @classmethod
    def create(cls, name: str, **kwargs):
        if name not in cls._strategies:
            raise ValueError(f"Unknown strategy: {name}")
        return cls._strategies[name](**kwargs)

# 使用
StrategyRegistry.register("macd_cross", MACDCrossoverStrategy)
StrategyRegistry.register("breakout", BreakoutStrategy)

# 从配置文件创建
strategy = StrategyRegistry.create("macd_cross", fast=12, slow=26)
```

### 3. 配置文件格式

```json
{
  "strategies": {
    "entry": {
      "type": "composite",
      "logic": "AND",
      "components": [
        {
          "type": "scorer_adapter",
          "scorer": "EnhancedScorer",
          "threshold": 70
        },
        {
          "type": "macd_crossover",
          "fast_period": 12,
          "slow_period": 26
        }
      ]
    },
    "exit": {
      "type": "atr_exiter",
      "stop_multiplier": 2.0,
      "trail_multiplier": 3.0
    }
  }
}
```

---

## 📊 预期改进

### 策略多样性

- ✅ 现在：2 种 scorer（Simple, Enhanced）
- 🎯 目标：10+种策略类型，无限组合

### 性能提升

- 📈 通过精确的条件组合，减少假信号
- 📈 通过多策略验证，提高胜率
- 📈 组合示例：MACD 金叉 + 价格突破 + 机构买入 → 胜率可能从 40%提升到 60%

### 开发效率

- ⚡ 新策略开发时间：从 2 小时降低到 30 分钟
- ⚡ 策略测试：组合替换即可，无需重写
- ⚡ 代码复用：策略模块化，可在不同 ticker 间共享

---

## ⚠️ 风险与注意事项

### 1. 过度拟合风险

- ⚠️ 组合太多条件可能导致过拟合
- ✅ 解决：始终在样本外数据测试，使用 walk-forward 分析

### 2. 性能开销

- ⚠️ 组合策略可能增加计算时间
- ✅ 解决：缓存指标计算结果，使用向量化

### 3. 维护成本

- ⚠️ 策略数量增加，维护复杂度上升
- ✅ 解决：严格单元测试，清晰的文档，策略版本管理

---

## 🎯 下一步行动

### 立即可做（推荐优先级）

1. **创建基础架构** (2 小时)

   - `base_strategy.py` - 定义 TradingSignal 和 BaseStrategy
   - `adapters.py` - ScorerAdapter 包装现有 Scorer

2. **实现 1-2 个新策略** (3 小时)

   - MACDCrossoverStrategy
   - BreakoutStrategy

3. **集成到回测引擎** (2 小时)

   - 添加`backtest_strategy_v2()`
   - 保持旧接口不变

4. **测试验证** (2 小时)
   - 对比新旧策略回测结果
   - 确保向后兼容性

**总时间估算：1-2 天**

---

## 💡 总结

当前架构的核心问题是**过度简化**：将复杂的买入逻辑强制压缩成 0-100 分数。

推荐采用**渐进式重构（方案 A）**：

- ✅ 保持向后兼容
- ✅ 引入信号抽象层
- ✅ 支持策略组合
- ✅ 易于扩展

这将使策略开发从"调整权重打分"转变为"组合逻辑条件"，更符合实战交易思维。

**是否开始实施？请确认：**

1. 是否同意采用方案 A（渐进式重构）？
2. 优先实现哪些策略类型？
3. 是否需要我立即开始编写代码？
