# 策略综合评价系统使用指南

## 概述

策略综合评价系统用于系统化地评估不同策略组合在不同市场环境下的表现，帮助识别"全天候策略"和"特定环境最优策略"。

### 核心功能

1. **批量回测**: 自动运行多个时间段 × 多个策略组合
2. **市场环境分类**: 根据 TOPIX 收益率将市场分为 5 类（熊市、温和牛市、强劲牛市、超级牛市、极端牛市）
3. **智能报告**: 生成 Markdown 报告 + CSV 原始数据
4. **灵活时间段**: 支持年度/季度/月度/自定义时间段

---

## 快速开始

### 1. 快速测试（推荐首次使用）

测试 2 个月数据，验证系统功能：

```bash
# 方法1: 使用测试脚本
python test_strategy_evaluation.py

# 方法2: 使用CLI
python main.py evaluate --mode monthly --years 2024 2025 --months 1
```

**预期结果:**

- 2 个月 × 25 个策略 = 50 次回测
- 耗时: ~10-15 分钟
- 输出: `strategy_evaluation_test/` 目录

### 2. 完整评估（生产环境）

评估 5 年完整数据：

```bash
# 方法1: 使用测试脚本
python test_strategy_evaluation.py --full

# 方法2: 使用CLI
python main.py evaluate --mode annual --years 2021 2022 2023 2024 2025
```

**预期结果:**

- 5 年 × 25 个策略 = 125 次回测
- 耗时: ~2-4 小时
- 输出: `strategy_evaluation/` 目录

---

## CLI 命令详解

### 基本语法

```bash
python main.py evaluate [OPTIONS]
```

### 参数说明

#### 必选参数

- `--mode {annual|quarterly|monthly|custom}`: 评估模式

  - `annual`: 整年评估（1 月 1 日-12 月 31 日）
  - `quarterly`: 季度评估（Q1-Q4）
  - `monthly`: 月度评估（1 月-12 月）
  - `custom`: 自定义时间段（需配合`--custom-periods`）

- `--years YEAR [YEAR ...]`: 年份列表
  - 示例: `--years 2021 2022 2023`

#### 可选参数

- `--months MONTH [MONTH ...]`: 指定月份（仅`monthly`模式）

  - 默认: 1-12（全部月份）
  - 示例: `--months 1 6 12` （只评估 1 月、6 月、12 月）

- `--custom-periods JSON`: 自定义时间段（仅`custom`模式）

  - 格式: `[["标签","开始日期","结束日期"], ...]`
  - 示例: `--custom-periods '[["2021-Q1","2021-01-01","2021-03-31"]]'`

- `--entry-strategies STRATEGY [STRATEGY ...]`: 指定入场策略

  - 默认: 全部 5 个策略
  - 可选值: `SimpleScorerStrategy`, `EnhancedScorerStrategy`, `MACDCrossoverStrategy`, `BollingerSqueezeStrategy`, `IchimokuStochStrategy`

- `--exit-strategies STRATEGY [STRATEGY ...]`: 指定出场策略

  - 默认: 全部 5 个策略
  - 可选值: `ATRExitStrategy`, `ScoreBasedExitStrategy`, `LayeredExitStrategy`, `BollingerDynamicExit`, `ADXTrendExhaustionExit`

- `--output-dir DIR`: 输出目录
  - 默认: `strategy_evaluation`

---

## 使用场景示例

### 场景 1: 测试特定策略组合

只评估 SimpleScorerStrategy 配合 3 个出场策略：

```bash
python main.py evaluate \
  --mode annual \
  --years 2023 2024 2025 \
  --entry-strategies SimpleScorerStrategy \
  --exit-strategies LayeredExitStrategy BollingerDynamicExit ADXTrendExhaustionExit
```

**回测次数**: 3 年 × 1 入场 × 3 出场 = 9 次

### 场景 2: 季度分析

评估每个季度的策略表现：

```bash
python main.py evaluate \
  --mode quarterly \
  --years 2024 2025
```

**回测次数**: 2 年 × 4 季度 × 25 策略 = 200 次

### 场景 3: 特定月份对比

比较每年 1 月的策略表现（快速测试）：

```bash
python main.py evaluate \
  --mode monthly \
  --years 2021 2022 2023 2024 2025 \
  --months 1
```

**回测次数**: 5 年 × 1 月 × 25 策略 = 125 次

### 场景 4: 自定义时间段

评估特定事件期间（例如：疫情前后）：

```bash
python main.py evaluate \
  --mode custom \
  --custom-periods '[
    ["疫情前","2019-01-01","2020-02-29"],
    ["疫情中","2020-03-01","2021-06-30"],
    ["疫情后","2021-07-01","2023-12-31"]
  ]'
```

