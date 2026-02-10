# Phase 1 实装方案 - 配置和数据结构

**用户决策**:

- Q1: 允许同股票多策略组（方案A）
- Q2: 交互式选择策略组
- Q3: FIFO处理部分卖出
- 必须完整实现（不简化）

---

## 📝 Phase 1 改动清单

### 1. config.json 新增 production 节点

**文件**: `config.json`  
**操作**: 添加新的 `production` 顶层字段

**改动内容**:

```json
{
  "default_strategies": {
    "entry": "SimpleScorerStrategy",
    "exit": "ATRExitStrategy"
  },
  "data": {
    "monitor_list_file": "data/monitor_list.txt",
    ...
  },

  "production": {
    "monitor_list_file": "data/production_monitor_list.json",
    "state_file": "production_state.json",
    "signal_file_pattern": "signals_{date}.json",
    "report_file_pattern": "trade_report_{date}.md",
    "history_file": "trade_history.json",
    "max_positions_per_group": 5,
    "max_position_pct": 0.30,
    "buy_threshold": 65,
    "strategy_groups": [
      {
        "id": "default",
        "name": "Default Strategy Group",
        "initial_capital": 3000000,
        "entry_strategy": "SimpleScorerStrategy",
        "exit_strategy": "LayeredExitStrategy"
      }
    ]
  }
}
```

**新增字段说明**:

- `monitor_list_file`: 生产环境监视列表路径
- `state_file`: 持仓状态文件路径（自动创建）
- `signal_file_pattern`: 信号文件命名模式（{date} 替换为 YYYY-MM-DD）
- `report_file_pattern`: 报告文件命名模式
- `history_file`: 交易历史文件路径
- `max_positions_per_group`: 每个策略组最大持仓数
- `max_position_pct`: 单只股票最大仓位占比
- `buy_threshold`: 买入信号最低分数
- `strategy_groups[]`: 策略组列表
  - `id`: 策略组唯一标识
  - `name`: 策略组显示名称
  - `initial_capital`: 初始资金
  - `entry_strategy`: 入场策略类名
  - `exit_strategy`: 出场策略类名

---

### 2. 创建示例 production_monitor_list.json

**文件**: `data/production_monitor_list.json`（新建）  
**操作**: 新建生产监视列表

**内容**:

```json
{
  "version": "1.0",
  "last_updated": "2026-01-21",
  "description": "Production trading monitor list",
  "tickers": [
    "8035",
    "8306",
    "7974",
    "7011",
    "6861",
    "8058",
    "6501",
    "4063",
    "7203",
    "4568",
    "6098",
    "1321"
  ]
}
```

**说明**: 初始包含12只核心股票，用户可自行修改

---

### 3. 创建示例 production_state.json（初始模板）

**文件**: `production_state.json`（初始模板）  
**操作**: 提供示例内容（首次运行时自动生成）

**内容**:

```json
{
  "last_updated": "2026-01-21T00:00:00",
  "strategy_groups": [
    {
      "id": "default",
      "name": "Default Strategy Group",
      "initial_capital": 3000000,
      "cash": 3000000,
      "positions": []
    }
  ]
}
```

**说明**: 首次运行 `trade prepare` 时，从 config.json 自动初始化多个策略组

---

### 4. 创建示例 signals_YYYY-MM-DD.json 结构

**文件**: `signals_YYYY-MM-DD.json`（示例）  
**操作**: 定义信号文件格式（运行时生成）

**内容**:

```json
{
  "date": "2026-01-21",
  "generated_at": "2026-01-21T20:30:00",
  "strategy_groups": [
    {
      "group_id": "default",
      "group_name": "Default Strategy Group",
      "entry_strategy": "SimpleScorerStrategy",
      "exit_strategy": "LayeredExitStrategy",
      "cash_available": 2500000,
      "buy_signals": [
        {
          "ticker": "4568",
          "score": 78.5,
          "signal_strength": "STRONG_BUY",
          "current_price": 5230,
          "suggested_quantity": 100,
          "estimated_cost": 523000,
          "reason": "技术面强势，机构持续买入",
          "breakdown": {
            "technical": 85.0,
            "institutional": 75.0,
            "fundamental": 80.0,
            "volatility": 72.0
          }
        },
        {
          "ticker": "7011",
          "score": 71.2,
          "signal_strength": "BUY",
          "current_price": 2180,
          "suggested_quantity": 200,
          "estimated_cost": 436000,
          "reason": "EMA金叉，防卫订单增长",
          "breakdown": {
            "technical": 75.0,
            "institutional": 68.0,
            "fundamental": 72.0,
            "volatility": 65.0
          }
        }
      ],
      "sell_signals": [
        {
          "ticker": "6501",
          "action": "SELL_50%",
          "urgency": "MEDIUM",
          "current_quantity": 100,
          "suggested_quantity": 50,
          "current_price": 12800,
          "entry_price": 13200,
          "reason": "技术面走弱，跌破EMA20",
          "profit_loss_pct": -3.0,
          "holding_days": 8
        }
      ]
    }
  ]
}
```

