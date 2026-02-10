# Phase 3 规划 - 信号生成与交易执行 (待实施)

## 概述

Phase 3 将实现生产交易系统的核心逻辑：

1. 调用 scorer 和 exiter 生成交易信号
2. 执行买入/卖出操作，更新投资组合状态
3. 生成每日信号文件供 UI/报告使用

---

## 文件结构

```
src/production/
├── __init__.py                      (已完成)
├── state_manager.py                 (已完成, 530+ 行)
├── signal_generator.py              (Phase 3 新增)
└── trade_executor.py                (Phase 3 新增)

signals_2026-01-21.json             (输出)
trade_history.json                   (追加更新)
```

---

## Phase 3 核心组件

### 1. SignalGenerator 类

**用途：** 根据当前市场数据调用策略评分，生成交易信号

**输入：**

```python
class SignalGenerator:
    def __init__(
        self,
        config: dict,           # 从 config.json 读取
        data_manager,           # StockDataManager 实例
        state: ProductionState  # Phase 2 状态
    ):
        pass

    def evaluate_all_groups(
        self,
        current_date: str,      # ISO format "YYYY-MM-DD"
        current_prices: Dict[str, float]
    ) -> Dict[str, List[Signal]]:
        """
        为所有策略组生成信号

        Returns:
            {
              "group_a": [Signal(...), Signal(...), ...],
              "group_b": [Signal(...), Signal(...), ...]
            }
        """
        pass
```

**Signal 数据结构：**

```python
@dataclass
class Signal:
    group_id: str
    ticker: str
    signal_type: str        # "BUY", "SELL", "HOLD", "EXIT"
    score: float            # 0-100
    confidence: float       # 0-1
    reason: str            # 用于报告
    suggested_action: str  # "BUY_100", "SELL_50%", "HOLD"

    # 对于 SELL 信号
    exit_reason: Optional[str] = None
    exit_urgency: Optional[str] = None
```

**逻辑流程：**

```
对于每个策略组:
  ├─ 获取组配置 (entry_strategy, exit_strategy)
  │
  ├─ 检查开放头寸 (get_positions_by_ticker)
  │  └─ 为每个头寸调用 exiter.evaluate_exit()
  │     → 生成 EXIT 或 HOLD 信号
  │
  ├─ 检查监视列表中的非头寸股票
  │  └─ 对每个股票调用 entry_scorer.evaluate()
  │     → 如果 score > buy_threshold 生成 BUY 信号
  │
  └─ 返回该组的信号列表
```

**关键计算：**

- 仅在现有头寸上调用 exiter（不是在所有股票上）
- 在非头寸股票上调用 entry scorer（buy_threshold = 65）
- 信心分数 = score / 100

---

### 2. TradeExecutor 类

**用途：** 执行信号，更新投资组合状态，记录交易

**输入：**

```python
class TradeExecutor:
    def __init__(
        self,
        state: ProductionState,
        history: TradeHistoryManager,
        current_date: str
    ):
        pass

    def execute_signal(
        self,
        signal: Signal,
        current_price: float
    ) -> ExecutionResult:
        """
        执行单个信号

        Returns:
            ExecutionResult(
              success: bool,
              executed_qty: int,
              executed_price: float,
              reason: str  # 如果失败的原因
            )
        """
        pass
```

**执行逻辑：**

#### BUY 信号

```python
def _execute_buy(self, signal: Signal, current_price: float):
    group = state.get_group(signal.group_id)

    # 计算可以买多少
    available_cash = group.cash
    max_position_value = available_cash * config['max_position_pct']
    position_value = current_price * qty  # qty 待定

    if position_value > max_position_value:
        qty = int(max_position_value / current_price)

    if group.cash < (current_price * qty):
        return ExecutionResult(success=False, reason="insufficient_cash")

    # 执行买入
    group.add_position(
        ticker=signal.ticker,
        quantity=qty,
        entry_price=current_price,
        entry_date=self.current_date,
        entry_score=signal.score
    )

    # 记录交易
    history.record_trade(
        date=self.current_date,
        group_id=signal.group_id,
        ticker=signal.ticker,
        action="BUY",
        quantity=qty,
        price=current_price,
        entry_score=signal.score
    )

    return ExecutionResult(success=True, executed_qty=qty, executed_price=current_price)
```

#### SELL 信号

```python
def _execute_sell(self, signal: Signal, current_price: float):
    group = state.get_group(signal.group_id)

    # 解析 signal.suggested_action ("SELL_50%", "SELL_100%")
    sell_pct = parse_action(signal.suggested_action)  # 0.5 或 1.0

    positions = group.get_positions_by_ticker(signal.ticker)
    total_qty = sum(p.quantity for p in positions)

    qty_to_sell = int(total_qty * sell_pct)

    if qty_to_sell == 0:
        return ExecutionResult(success=False, reason="qty_too_small")

    # FIFO 卖出
    proceeds, sold = group.partial_sell(
        ticker=signal.ticker,
        quantity=qty_to_sell,
        exit_price=current_price
    )

    # 计算 P&L
    entry_price = positions[0].entry_price  # FIFO 第一个
    pl_pct = ((current_price - entry_price) / entry_price) * 100

    # 记录交易
    history.record_trade(
        date=self.current_date,
        group_id=signal.group_id,
        ticker=signal.ticker,
        action="SELL",
        quantity=sold,
        price=current_price,
        exit_reason=signal.exit_reason,
        exit_score=signal.score
    )

    return ExecutionResult(success=True, executed_qty=sold, executed_price=current_price)
```

