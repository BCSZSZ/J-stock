# 组合投资回测系统

## 概述

本系统提供**两套独立的回测架构**:

### 1. 单股票回测（Single Stock Backtest）

- **入口**: `start_backtest.py`
- **配置**: `backtest_config.json`
- **特点**: 每次回测一只股票，全仓买入
- **用途**: 测试策略在单个股票上的表现

### 2. 组合投资回测（Portfolio Backtest）

- **入口**: `start_portfolio_backtest.py`
- **配置**: `portfolio_config.json`
- **特点**: 同时管理多只股票，分散投资
- **用途**: 测试策略在投资组合上的表现

---

## 快速开始

### 单股票回测

```bash
python start_backtest.py
```

### 组合投资回测

```bash
python start_portfolio_backtest.py
```

---

## 组合投资回测新功能

### 核心特性

#### 1. 多持仓管理

```python
# 可以同时持有多只股票
最大持仓数: 5只
单股最大仓位: 30%
单股最小仓位: 5%
```

#### 2. 信号竞争处理

当多只股票同时发出买入信号时，系统会根据优先级排序:

- **simple_score**: 按综合得分排序
- **confidence_weighted**: 按得分 × 信心度排序
- **risk_adjusted**: 按风险调整得分排序

#### 3. 最小购买单位

```python
# 日本市场规则
普通股票: 100股为1单位
REIT (如1321): 1股为1单位
```

#### 4. 智能资金分配

- 自动计算每只股票的可用资金
- 确保不超过单股最大仓位限制
- 考虑最小购买单位约束

---

## 配置文件说明

### portfolio_config.json

```json
{
  "portfolio_backtest_config": {
    "tickers": ["1321", "1231", "7203", "6501", "8035"],

    "portfolio_rules": {
      "starting_capital_jpy": 5000000,  // 起始资金
      "max_positions": 5,                // 最多同时持有5只
      "max_position_pct": 0.30,         // 单股最大30%
      "min_position_pct": 0.05          // 单股最小5%
    },

    "lot_sizes": {
      "1321": 1,      // REIT: 1股起
      "default": 100  // 普通股票: 100股起
    },

    "signal_ranking": {
      "method": "simple_score"  // 信号排序方法
    },

    "strategies": [
      {"entry": "SimpleScorerStrategy", "exit": "ATRExitStrategy"},
      ...
    ]
  }
}
```

---

## 回测流程

### 单股票回测流程

```
对每只股票独立回测:
1. 加载股票数据
2. 生成入场/出场信号
3. 全仓买入
4. 持有或卖出
5. 计算收益
```

### 组合投资回测流程

```
每日循环:
1. 执行待执行的卖出订单 (释放资金)
2. 执行待执行的买入订单 (按优先级)
   a. 对所有买入信号排序
   b. 依次尝试买入前N只
   c. 检查持仓数量、资金、lot size
3. 为所有股票生成新信号
4. 更新持仓峰值价格
5. 记录组合总资产
```

---

## 输出示例

### 单股票回测输出

```
策略 1/9: 7203 × SimpleScorer + ATRExitStrategy
────────────────────────────────────────
  📊 BUY  2023-08-04: 2,077 shares @ ¥2,407.00
  📈 SELL 2023-10-02: 2,077 shares @ ¥2,700.50 (+12.19%)

总回报: +42.69%
夏普比率: 1.23
```

### 组合投资回测输出

```
策略 1/9: Portfolio[1321, 1231, 7203, 6501] × SimpleScorer + ATRExitStrategy
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 买入信号排序 (2023-08-04):
   #1 7203: Score=68.0, Priority=68.0
   #2 1321: Score=66.0, Priority=66.0
   #3 6501: Score=65.0, Priority=65.0

  📊 BUY  7203: 1,000 shares @ ¥2,407.00 (Score: 68.0)
  📊 BUY  1321: 500 shares @ ¥3,500.00 (Score: 66.0)
  📊 BUY  6501: 200 shares @ ¥8,500.00 (Score: 65.0)

  📈 SELL 7203: 1,000 shares @ ¥2,700.50 (+12.19%, ¥+293,500)

总回报: +58.3%
夏普比率: 1.87
```

---

## 架构设计

### 新增组件

#### Portfolio (组合管理器)

- 文件: `src/backtest/portfolio.py`
- 功能: 管理多个股票持仓、现金、仓位限制

#### SignalRanker (信号排序器)

- 文件: `src/backtest/signal_ranker.py`
- 功能: 对同时触发的买入信号排序

#### LotSizeManager (购买单位管理)

- 文件: `src/backtest/lot_size_manager.py`
- 功能: 处理不同股票的最小购买单位

#### PortfolioBacktestEngine (组合引擎)

- 文件: `src/backtest/portfolio_engine.py`
- 功能: 组合回测核心逻辑

---

## 适用场景

### 使用单股票回测

- 测试策略在特定股票上的效果
- 快速验证策略逻辑
- 分析单个标的的历史表现

### 使用组合投资回测

- 测试实际投资场景（分散投资）
- 评估资金分配策略
- 分析组合风险和收益
- 模拟真实交易环境

---

## 常见问题

### Q: 两套系统可以同时使用吗?

A: 可以！它们完全独立，互不影响。

### Q: 配置文件可以互换吗?

A: 不可以。两套系统使用不同的配置文件格式。

### Q: 组合回测会慢很多吗?

A: 会稍慢，因为需要同时处理多只股票的信号。

### Q: 可以自定义信号排序逻辑吗?

A: 可以！修改 `SignalRanker` 类，添加新的排序方法。

---

## 未来改进

- [ ] 实现再平衡机制
- [ ] 添加行业分散检查
- [ ] 支持股票间相关性分析
- [ ] 动态仓位调整
- [ ] 组合级别的风险指标（Sharpe, Max Drawdown 等）
- [ ] 可视化组合权重变化

---

## 技术支持

如有问题，请查看:

- 单股票回测文档: `USAGE_GUIDE.md`
- 策略设计文档: `FINAL_STRATEGY_ARCHITECTURE.md`
- 回测配置文档: `BACKTEST_CONFIG_GUIDE.md`
