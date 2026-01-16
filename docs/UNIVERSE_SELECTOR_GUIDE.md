# Universe Selector - 使用指南

## 概述

Universe Selector 是一个从大量股票中筛选出最适合交易的股票池的工具。它基于**流动性**、**波动率**和**趋势强度**三个维度进行综合评分和排名。

## 设计哲学

### 筛选流程

```
输入股票池 (N支)
    ↓
Phase 1: 硬过滤 (Hard Filters)
├─ 最低价格 > 100 JPY (排除仙股)
├─ 流动性 > 500M JPY (20日中位数)
└─ 波动率 1.5% < ATR Ratio < 5.0% (安全范围)
    ↓
Phase 2: 归一化 (Normalization)
├─ Rank_Vol (波动率百分位排名 0-1)
├─ Rank_Liq (流动性百分位排名 0-1)
└─ Rank_Trend (趋势强度百分位排名 0-1)
    ↓
Phase 3: 加权评分 (Weighted Scoring)
TotalScore = 0.4×Rank_Vol + 0.3×Rank_Liq + 0.3×Rank_Trend
    ↓
Phase 4: Top N 选择
输出前50名
```

### 评分权重

| 维度 | 权重 | 理由 |
|------|------|------|
| **波动率** | 40% | 核心盈利驱动因素 - 更高的日内波动=更多交易机会 |
| **流动性** | 30% | 安全保障 - 确保可以无滑点进出 |
| **趋势强度** | 30% | 方向性加成 - "强者恒强"，顺势而为 |

## 快速开始

### 1. 测试模式（推荐先运行）

使用monitor_list中的股票进行快速测试：

```bash
python test_universe_selector.py
```

这会：
- 使用现有监视列表中的10支股票
- 选出Top 5
- 保存结果到 `data/universe/`

### 2. 生产模式 - 使用文件提供股票池

#### 方法A: 使用JSON格式

创建 `my_universe.json`:
```json
{
  "codes": [
    "8035",
    "8306",
    "7974",
    ...
  ]
}
```

运行选股：
```bash
python run_universe_selector.py --universe-file data/universe/my_universe.json --top-n 50
```

#### 方法B: 使用TXT格式

创建 `my_universe.txt`:
```
# 我的股票池
8035
8306
7974
7011
...
```

运行选股：
```bash
python run_universe_selector.py --universe-file data/universe/my_universe.txt --top-n 50
```

### 3. 生产模式 - 从API获取全市场（需要API权限）

```bash
# 直接从JQuants API获取所有上市股票（约4000支）
python run_universe_selector.py --top-n 50
```

**注意**: 此方法需要API的 `/v1/listed/info` 端点权限，且会耗时较长（约1小时，受API速率限制）。

## 输出结果

### JSON格式 (可直接用作monitor_list)

```json
{
  "version": "1.0",
  "selection_date": "2026-01-15 15:40:41",
  "description": "Top 50 stocks selected by Universe Selector",
  "selection_criteria": {
    "min_price": 100,
    "min_liquidity": 500000000,
    "atr_ratio_range": [0.015, 0.05],
    "weights": {
      "volatility": 0.4,
      "liquidity": 0.3,
      "trend": 0.3
    }
  },
  "tickers": [
    {
      "code": "8035",
      "name": "Tokyo Electron",
      "rank": 1,
      "total_score": 0.93,
      "rank_vol": 0.9,
      "rank_liq": 0.9,
      "rank_trend": 1.0,
      "atr_ratio": 0.0327,
      "median_turnover": 87338699500.0,
      "trend_strength": 0.487,
      "close_price": 42310.0,
      "selected_date": "2026-01-15"
    },
    ...
  ]
}
```

### CSV格式 (用于分析)

| Rank | Code | CompanyName | TotalScore | Rank_Vol | Rank_Liq | Rank_Trend | Close | ATR_Ratio | MedianTurnover | TrendStrength |
|------|------|-------------|------------|----------|----------|------------|-------|-----------|----------------|---------------|
| 1 | 8035 | Stock_8035 | 0.93 | 0.9 | 0.9 | 1.0 | 42310.0 | 0.0327 | 87338699500.0 | 0.487 |

## 高级用法

### 调整筛选参数

编辑 `src/universe/stock_selector.py` 中的配置：

```python
# Hard Filter Thresholds
MIN_PRICE = 100  # JPY - 调高可排除更多低价股
MIN_LIQUIDITY = 500_000_000  # 500M JPY - 调高获得更高流动性
MIN_ATR_RATIO = 0.015  # 1.5% - 最小波动率
MAX_ATR_RATIO = 0.050  # 5.0% - 最大波动率

# Scoring Weights
WEIGHT_VOLATILITY = 0.4  # 波动率权重
WEIGHT_LIQUIDITY = 0.3   # 流动性权重
WEIGHT_TREND = 0.3       # 趋势强度权重
```

