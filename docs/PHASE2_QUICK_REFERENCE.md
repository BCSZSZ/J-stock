# Phase 2 快速参考 - API Cheat Sheet

## 🚀 快速开始 (5 分钟)

```python
from src.production.state_manager import ProductionState, TradeHistoryManager

# 1️⃣ 初始化
state = ProductionState("production_state.json")
history = TradeHistoryManager("trade_history.json")

# 2️⃣ 获取策略组
group_a = state.get_group("group_a")

# 3️⃣ 买入
group_a.add_position("8035", 100, 31500, "2026-01-21", 75.0)

# 4️⃣ 保存
state.save()
history.record_trade("2026-01-21", "group_a", "8035", "BUY", 100, 31500, 75.0)
history.save()

# 5️⃣ 查看状态
print(group_a.get_status())
```

---

## 📊 核心方法速查表

### Position 类 (头寸)

| 方法                       | 说明      | 示例                                   |
| -------------------------- | --------- | -------------------------------------- |
| `current_value(price)`     | 现价市值  | `pos.current_value(32000)` → 3.2M      |
| `unrealized_pl(price)`     | P&L (JPY) | `pos.unrealized_pl(33000)` → 150K      |
| `unrealized_pl_pct(price)` | P&L (%)   | `pos.unrealized_pl_pct(33000)` → 4.76% |
| `holding_days()`           | 持有天数  | `pos.holding_days()` → 6               |

### StrategyGroupState 类 (策略组)

| 方法                               | 说明         | 返回             |
| ---------------------------------- | ------------ | ---------------- |
| `add_position(...)`                | 买入         | None             |
| `partial_sell(ticker, qty, price)` | 卖出 (FIFO)  | (proceeds, qty)  |
| `get_position(ticker)`             | 获取FIFO头寸 | Position or None |
| `get_positions_by_ticker(ticker)`  | 获取所有头寸 | List[Position]   |
| `total_value(prices)`              | 投资组合总值 | float            |
| `get_status(prices)`               | 状态摘要     | dict             |

### ProductionState 类 (多组)

| 方法                           | 说明         | 返回                     |
| ------------------------------ | ------------ | ------------------------ |
| `add_group(id, name, capital)` | 新增策略组   | StrategyGroupState       |
| `get_group(id)`                | 获取策略组   | StrategyGroupState       |
| `get_all_groups()`             | 获取所有组   | List[StrategyGroupState] |
| `select_group_interactive()`   | 交互选择     | StrategyGroupState       |
| `load()`                       | 从文件加载   | None                     |
| `save()`                       | 保存到文件   | None                     |
| `get_portfolio_status(prices)` | 投资组合状态 | dict                     |

### TradeHistoryManager 类 (历史)

| 方法                           | 说明       | 返回        |
| ------------------------------ | ---------- | ----------- |
| `record_trade(...)`            | 记录交易   | Trade       |
| `get_trades_by_group(id)`      | 按组查询   | List[Trade] |
| `get_trades_by_ticker(ticker)` | 按股票查询 | List[Trade] |
| `get_trades_by_date(date)`     | 按日期查询 | List[Trade] |
| `load()`                       | 加载历史   | None        |
| `save()`                       | 保存历史   | None        |

---

## 💼 常见场景

### 场景 1: 检查现金充足

```python
group = state.get_group("group_a")

required_capital = 31500 * 100
if group.cash >= required_capital:
    group.add_position("8035", 100, 31500, "2026-01-21", 75.0)
    state.save()
else:
    print(f"现金不足: {group.cash} < {required_capital}")
```

### 场景 2: 查询头寸

```python
# 单个头寸 (FIFO 最早的)
pos = group.get_position("8035")
if pos:
    print(f"{pos.ticker} x{pos.quantity} @ ¥{pos.entry_price}")

# 所有头寸
all_pos = group.get_positions_by_ticker("8035")
total = sum(p.quantity for p in all_pos)
print(f"总持仓: {total} 股")
```

### 场景 3: 部分卖出

```python
# 卖出50股
proceeds, sold = group.partial_sell("8035", 50, 32500)

print(f"卖出: {sold} 股")
print(f"收益: ¥{proceeds:,.0f}")
print(f"现金: ¥{group.cash:,.0f}")

# 记录
history.record_trade(
    "2026-01-21", "group_a", "8035", "SELL",
    sold, 32500, exit_reason="Take Profit"
)
history.save()
```

### 场景 4: 投资组合概览

```python
prices = {"8035": 32000, "8306": 1950, "7974": 2200}
status = state.get_portfolio_status(prices)

print(f"总资产: ¥{status['total_value']:,.0f}")
print(f"现金: ¥{status['total_cash']:,.0f}")
print(f"头寸: {status['total_positions']}")
print(f"组数: {status['num_groups']}")
```

### 场景 5: 交互选择策略组

```python
# 自动检测
group = state.select_group_interactive()
# 如果只有1个组 → 自动返回
# 如果有多个 → 显示菜单让用户选择

print(f"已选择: {group.name} (ID: {group.id})")
```