**说明**: 每个策略组独立生成 buy_signals 和 sell_signals

---

### 5. 创建示例 trade_history.json 结构

**文件**: `trade_history.json`（示例）  
**操作**: 定义交易历史文件格式

**内容**:

```json
{
  "trades": [
    {
      "date": "2026-01-15",
      "strategy_group_id": "default",
      "action": "BUY",
      "ticker": "8035",
      "price": 31500,
      "quantity": 100,
      "total": 3150000,
      "notes": "Strong buy signal"
    },
    {
      "date": "2026-01-19",
      "strategy_group_id": "default",
      "action": "SELL",
      "ticker": "6501",
      "price": 12800,
      "quantity": 25,
      "total": 320000,
      "entry_price": 13200,
      "profit": -10000,
      "profit_pct": -3.0,
      "holding_days": 8,
      "notes": "Sell 50% as suggested"
    }
  ]
}
```

**说明**: 所有交易追加到此文件，支持多策略组（通过 strategy_group_id）

---

### 6. 创建示例 trade_report_YYYY-MM-DD.md

**文件**: `trade_report_YYYY-MM-DD.md`（运行时生成）  
**操作**: 定义报告文件格式

**内容示例**:

```markdown
# 交易策略报告

**日期**: 2026-01-21  
**生成时间**: 2026-01-21 20:30:00

---

## 策略组: Default Strategy Group

**策略**: SimpleScorerStrategy → LayeredExitStrategy  
**可用现金**: ¥2,500,000

### 📊 当前持仓（2只）

| 股票 | 数量 | 入场价  | 当前价  | 盈亏%  | 持有天数 |
| ---- | ---- | ------- | ------- | ------ | -------- |
| 8035 | 100  | ¥31,500 | ¥37,200 | +18.1% | 47       |
| 7974 | 200  | ¥5,820  | ¥6,100  | +4.8%  | 13       |

**总市值**: ¥4,940,000  
**浮动盈亏**: +¥680,000 (+16.0%)

---

### 📈 买入信号（2个）

1. **4568 第一三共 - 78.5分 (STRONG_BUY)**
   - 当前价: ¥5,230
   - 建议数量: 100股
   - 预估成本: ¥523,000 ✅ 现金充足
   - 理由: 技术面强势，机构持续买入

2. **7011 三菱重工 - 71.2分 (BUY)**
   - 当前价: ¥2,180
   - 建议数量: 200股
   - 预估成本: ¥436,000 ✅ 现金充足
   - 理由: EMA金叉，防卫订单增长

---

### 🔴 卖出建议（1个）

1. **6501 日立 - SELL_50% (MEDIUM)**
   - 当前价: ¥12,800
   - 建议卖出: 50股（当前持有100股）
   - 盈亏: -3.0% (持有8天)
   - 理由: 技术面走弱，跌破EMA20

---

✅ 信号文件已保存: `signals_2026-01-21.json`
```

---

## 🔍 改动清单总结

| 操作 | 文件                                | 类型     | 说明                         |
| ---- | ----------------------------------- | -------- | ---------------------------- |
| 修改 | `config.json`                       | JSON     | 添加 production 节点         |
| 新建 | `data/production_monitor_list.json` | JSON     | 生产监视列表                 |
| 新建 | `production_state.json`             | JSON     | 持仓状态（首次运行自动创建） |
| 定义 | `signals_YYYY-MM-DD.json`           | JSON     | 信号文件格式                 |
| 定义 | `trade_history.json`                | JSON     | 交易历史                     |
| 定义 | `trade_report_YYYY-MM-DD.md`        | Markdown | 报告格式                     |

---

## ✅ 确认清单

实施前请确认：

- [ ] config.json 的 production 节点结构是否满足需求？
- [ ] strategy_groups 的字段（id, name, initial_capital, entry_strategy, exit_strategy）是否完整？
- [ ] production_monitor_list.json 的初始股票列表是否需要调整？
- [ ] signals 文件格式中，每个策略组独立的 buy_signals/sell_signals 是否符合需求？
- [ ] trade_history.json 中记录 strategy_group_id 是否足以支持多策略组追踪？
- [ ] 是否需要添加其他字段（如每个持仓的 entry_score 记录）？

---

**下一步**: 确认以上所有改动后，我们开始实施 Phase 1