---

## 输出文件说明

评估完成后，会在输出目录生成 3 个文件：

### 1. 原始结果 CSV

`{prefix}_raw_{timestamp}.csv`

包含所有回测的原始数据：

| 列名             | 说明                                         |
| ---------------- | -------------------------------------------- |
| period           | 时间段标签（如"2021"、"2024-Q1"、"2024-01"） |
| start_date       | 开始日期                                     |
| end_date         | 结束日期                                     |
| entry_strategy   | 入场策略                                     |
| exit_strategy    | 出场策略                                     |
| return_pct       | 策略收益率                                   |
| topix_return_pct | TOPIX 收益率                                 |
| alpha            | 超额收益率                                   |
| sharpe_ratio     | 夏普比率                                     |
| max_drawdown_pct | 最大回撤                                     |
| num_trades       | 交易次数                                     |
| win_rate_pct     | 胜率                                         |
| avg_gain_pct     | 平均盈利                                     |
| avg_loss_pct     | 平均亏损                                     |

### 2. 市场环境分析 CSV

`{prefix}_by_regime_{timestamp}.csv`

按市场环境分组的统计结果：

| 列名              | 说明         |
| ----------------- | ------------ |
| market_regime     | 市场环境分类 |
| entry_strategy    | 入场策略     |
| exit_strategy     | 出场策略     |
| return_pct_mean   | 平均收益率   |
| return_pct_std    | 收益率标准差 |
| alpha_mean        | 平均超额收益 |
| sharpe_ratio_mean | 平均夏普比率 |
| sample_count      | 样本数量     |

### 3. Markdown 综合报告

`{prefix}_report_{timestamp}.md`

包含：

- **总体概览**: 评估时段、策略数量、回测次数
- **时段 TOPIX 表现**: 每个时段的市场环境分类
- **按市场环境分类的最优策略**: 每种市场环境的 Top 3 策略
- **全天候策略推荐**: 基于跨市场环境平均排名的推荐

---

## 市场环境分类标准

系统根据 TOPIX 收益率将市场分为 5 类：

| 市场环境 | TOPIX 收益率范围 | 特点               |
| -------- | ---------------- | ------------------ |
| 熊市     | < 0%             | 下跌市场，防御为主 |
| 温和牛市 | 0% - 25%         | 稳定上涨，适度参与 |
| 强劲牛市 | 25% - 50%        | 强势上涨，积极参与 |
| 超级牛市 | 50% - 75%        | 极强趋势，注意泡沫 |
| 极端牛市 | > 75%            | 罕见极端行情       |

---

## 评价逻辑

### 1. 单环境最优策略

- 在特定市场环境下，按 alpha 排序
- 适用场景: 明确判断市场环境时选择策略

### 2. 全天候策略

- 计算每个策略组合在所有市场环境中的平均排名
- 平均排名最靠前的策略 = 全天候策略
- 适用场景: 无法准确判断市场环境时的默认策略

---

## Python API 使用

如果需要在代码中调用评价系统：

```python
from src.evaluation import (
    StrategyEvaluator,
    create_annual_periods,
    create_monthly_periods
)

# 创建评价器
evaluator = StrategyEvaluator(
    data_root='data',
    output_dir='my_evaluation'
)

# 创建时间段
periods = create_annual_periods([2021, 2022, 2023])

# 运行评估
df_results = evaluator.run_evaluation(
    periods=periods,
    entry_strategies=['SimpleScorerStrategy'],
    exit_strategies=['LayeredExitStrategy', 'BollingerDynamicExit']
)

# 按市场环境分析
regime_analysis = evaluator.analyze_by_market_regime()

# 获取每种环境的最优策略
top_strategies = evaluator.get_top_strategies_by_regime(top_n=3)

# 保存结果
files = evaluator.save_results(prefix='my_evaluation')
```

---

## 注意事项

### 1. 数据完整性检查

评估前确保：

- `data/features/` 目录包含所有监视列表股票的数据
- `data/benchmarks/` 目录包含 TOPIX 基准数据
- 数据覆盖评估时间段

检查命令：

```bash
python main.py fetch --all  # 更新全部数据
```

### 2. 时间估算

回测次数 = 时间段数 × 入场策略数 × 出场策略数

单次回测耗时：~5-10 秒（取决于数据大小和交易频率）

**示例：**

- 5 年 × 5 入场 × 5 出场 = 125 次 → ~2-4 小时
- 2 月 × 5 入场 × 5 出场 = 50 次 → ~10-15 分钟
- 1 年 × 1 入场 × 3 出场 = 3 次 → ~1 分钟

### 3. 内存使用

每个回测会加载：

