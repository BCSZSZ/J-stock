# Daily Production Trading System - Design Consensus

**Date:** 2026-01-19  
**Status:** 设计讨论中，待最终确认

---

## 核心需求

实现实盘交易辅助系统，支持：
1. **准备交易**：爬取最新数据 → 生成策略报告 → 用于第二天交易决策
2. **记录交易**：录入实际成交 → 更新持久化状态

**工作流：**
- 任意时刻：如果有交易，运行 `record` 记录
- 每晚：运行 `prepare` 生成明日策略

---

## 命名方案（待选择）

### **方案A：`trade` 系列（推荐）**
```bash
python main.py trade prepare   # 准备明天：爬数据 + 生成策略报告
python main.py trade record    # 记录交易：录入实际成交
```
**优点：** 
- 与 backtest 对称（一个回测，一个实盘）
- prepare/record 语义自然
- 未来扩展方便（如 `trade status` 可选加回来）

---

### **方案B：`live` 系列**
```bash
python main.py live scan       # 扫描市场：爬数据 + 生成信号
python main.py live update     # 更新持仓：录入交易
```
**优点：** 
- live 强调实盘（vs backtest）
- scan/update 更技术化

---

### **方案C：顶层命令（最简）**
```bash
python main.py prepare         # 准备交易
python main.py record          # 记录交易
```
**优点：** 
- 最短
- 但和其他命令（fetch/backtest）并列，可能语义层次不统一

---

## 功能详细定义

### **1. `trade prepare`（准备明天）**

#### 输入
- `config.json` → production 配置（初始资金、策略名、monitor列表路径）
- `data/production_monitor_list.json` → 要监控的股票列表
- `production_state.json` → 当前持仓状态（如不存在则自动创建）

#### 执行流程
1. **检查/创建状态文件**
   - 首次运行：从 config.json 读取 initial_capital，创建空状态
   - 后续运行：加载现有状态

2. **显示当前状态摘要**
   ```
   ========================================
   📊 当前持仓状态
   ========================================
   现金: ¥2,500,000
   持仓: 3 只
     - 8035: 100股 @ ¥31,500 → ¥37,200 (+18.1%, 持有45天)
     - 7974: 200股 @ ¥5,820 → ¥6,100 (+4.8%, 持有12天)
     - 6501: 50股 @ ¥13,200 → ¥12,800 (-3.0%, 持有8天)
   总市值: ¥2,700,000
   浮动盈亏: +8.0%
   ```

3. **爬取最新数据**
   - TOPIX benchmark（日线OHLC）
   - monitor list 所有股票：
     - OHLCV（日线）
     - 机构交易流（周度）
     - 财报数据（季度）
     - 元数据（earnings calendar）

4. **加载策略**
   - Entry scorer：从 config.production.entry_strategy 读取
   - Exit strategy：从 config.production.exit_strategy 读取

5. **生成信号**
   - **买入机会**：
     - 对 monitor list 中**未持仓**的股票评分
     - 筛选 score ≥ buy_threshold（默认65）
     - 按分数降序排列
   - **卖出建议**：
     - 对当前所有持仓运行 exiter
     - 生成退出信号（HOLD/SELL_X%）

6. **保存信号文件**
   - 文件名：`signals_YYYY-MM-DD.json`
   - 内容：买入列表 + 卖出列表

7. **显示交易计划报告**
   ```
   ========================================
   📈 买入机会（≥65分）
   ========================================
   1. 4568 第一三共 - 分数: 78.5 (STRONG_BUY)
      当前价: ¥5,230
      建议买入: 100股 (约 ¥523,000)
      理由: 技术面强势，机构持续买入，ROE改善

   2. 7011 三菱重工 - 分数: 71.2 (BUY)
      当前价: ¥2,180
      建议买入: 200股 (约 ¥436,000)
      理由: EMA金叉，防卫订单增长

   ========================================
   🔴 卖出建议
   ========================================
   1. 6501 日立 - SELL_50% (MEDIUM)
      当前价: ¥12,800
      盈亏: -3.0% (持有8天)
      理由: 技术面走弱，跌破EMA20

   ========================================
   ✅ 信号已保存: signals_2026-01-19.json
   ```

#### 待确认问题

**Q1:** 报告要保存成文件吗？（txt/markdown）还是只终端显示？

**Q2:** 如果当天已经运行过（signals文件已存在），要覆盖还是提示？

**Q3:** 买入建议要考虑现金余额吗？
- 如现金不够买所有信号，按分数排序取前N个？
- 还是显示所有信号，让用户自己选择？

---

### **2. `trade record`（记录交易）**

#### 输入
- `production_state.json` → 当前持仓状态
- 用户交互输入（实际成交记录）