**保存状态：**

```python
def save_all(self):
    state.save()              # 更新 production_state.json
    history.save()            # 追加到 trade_history.json
```

---

## 数据流

```
Daily Pipeline:
  │
  ├─ 获取市场数据 (已有: data_manager)
  │   └─ df_features, df_trades, df_financials
  │
  ├─ SignalGenerator.evaluate_all_groups()
  │   └─ 调用 scorer/exiter
  │   └─ 返回 signals_group_a, signals_group_b
  │
  ├─ 保存信号文件 → signals_2026-01-21.json
  │   {
  │     "timestamp": "2026-01-21T12:34:56",
  │     "group_a": [...signals...],
  │     "group_b": [...signals...]
  │   }
  │
  ├─ TradeExecutor 顺序执行
  │   ├─ 过滤 signal_type == "BUY" 信号
  │   ├─ 过滤 signal_type == "SELL" 信号
  │   └─ 更新 production_state.json + trade_history.json
  │
  └─ 输出完成 → UI/报告可读取
```

---

## 集成点

### 与 Phase 2 的关系

- **读取：** ProductionState, TradeHistoryManager
- **写入：** 更新 cash/positions, 追加 trade_history.json

### 与现有系统的关系

- **读取：** data_manager (获取特征), scorer/exiter (评分)
- **依赖：** src/analysis/scorers, src/analysis/exiters, src/data/stock_data_manager

### 配置来源

```python
config = {
    "production": {
        "buy_threshold": 65,
        "max_positions_per_group": 5,
        "max_position_pct": 0.30,
        "strategy_groups": [
            {
                "id": "group_a",
                "entry_strategy": "SimpleScorerStrategy",
                "exit_strategy": "LayeredExitStrategy"
            },
            ...
        ]
    }
}
```

---

## 实施步骤

### Step 1: Signal 数据类

- 定义 Signal, ExecutionResult dataclass
- 文件: signal_generator.py 顶部

### Step 2: SignalGenerator 类

- 实现 evaluate_all_groups()
- 逻辑分离为 \_evaluate_entry_signals(), \_evaluate_exit_signals()
- 包含错误处理（缺失数据、异常）

### Step 3: TradeExecutor 类

- 实现 execute_signal()
- 分离 \_execute_buy(), \_execute_sell()
- 确保原子性（全部成功或全部失败）

### Step 4: 信号文件 I/O

- 实现 save_signals(signals_dict, date)
- 格式: signals_YYYY-MM-DD.json
- 路径: config['production']['signal_file_pattern']

### Step 5: 集成测试

- test_phase3_signal_generation.py
- 验证信号生成逻辑
- 验证交易执行更新状态

---

## 测试场景

### Scenario 1: 简单买入

```
输入：
  - group_a, ticker=8035, current_score=75
  - 现金充足

预期：
  - BUY 信号生成 (confidence=0.75)
  - 头寸添加到 state
  - 交易记录到 history
```

### Scenario 2: FIFO 部分卖出

```
输入：
  - group_a 持有 8035: 100 @ ¥31,500 (旧) + 50 @ ¥32,000 (新)
  - EXIT 信号要求卖出 50%
  - 当前价格 ¥32,500

预期：
  - SELL 75 shares (100 + 0 from second)
  - 保留：50 (第二个) [FIFO]
  - P&L 计算正确
```

### Scenario 3: 现金不足

```
输入：
  - group_a 现金 ¥50,000
  - 想买 100 @ ¥1,000 = ¥100,000

预期：
  - 部分执行: 买 50 股
  - 或拒绝: 返回 insufficient_cash
```

### Scenario 4: 买入阈值过滤

```
输入：
  - scorer 返回 score=60 (< buy_threshold=65)
  - ticker=8306

预期：
  - 不生成 BUY 信号
  - 保持 HOLD
```

---

## 错误处理

### 常见错误

1. **数据缺失** - 股票没有特征数据
   - 跳过该股票，记录警告
2. **现金不足** - 无法执行买入
   - 部分执行或完全拒绝（可配置）
3. **头寸不存在** - 尝试卖出不持有的股票
   - 返回错误，不执行
4. **Scorer 异常** - 评分函数失败
   - 捕获异常，返回 HOLD 信号

---

## 性能考虑

### 优化点

- 批量加载所有股票的特征数据（已在 data_manager）
- 缓存 scorer/exiter 实例（避免重复初始化）
- 使用向量化操作计算 P&L

### 预期性能

- 61 个股票评估：< 5 秒 (2 个 scorer + 2 个 exiter)
- 信号生成：< 10 秒（包括 I/O）
- 交易执行：< 1 秒（内存操作）

---

## 后续 Phase 依赖

- **Phase 4 (报告)**: 使用 signals\_\*.json 生成 Markdown
- **Phase 5 (CLI)**: 将 TradeExecutor 集成到 `trade record` 命令

---

**预计实施时间：** 2-3 小时  
**复杂度：** 中等（主要是逻辑协调，非算法复杂）