- 61 支股票的特征数据
- 交易记录和财务数据
- TOPIX 基准数据

推荐配置：

- 内存: ≥8GB
- 磁盘空间: ≥2GB（数据存储）

### 4. 错误处理

如果某个策略组合回测失败：

- 系统会跳过该组合，继续下一个
- 最终报告会反映实际成功的回测数量
- 检查日志查看失败原因

---

## 实战案例

### 案例 1: 2024-2025 市场验证

**目标**: 验证 2024-2025 年哪些策略表现最好

```bash
python main.py evaluate --mode annual --years 2024 2025
```

**预期输出**:

- 判断 2024-2025 市场环境（温和牛市 vs 强劲牛市）
- 识别该环境下的 Top 3 策略
- 对比 25 个策略的 alpha 分布

### 案例 2: 季节性分析

**目标**: 研究 1 月、4 月、7 月、10 月的策略表现差异

```bash
python main.py evaluate \
  --mode monthly \
  --years 2021 2022 2023 2024 2025 \
  --months 1 4 7 10
```

**回测次数**: 5 年 × 4 月 × 25 策略 = 500 次（约 3-5 小时）

### 案例 3: 快速 A/B 测试

**目标**: 对比两个新策略 vs 现有最佳策略

```bash
python main.py evaluate \
  --mode monthly \
  --years 2025 \
  --months 1 \
  --entry-strategies NewStrategy1 NewStrategy2 SimpleScorerStrategy \
  --exit-strategies LayeredExitStrategy
```

**回测次数**: 1 年 × 1 月 × 3 入场 × 1 出场 = 3 次（约 1 分钟）

---

## FAQ

### Q1: 为什么要按市场环境分类？

**A**: 不同策略在不同市场环境下表现差异巨大。例如：

- 熊市: 防御型策略（快速止损）表现更好
- 强劲牛市: 趋势跟踪策略（延迟止盈）表现更好

按环境分类可以实现"择时选策略"。

### Q2: 什么是"全天候策略"？

**A**: 在所有市场环境下都相对稳健的策略。虽然不是每种环境的最优，但：

- 避免了"择时失误"的风险
- 适合长期投资者
- 简化决策流程

### Q3: 如何解读报告中的"平均排名"？

**A**: 平均排名 = 该策略在所有市场环境中的 alpha 排名的平均值

**示例:**

- 策略 A: 熊市排名 1, 牛市排名 10 → 平均排名 5.5
- 策略 B: 熊市排名 3, 牛市排名 3 → 平均排名 3.0

策略 B 是更好的"全天候策略"（平均排名更小）。

### Q4: 可以评估自定义策略吗？

**A**: 可以！步骤：

1. 创建新策略类（继承`BaseScorer`或`BaseExiter`）
2. 在`src/utils/strategy_loader.py`中注册
3. 使用`--entry-strategies`或`--exit-strategies`指定

### Q5: 评估结果如何用于实盘？

**A**: 建议流程：

1. 运行完整 5 年评估，识别全天候策略
2. 分析当前市场环境（TOPIX 近期收益率）
3. 选择该环境下的最优策略 OR 全天候策略
4. 定期（季度/半年）重新评估，动态调整

---

## 技术实现说明

### 架构设计

系统采用"编排而非修改"的设计理念：

```
StrategyEvaluator (评价器)
    ↓ 调用
PortfolioBacktestEngine (组合回测引擎)
    ↓ 使用
StockDataManager (数据管理器) + BenchmarkManager (基准管理器)
```

- **零侵入**: 不修改任何现有核心代码
- **纯编排**: 仅调用现有 API
- **独立输出**: 结果保存在独立目录

### 数据流

1. 加载监视列表 (`data/monitor_list.json`)
2. 遍历时间段和策略组合
3. 调用 `PortfolioBacktestEngine.run_backtest()`
4. 获取 TOPIX 收益率 (`BenchmarkManager.calculate_benchmark_return()`)
5. 构造 `AnnualStrategyResult` 对象
6. 聚合、分组、排序
7. 生成 Markdown + CSV

### 性能优化

- 使用 DataFrame 批量操作（避免循环）
- 缓存 TOPIX 基准数据
- 支持增量评估（指定部分策略）

---

## 更新日志

### v1.0.0 (2026-01-16)

- ✅ 初始版本发布
- ✅ 支持年度/季度/月度/自定义时间段
- ✅ 5 种市场环境分类
- ✅ Markdown + CSV 双输出
- ✅ 全天候策略推荐算法

---

## 联系与反馈

如遇问题或有改进建议，请通过以下方式反馈：

- GitHub Issues
- 项目文档更新请求

**祝交易顺利！📈**
