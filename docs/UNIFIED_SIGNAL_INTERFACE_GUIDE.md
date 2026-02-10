# 信号生成统一接口 - 最佳实践指南

## 问题说明

之前代码中存在3种不同的信号生成方式：

1. `src/signal_generator.py` - CLI 使用的信号生成
2. `backtest/engine.py` - 直接调用 strategy 方法
3. `production/signal_generator.py` - 生产环境信号生成

结果导致：

- 重复的信号生成逻辑
- 难以维护（修改逻辑需要改3个地方）
- 不一致的返回值类型

---

## 新的统一接口：`generate_signal_v2()`

### 位置

`src/signal_generator.py::generate_signal_v2()`

### 签名

```python
def generate_signal_v2(
    market_data: MarketData,
    entry_strategy,                    # 策略实例或类
    exit_strategy=None,                # 可选
    position: Position = None,         # 如果提供，生成退出信号
    entry_params: dict = None,
    exit_params: dict = None
) -> TradingSignal:
    """返回统一的 TradingSignal 对象"""
```

### 返回值

总是返回单个 `TradingSignal` 对象：

```python
@dataclass
class TradingSignal:
    action: SignalAction           # BUY / SELL_X% / HOLD
    confidence: float              # 0-1
    reasons: List[str]             # 信号原因
    metadata: Dict                 # 额外信息（分数、触发条件等）
    strategy_name: str             # "SimpleScorerStrategy" 等
```

### 使用方式

#### 模式1：入场信号（无持仓）

```python
from src.data.market_data_builder import MarketDataBuilder
from src.signal_generator import generate_signal_v2
from src.analysis.strategies.entry import SimpleScorerStrategy

# 构建 MarketData
market_data = MarketDataBuilder.build_from_manager(
    data_manager=data_manager,
    ticker="8035",
    current_date=pd.Timestamp("2026-01-15")
)

# 生成入场信号
entry_strategy = SimpleScorerStrategy()
signal = generate_signal_v2(
    market_data=market_data,
    entry_strategy=entry_strategy
)

if signal.action == SignalAction.BUY:
    print(f"✅ 买入信号: {signal.reasons[0]}")
    print(f"   策略: {signal.strategy_name}")
```

#### 模式2：退出信号（有持仓）

```python
from src.analysis.strategies.exit import ATRExitStrategy

# 创建持仓对象
position = Position(
    ticker="8035",
    entry_price=31000,
    entry_date=pd.Timestamp("2026-01-01"),
    quantity=100,
    entry_signal=None,
    peak_price_since_entry=32000
)

# 生成退出信号
exit_strategy = ATRExitStrategy()
signal = generate_signal_v2(
    market_data=market_data,
    entry_strategy=None,  # 不需要
    exit_strategy=exit_strategy,
    position=position
)

if signal.action.startswith("SELL"):
    print(f"⚠️  卖出信号: {signal.reasons[0]}")
```

---

## 与现有代码的兼容性

### `generate_signal_v2()` 支持两种后向兼容模式：

#### 1. 新的策略接口（推荐）

```python
class MyEntryStrategy(BaseEntryStrategy):
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        # 返回 TradingSignal 对象
        pass
```

#### 2. 旧的 Scorer 接口（向后兼容）

```python
class MyScorer(BaseScorer):
    def evaluate(self, ticker, df_features, df_trades, df_financials, metadata) -> ScoreResult:
        # 返回 ScoreResult 对象
        pass
```

`generate_signal_v2()` 会自动处理转换。

---

## 迁移指南

### For Backtest Engine

**现状**：直接调用 `entry_strategy.generate_entry_signal()`

**推荐**：使用 `generate_signal_v2()`

```python
# 之前（现有代码，仍然有效）
signal = entry_strategy.generate_entry_signal(market_data)

# 之后（新的统一方式）
from src.signal_generator import generate_signal_v2
signal = generate_signal_v2(
    market_data=market_data,
    entry_strategy=entry_strategy,
    exit_strategy=exit_strategy,
    position=position  # 如果有持仓，自动生成退出信号
)
```

**优势**：