### 自动替换monitor_list

运行后会询问是否保存为新的monitor_list.json：

```bash
python run_universe_selector.py --universe-file my_universe.json

# 完成后会提示：
❓ Save top results as new monitor_list.json? (y/n): y
✅ Backed up existing monitor_list to data/monitor_list_backup.json
✅ Saved top 50 stocks as new monitor_list.json
```

## 数据复用

Universe Selector 完全复用现有架构：

| 功能 | 复用模块 |
|------|---------|
| OHLC数据获取 | `StockDataManager.fetch_and_update_ohlc()` |
| 技术指标计算 | `StockDataManager.compute_features()` (ATR, EMA_200等) |
| 增量更新 | Data Lake的增量更新机制 |
| API速率控制 | `JQuantsV2Client` 的内置限速 |

## 性能估算

| 股票数量 | 预计耗时 | 说明 |
|---------|---------|------|
| 10支 (测试) | ~10秒 | 每支股票约1秒（增量更新） |
| 100支 | ~2分钟 | 适合行业板块筛选 |
| 1000支 | ~20分钟 | 大规模筛选 |
| 4000支 (全市场) | ~1小时 | 受API速率限制（1 req/sec） |

**优化建议**：
- 首次运行使用测试模式验证逻辑
- 定期更新（每周）可利用增量更新机制加速
- 已有数据的股票只需要更新最新数据，非常快

## 故障排查

### "401 Unauthorized" API错误

- **原因**: `/v1/listed/info` 端点可能需要更高级别的API权限
- **解决**: 使用 `--universe-file` 参数提供股票代码列表

### "Insufficient data" 警告

- **原因**: 某些股票历史数据不足250天（需要计算MA200）
- **解决**: 这些股票会自动跳过，不影响整体流程

### SettingWithCopyWarning

- **已修复**: 使用 `.copy()` 显式创建DataFrame副本

## 与现有功能集成

### 作为backtest输入

```python
# 1. 运行选股
python run_universe_selector.py --top-n 50

# 2. 结果会自动保存为JSON，可直接用作monitor_list

# 3. 运行backtest
python main.py backtest --strategy SimpleScorer+ATRExiter
```

### 定期更新工作流

```bash
# 每周日执行
python run_universe_selector.py --universe-file my_4000_stocks.json --top-n 50

# 自动替换monitor_list
# (在脚本中选择 y)

# 抓取最新数据
python src/main.py

# 运行回测验证
python main.py backtest
```

## 技术指标说明

### ATR Ratio (波动率比率)
```
ATR_Ratio = ATR(14) / Close
```
- **含义**: 日均波动幅度占股价的百分比
- **示例**: ATR=100, Close=3000 → Ratio=3.33%
- **理想范围**: 1.5% - 5.0%

### Median Turnover (中位成交额)
```
TradingValue = Close × Volume
MedianTurnover = median(TradingValue[-20天])
```
- **含义**: 近20天成交额的中位数
- **门槛**: > 500M JPY

### Trend Strength (趋势强度)
```
TrendStrength = (Close - EMA_200) / EMA_200
```
- **含义**: 当前价格相对200日均线的偏离度
- **示例**: 
  - +0.20 = 比均线高20% (强势)
  - -0.10 = 比均线低10% (弱势)

## 常见问题

**Q: 为什么选50支而不是100支？**
A: 基于组合管理考虑。50支股票足够分散风险，同时保持可管理性。可通过 `--top-n` 参数调整。

**Q: 可以改变权重吗？**
A: 可以。编辑 `stock_selector.py` 中的 `WEIGHT_*` 常量。确保三个权重之和为1.0。

**Q: 多久更新一次Universe？**
A: 建议每周更新一次。市场结构变化较慢，无需每日更新。

**Q: 能否排除特定行业？**
A: 可以。在 `_filter_equity_only()` 函数中添加行业过滤逻辑（需要API返回行业信息）。

## 下一步优化方向

1. **行业平衡**: 添加行业分散度约束（每行业最多N支）
2. **动态权重**: 根据市场环境调整三个维度的权重
3. **机器学习**: 使用历史回测结果优化权重和阈值
4. **实时监控**: 跟踪Top 50的排名变化，及时调整持仓

## 参考文献

- [DATA_LAKE_GUIDE.md](../DATA_LAKE_GUIDE.md) - 数据架构说明
- [USAGE_GUIDE.md](../USAGE_GUIDE.md) - 系统整体使用指南