#### 执行流程
1. **加载当前状态**
   - 显示当前持仓摘要

2. **显示昨日信号**（可选参考）
   - 如果存在昨日 signals 文件，显示为参考

3. **交互式录入**
   ```
   ========================================
   💰 记录实际交易
   ========================================
   
   请输入买入交易（格式: ticker price quantity）
   输入空行结束
   买入 > 4568 5230 100
   ✅ 已记录: 4568 买入 100股 @ ¥5,230
   买入 > 7011 2180 200
   ✅ 已记录: 7011 买入 200股 @ ¥2,180
   买入 > 
   
   请输入卖出交易（格式: ticker price quantity）
   输入空行结束
   卖出 > 6501 12800 25
   ✅ 已记录: 6501 卖出 25股 @ ¥12,800
   卖出 > 
   ```

4. **更新状态**
   - **买入**：
     - 减少现金：`cash -= price * quantity`
     - 新增持仓或增加数量
     - 记录 entry_price, entry_date
   - **卖出**：
     - 增加现金：`cash += price * quantity`
     - 减少持仓数量或清除持仓
     - 计算盈亏

5. **显示更新后状态**
   ```
   ========================================
   更新后持仓状态
   ========================================
   现金: ¥1,782,000
   持仓: 5 只
   ...
   ```

6. **保存状态**
   - 更新 `production_state.json`
   - 追加到 `trade_history.json`

#### 待确认问题

**Q4:** 卖出时，如果是部分卖出（如持有100股卖50股），如何处理 entry_price？
- **方案A（FIFO）**：保持原 entry_price
- **方案B（加权平均）**：如有多次买入，计算加权平均价

**Q5:** 如果输入错误（如卖出数量超过持仓），怎么处理？
- **方案A**：立即报错，重新输入当前这条
- **方案B**：完成所有输入后统一校验

**Q6:** 要支持撤销上一条输入吗？
- **方案A**：支持（输入 `undo` 撤销）
- **方案B**：不支持，输错就重新运行

---

## 配置文件结构

### `config.json` 新增 production 节点

```json
{
  "default_strategies": {
    "entry": "SimpleScorerStrategy",
    "exit": "ATRExitStrategy"
  },
  "production": {
    "initial_capital": 3000000,
    "entry_strategy": "SimpleScorerStrategy",
    "exit_strategy": "LayeredExitStrategy",
    "monitor_list_file": "data/production_monitor_list.json",
    "state_file": "production_state.json",
    "signal_file_pattern": "signals_{date}.json",
    "history_file": "trade_history.json",
    "max_positions": 5,
    "max_position_pct": 0.30,
    "buy_threshold": 65
  }
}
```

**字段说明：**
- `initial_capital`：初始资金（仅首次初始化用）
- `entry_strategy`：入场策略类名
- `exit_strategy`：出场策略类名
- `monitor_list_file`：监视列表文件路径
- `state_file`：持仓状态文件路径
- `signal_file_pattern`：信号文件命名模式（{date} 会替换为日期）
- `history_file`：交易历史文件路径
- `max_positions`：最大持仓数量
- `max_position_pct`：单只股票最大仓位比例
- `buy_threshold`：买入信号分数阈值

---

### `data/production_monitor_list.json`

独立的生产监视列表（可与全局 monitor_list.json 不同）

```json
{
  "tickers": [
    "8035",
    "7974",
    "6861",
    "6501",
    "8058",
    "7203",
    "4568",
    "8306",
    "7011",
    "4063"
  ],
  "last_updated": "2026-01-19"
}
```

---

### `production_state.json`

实时持仓状态

```json
{
  "cash": 2500000,
  "positions": [
    {
      "ticker": "8035",
      "entry_price": 31500,
      "entry_date": "2025-12-05",
      "quantity": 100,
      "peak_price": 37200
    },
    {
      "ticker": "7974",
      "entry_price": 5820,
      "entry_date": "2026-01-08",
      "quantity": 200,
      "peak_price": 6100
    }
  ],
  "last_updated": "2026-01-19T20:30:00"
}
```

**字段说明：**
- `cash`：当前现金余额
- `positions`：当前持仓列表
  - `ticker`：股票代码
  - `entry_price`：入场价格
  - `entry_date`：入场日期（ISO格式字符串，加载时转为 Timestamp）
  - `quantity`：持有数量
  - `peak_price`：持有期间最高价（用于追踪trailing stop）
- `last_updated`：最后更新时间

---

### `signals_YYYY-MM-DD.json`

每日生成的信号文件