- 单一入口点处理入场/退场逻辑
- 向后兼容旧的 Scorer 接口
- 未来修改逻辑只需改 signal_generator.py

### For Production Signal Generator

**现状**：直接调用 `strategy.generate_entry_signal()`

**改进**：

```python
from src.signal_generator import generate_signal_v2

# 替代现有的直接调用
signal = generate_signal_v2(
    market_data=market_data,
    entry_strategy=entry_strategy,
    exit_strategy=exit_strategy,
    position=position if self.is_holding(ticker) else None
)
```

---

## 设计原则

### 为什么是 `generate_signal_v2()` 而不是改 `generate_trading_signal()`？

1. **向后兼容**：CLI 的 `generate_trading_signal()` 返回 dict，现有脚本依赖它
2. **命名清晰**：`_v2` 表示这是新接口，明确指出它是替代品
3. **平稳迁移**：现有代码继续工作，新代码逐步采用

### 为什么是 `TradingSignal` 而不是 dict？

1. **类型安全**：IDE 可以自动完成属性
2. **易于验证**：数据类自动验证字段
3. **一致性**：整个系统都用 TradingSignal

---

## 建议的实施计划

### 优先级

1. **立即**（已完成）
   - ✅ 创建 `generate_signal_v2()` 统一接口
   - ✅ 支持向后兼容旧 Scorer 接口

2. **下次迭代**（可选）
   - 更新 backtest/engine.py 使用 `generate_signal_v2()`
   - 更新 production/signal_generator.py 使用 `generate_signal_v2()`
   - 更新 comprehensive_evaluator.py 使用 `generate_signal_v2()`

3. **长期**（不急）
   - 弃用旧的 ScoreResult/Scorer 接口
   - 统一所有策略为新的 Strategy 接口

---

## 代码示例集合

### 示例1：Simple Backtest Loop

```python
from src.signal_generator import generate_signal_v2
from src.data.market_data_builder import MarketDataBuilder
from src.analysis.strategies.entry import SimpleScorerStrategy
from src.analysis.strategies.exit import ATRExitStrategy

entry_strategy = SimpleScorerStrategy()
exit_strategy = ATRExitStrategy()

for current_date in trading_dates:
    market_data = MarketDataBuilder.build_from_manager(
        data_manager, ticker, current_date
    )

    if position is None:
        # 生成入场信号
        signal = generate_signal_v2(market_data, entry_strategy)
        if signal.action == SignalAction.BUY:
            # 进入
    else:
        # 生成退出信号
        signal = generate_signal_v2(
            market_data, entry_strategy, exit_strategy, position
        )
        if signal.action.startswith("SELL"):
            # 退出
```

### 示例2：Production Signal Evaluation

```python
from src.signal_generator import generate_signal_v2

def evaluate_all_stocks(tickers, strategy_config):
    signals = {}
    for ticker in tickers:
        market_data = MarketDataBuilder.build_from_manager(
            self.data_manager, ticker, pd.Timestamp.now()
        )
        if market_data is None:
            continue

        # 统一生成信号（处理入场/退场）
        signal = generate_signal_v2(
            market_data=market_data,
            entry_strategy=entry_strategy,
            exit_strategy=exit_strategy,
            position=self.get_position(ticker)  # 如果有持仓
        )

        signals[ticker] = signal

    return signals
```

---

## FAQ

**Q: 我应该立即改造所有现有代码吗？**
A: 不必。新接口是**完全可选的**。现有的 backtest/portfolio 代码运行良好，没必要改。只是：

- 新的 scorer/exiter 应该使用新接口
- 新功能应该用新接口
- 逐步迁移，不要一次改太多

**Q: 如何处理 ScoreResult vs TradingSignal 的混用？**
A: `generate_signal_v2()` 自动转换 ScoreResult → TradingSignal，所以不用担心。

**Q: 为什么 backtest/engine.py 还在直接调用策略方法？**
A: 为了最小化改动。backtest 运行良好，改它有风险。如果想用新接口，可选采用。

**Q: 下个版本会强制使用新接口吗？**
A: 可能在 v1.0 时。现在是过渡期，建议新代码用新接口，旧代码保持不变。
