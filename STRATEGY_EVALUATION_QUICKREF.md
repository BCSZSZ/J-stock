# 策略评价系统 - 快速参考卡

## 一行命令

### 快速测试（推荐首次使用）

```bash
python test_strategy_evaluation.py
```

- 2 个月 × 25 策略 = 50 次回测
- 耗时: ~10-15 分钟

### 完整评估

```bash
python main.py evaluate --mode annual --years 2021 2022 2023 2024 2025
```

- 5 年 × 25 策略 = 125 次回测
- 耗时: ~2-4 小时

---

## 常用命令

### 评估特定年份

```bash
python main.py evaluate --mode annual --years 2024 2025
```

### 评估特定月份（跨年）

```bash
python main.py evaluate --mode monthly --years 2023 2024 2025 --months 1
```

### 季度评估

```bash
python main.py evaluate --mode quarterly --years 2024 2025
```

### 测试特定策略

```bash
python main.py evaluate \
  --mode annual \
  --years 2024 \
  --entry-strategies SimpleScorerStrategy \
  --exit-strategies LayeredExitStrategy BollingerDynamicExit
```

---

## 输出文件

评估完成后，在 `strategy_evaluation/` 目录生成：

1. **{prefix}_raw_{timestamp}.csv** - 原始结果
2. **{prefix}_by_regime_{timestamp}.csv** - 按市场环境分组
3. **{prefix}_report_{timestamp}.md** - 综合报告

---

## 市场环境分类

| 环境     | TOPIX 收益率 | 策略建议           |
| -------- | ------------ | ------------------ |
| 熊市     | < 0%         | 防御型、快速止损   |
| 温和牛市 | 0-25%        | 平衡型             |
| 强劲牛市 | 25-50%       | 趋势跟踪、延迟止盈 |
| 超级牛市 | 50-75%       | 动量策略           |
| 极端牛市 | > 75%        | 警惕泡沫           |

---

## 策略列表

### 入场策略（5 个）

- SimpleScorerStrategy
- EnhancedScorerStrategy
- MACDCrossoverStrategy
- BollingerSqueezeStrategy
- IchimokuStochStrategy

### 出场策略（5 个）

- ATRExitStrategy
- ScoreBasedExitStrategy
- LayeredExitStrategy
- BollingerDynamicExit
- ADXTrendExhaustionExit

---

## 故障排查

### 数据缺失

```bash
python main.py fetch --all  # 更新全部数据
```

### 查看可用策略

```bash
python -c "from src.utils.strategy_loader import ENTRY_STRATEGIES, EXIT_STRATEGIES; print('Entry:', list(ENTRY_STRATEGIES.keys())); print('Exit:', list(EXIT_STRATEGIES.keys()))"
```

### 测试单个回测

```bash
python main.py portfolio \
  --tickers 8306 \
  --entry-strategy SimpleScorerStrategy \
  --exit-strategy LayeredExitStrategy \
  --start 2024-01-01 \
  --end 2024-12-31
```

---

## 时间估算公式

**回测次数** = 时间段数 × 入场策略数 × 出场策略数

**耗时** ≈ 回测次数 × 5-10 秒

**示例:**

- 1 年 × 25 策略 = 25 次 → ~5 分钟
- 5 年 × 25 策略 = 125 次 → ~2-4 小时
- 12 月 × 25 策略 = 300 次 → ~5-8 小时

---

## Python API

```python
from src.evaluation import StrategyEvaluator, create_annual_periods

# 创建评价器
evaluator = StrategyEvaluator()

# 创建时间段
periods = create_annual_periods([2021, 2022, 2023])

# 运行评估
df = evaluator.run_evaluation(periods=periods)

# 分析
regime_analysis = evaluator.analyze_by_market_regime()
top_strategies = evaluator.get_top_strategies_by_regime(top_n=3)

# 保存
files = evaluator.save_results(prefix='my_eval')
```

---

## 报告解读

### 关键指标

- **return_pct**: 策略收益率
- **alpha**: 超额收益率（相对 TOPIX）
- **sharpe_ratio**: 夏普比率（风险调整后收益）
- **win_rate_pct**: 胜率
- **max_drawdown_pct**: 最大回撤

### 排名逻辑

- **单环境最优**: 该环境下 alpha 最高的策略
- **全天候策略**: 跨所有环境平均排名最靠前的策略

---

## 实战建议

### 首次使用流程

1. **快速测试**: `python test_strategy_evaluation.py` (15 分钟)
2. **查看报告**: 打开 `strategy_evaluation_test/test_evaluation_report_*.md`
3. **理解逻辑**: 阅读市场环境分类和 Top 策略
4. **完整评估**: `python main.py evaluate --mode annual --years 2021 2022 2023 2024 2025` (2-4 小时)
5. **应用决策**: 根据当前市场环境选择策略

### 定期评估

- **频率**: 季度或半年度
- **命令**: 评估最近 3-5 年数据
- **目的**: 动态调整策略组合

---

## 高级用法

### 自定义时间段

```bash
python main.py evaluate \
  --mode custom \
  --custom-periods '[
    ["疫情前","2019-01-01","2020-02-29"],
    ["疫情中","2020-03-01","2021-06-30"],
    ["疫情后","2021-07-01","2023-12-31"]
  ]'
```

### 指定输出目录

```bash
python main.py evaluate \
  --mode annual \
  --years 2024 \
  --output-dir my_analysis
```

---

## 更多信息

详细文档: [STRATEGY_EVALUATION_GUIDE.md](STRATEGY_EVALUATION_GUIDE.md)