```json
{
  "date": "2026-01-19",
  "buy_signals": [
    {
      "ticker": "4568",
      "score": 78.5,
      "signal_strength": "STRONG_BUY",
      "current_price": 5230,
      "suggested_quantity": 100,
      "reason": "技术面强势，机构持续买入，ROE改善",
      "breakdown": {
        "technical": 85.0,
        "institutional": 75.0,
        "fundamental": 80.0,
        "volatility": 72.0
      }
    }
  ],
  "sell_signals": [
    {
      "ticker": "6501",
      "action": "SELL_50%",
      "urgency": "MEDIUM",
      "current_price": 12800,
      "reason": "技术面走弱，跌破EMA20",
      "profit_loss_pct": -3.0,
      "holding_days": 8
    }
  ]
}
```

---

### `trade_history.json`

所有交易历史记录

```json
{
  "trades": [
    {
      "date": "2026-01-15",
      "action": "BUY",
      "ticker": "8035",
      "price": 31500,
      "quantity": 100,
      "total": 3150000
    },
    {
      "date": "2026-01-19",
      "action": "SELL",
      "ticker": "6501",
      "price": 12800,
      "quantity": 25,
      "total": 320000,
      "profit": -10000,
      "profit_pct": -3.0,
      "holding_days": 8
    }
  ]
}
```

**字段说明：**
- `date`：交易日期
- `action`：BUY/SELL
- `ticker`：股票代码
- `price`：成交价格
- `quantity`：数量
- `total`：总金额
- `profit`（仅卖出）：盈亏金额
- `profit_pct`（仅卖出）：盈亏百分比
- `holding_days`（仅卖出）：持有天数

---

## 设计原则

### ✅ 应该做的
1. **独立配置**：生产环境与回测配置分离
2. **懒初始化**：状态文件不存在时自动创建，无需 init 命令
3. **数据共享**：复用现有 parquet/json 数据格式
4. **策略复用**：直接使用现有 scorer/exiter 类
5. **持久化简单**：JSON 文件，易于人工查看和编辑
6. **历史完整**：所有交易追加到 history，永不删除

### ❌ 不应该做的
1. **不修改 BaseScorer/BaseExiter**：只使用，不改接口
2. **不做自动交易**：只生成建议，不实际下单
3. **不做复杂状态管理**：避免数据库，保持文件系统简单
4. **不做实时监控**：prepare 是批处理，不是实时流式
5. **不创建不必要的子命令**：保持简洁

---

## 技术要点

### 避免之前的坑

1. **ScoreResult vs float**
   ```python
   # ❌ 错误
   if current_score > 70:  # current_score 是 ScoreResult 对象！
   
   # ✅ 正确
   if isinstance(current_score, ScoreResult):
       score_value = current_score.total_score
   else:
       score_value = current_score
   if score_value > 70:
   ```

2. **entry_date 必须是 Timestamp**
   ```python
   # ❌ 错误
   position = Position(entry_date="2025-01-15")  # 字符串
   
   # ✅ 正确
   position = Position(entry_date=pd.Timestamp("2025-01-15"))
   ```

3. **DataFrame index 约定**
   - features：Date 是 INDEX
   - trades：EnDate 是 COLUMN
   - financials：DiscDate 是 COLUMN

---

## 实现顺序（待确认后执行）

1. **配置准备**
   - 更新 config.json（添加 production 节点）
   - 创建 data/production_monitor_list.json

2. **状态管理模块**
   - `src/production/state_manager.py`：加载/保存状态，更新持仓

3. **CLI 框架**
   - main.py 添加 trade 命令
   - 子解析器：prepare, record

4. **prepare 实现**
   - 数据爬取（复用现有 pipeline）
   - 信号生成（scorer/exiter）
   - 报告显示和保存

5. **record 实现**
   - 交互式输入
   - 状态更新
   - 历史追加

6. **测试验证**
   - 测试 prepare（首次运行 + 后续运行）
   - 测试 record（买入 + 卖出 + 边界情况）

---

## 待确认清单

在开始实现前，需要确认：

- [ ] **命名方案**：选择 A/B/C 或提出新方案
- [ ] **Q1**：报告保存策略（仅终端 / 同时保存文件）
- [ ] **Q2**：重复运行处理（覆盖 / 提示 / 跳过）
- [ ] **Q3**：买入建议算法（考虑现金余额 / 显示所有）
- [ ] **Q4**：部分卖出 entry_price 处理（FIFO / 加权平均）
- [ ] **Q5**：输入错误处理（立即报错 / 批量校验）
- [ ] **Q6**：支持撤销功能（是 / 否）
- [ ] **配置结构确认**：是否需要调整字段

---

## 下次继续

确认以上待定问题后，开始实现代码。

