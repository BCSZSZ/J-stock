# 代码优化 - 快速参考

## 📋 三个优化的快速概览

### A. MarketDataBuilder 工具

**用途**：统一 MarketData 对象构建

**位置**：`src/data/market_data_builder.py`

**使用**：

```python
from src.data.market_data_builder import MarketDataBuilder

# 从 StockDataManager 加载
market_data = MarketDataBuilder.build_from_manager(
    data_manager, ticker, current_date
)

# 从已加载的 DataFrame
market_data = MarketDataBuilder.build_from_dataframes(
    ticker, current_date, df_features, df_trades, df_financials, metadata
)
```

**改进**：消除 6 个地方共 155 行重复代码

---

### B. generate_signal_v2() 接口

**用途**：统一 signal 生成（支持入场和退场）

**位置**：`src/signal_generator.py`

**使用**：

```python
from src.signal_generator import generate_signal_v2

# 入场信号
signal = generate_signal_v2(market_data, entry_strategy)

# 退场信号（自动检测）
signal = generate_signal_v2(
    market_data, entry_strategy, exit_strategy, position
)

# 信号属性
if signal.action == SignalAction.BUY:
    print(signal.reasons[0])
    print(signal.confidence)
```

**特点**：

- 总是返回 `TradingSignal`
- 自动处理入场/退场
- 向后兼容旧 Scorer

---

### C. create_strategy_instance() 工具

**用途**：统一 strategy 加载

**位置**：`src/utils/strategy_loader.py`

**使用**：

```python
from src.utils.strategy_loader import create_strategy_instance

# 加载任何策略
entry_strategy = create_strategy_instance("SimpleScorerStrategy", "entry")
exit_strategy = create_strategy_instance("ATRExitStrategy", "exit")
```

**优势**：

- 新增策略自动支持
- 不需改加载代码
- 已经集成到 production

---

## 🔧 如何在现有代码中使用

### 如果你在写新的 scorer/exiter

使用新的统一接口：

```python
from src.data.market_data_builder import MarketDataBuilder
from src.signal_generator import generate_signal_v2

market_data = MarketDataBuilder.build_from_manager(data_mgr, ticker, date)
signal = generate_signal_v2(market_data, my_strategy)
```

### 如果你在改 backtest/portfolio

**可选**：使用新接口获益，但现有代码也继续工作

```python
# 旧方式（仍然有效）
signal = entry_strategy.generate_entry_signal(market_data)

# 新方式（推荐，但可选）
from src.signal_generator import generate_signal_v2
signal = generate_signal_v2(market_data, entry_strategy)
```

### 如果你在改 production

现在已经用新接口了，继续就好。

---

## 📊 改进数据

| 方面            | 之前          | 之后                     | 改进    |
| --------------- | ------------- | ------------------------ | ------- |
| MarketData 构造 | 6 处重复      | 1 个工具                 | -155 行 |
| Signal 生成     | 3 处分散      | 1 个接口                 | 统一    |
| Strategy 加载   | 60 行 if-else | create_strategy_instance | -55 行  |
| 总代码行数      | 参考基线      | -90 行                   | 更清晰  |

---

## ✅ 验证清单

- [x] 所有语法检查通过
- [x] 向后兼容（旧代码继续工作）
- [x] 文档完整
- [x] 新工具可选使用

---

## 📖 详细文档

1. `docs/CODE_OPTIMIZATION_COMPLETION.md` - 完整改动说明
2. `docs/UNIFIED_SIGNAL_INTERFACE_GUIDE.md` - Signal 接口详细指南
3. `docs/CODE_DUPLICATION_ANALYSIS.md` - 原始问题分析