---

## 🔧 数据结构速查

### Position 字段

```python
Position(
    ticker: str,                  # "8035"
    quantity: int,                # 100
    entry_price: float,           # 31500.0
    entry_date: str,              # "2026-01-21"
    entry_score: float,           # 75.0
    peak_price: float = 0.0       # 31500.0
)
```

### Trade 字段

```python
Trade(
    date: str,                    # "2026-01-21"
    group_id: str,                # "group_a"
    ticker: str,                  # "8035"
    action: str,                  # "BUY" or "SELL"
    quantity: int,                # 100
    price: float,                 # 31500.0
    total_jpy: float,             # 3150000.0
    entry_score: Optional[float],           # 75.0 (for BUY)
    exit_reason: Optional[str] = None,      # "Take Profit" (for SELL)
    exit_score: Optional[float] = None      # 68.0 (for SELL)
)
```

---

## ⚠️ 常见错误

### 错误 1: 现金不足

```python
❌ 错误:
group.add_position("8035", 100, 31500, ...)  # 需要 ¥3.15M

✅ 修正:
if group.cash >= 31500 * 100:
    group.add_position(...)
else:
    print("现金不足")
```

### 错误 2: 头寸不存在

```python
❌ 错误:
group.partial_sell("8999", 50, 32500)  # 没有8999的头寸

✅ 修正:
if group.get_position("8999"):
    group.partial_sell("8999", 50, 32500)
else:
    print("头寸不存在")
```

### 错误 3: 数量过多

```python
❌ 错误:
group.partial_sell("8035", 1000, 32500)  # 只持有100股

✅ 修正:
positions = group.get_positions_by_ticker("8035")
max_qty = sum(p.quantity for p in positions)
qty_to_sell = min(100, max_qty)
group.partial_sell("8035", qty_to_sell, 32500)
```

### 错误 4: 忘记保存

```python
❌ 错误:
group.add_position(...)
# 程序结束，状态未保存

✅ 修正:
group.add_position(...)
state.save()  # ← 必须
```

---

## 🧮 计算公式

### 头寸值

```
现价市值 = 数量 × 当前价格
   例: 100 × 32000 = ¥3.2M

持仓成本 = 数量 × 入价
   例: 100 × 31500 = ¥3.15M

未实现P&L = 现价市值 - 持仓成本
   例: 3.2M - 3.15M = ¥50,000

P&L% = ((现价 - 入价) / 入价) × 100
   例: ((32000 - 31500) / 31500) × 100 = 1.59%
```

### 投资组合

```
总资产 = 现金 + Σ(所有头寸现价市值)

现金 = 初始资本 - Σ(买入金额) + Σ(卖出金额)

投资率 = 投资金额 / 初始资本 × 100%
```

---

## 📝 文件位置

| 文件                                | 用途         |
| ----------------------------------- | ------------ |
| `src/production/state_manager.py`   | 核心模块     |
| `production_state.json`             | 投资组合状态 |
| `trade_history.json`                | 交易审计日志 |
| `data/production_monitor_list.json` | 61只监视股票 |
| `config.json`                       | 策略配置     |

---

## 🎯 关键限制

| 限制                 | 值     |
| -------------------- | ------ |
| 每个策略组最大头寸数 | 5      |
| 单头寸最大投资占比   | 30%    |
| 最小买入阈值         | 65 分  |
| 最大买入数量         | 无限制 |

---

## 🔄 FIFO 示例

```
堆栈状态:
  [0] 100 股 @ ¥30,000
  [1] 100 股 @ ¥31,000
  [2] 100 股 @ ¥32,000

command: 卖出 150 股

执行过程:
  Step 1: 卖 [0] 全部 100 股
  Step 2: 卖 [1] 全部 100 股
  Step 3: 卖 [2] 部分 50 股

结果:
  堆栈: [2] 剩余 50 股 @ ¥32,000
  收益: 100×32500 + 100×32500 + 50×32500 = ¥8.125M
```

---

## 📞 示例代码

### 完整买卖流程

```python
from src.production.state_manager import ProductionState, TradeHistoryManager

# 初始化
state = ProductionState()
history = TradeHistoryManager()

# 获取策略组
group = state.select_group_interactive()

# 买入
date = "2026-01-21"
group.add_position("8035", 100, 31500, date, 75.0)
history.record_trade(date, group.id, "8035", "BUY", 100, 31500, 75.0)

# 卖出
proceeds, sold = group.partial_sell("8035", 50, 32500)
history.record_trade(date, group.id, "8035", "SELL", sold, 32500,
                    exit_reason="Take Profit", exit_score=68.0)

# 保存
state.save()
history.save()

# 报告
status = group.get_status({"8035": 32500})
print(f"现金: ¥{status['current_cash']:,.0f}")
print(f"头寸: {status['position_count']}")
```

---

**最后更新:** 2026-01-21  
**版本:** Phase 2 Final
