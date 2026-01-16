# 项目架构整理方案

## 📋 整理目标

基于 3 个核心功能重新组织项目：

1. **数据抓取** - 从 JQuants 获取股票数据
2. **策略判定** - 入场与出场策略（实时信号生成）
3. **策略回测** - 单股票和组合投资回测

---

## 🗂️ 文件重命名与删除计划

### ✅ 第一步：重命名核心文件

| 当前文件名    | 新文件名                    | 说明                                 |
| ------------- | --------------------------- | ------------------------------------ |
| `src/main.py` | `src/data_fetch_manager.py` | 数据抓取管理器                       |
| -             | `main.py`（新建）           | **新的项目入口** - 提供 CLI 选择功能 |

### ❌ 第二步：删除冗余代码

| 删除文件/文件夹                    | 原因                            |
| ---------------------------------- | ------------------------------- |
| `src/analysis/scorers/` 整个文件夹 | 已被 `strategies/entry/` 替代   |
| `src/analysis/exiters/` 整个文件夹 | 已被 `strategies/exit/` 替代    |
| `test_backtest.py`                 | 功能与 `start_backtest.py` 重复 |
| `test_scorer.py`                   | 临时测试脚本，已验证完成        |
| `test_exit.py`                     | 临时测试脚本，已验证完成        |
| `test_new_strategies.py`           | 临时测试脚本，已验证完成        |
| `test_beta_ir.py`                  | 临时测试脚本，已验证完成        |

### 🔄 第三步：整合和简化

| 操作 | 文件                     | 说明                             |
| ---- | ------------------------ | -------------------------------- |
| 整合 | `quick_backtest.py`      | 合并到新 `main.py` 作为 CLI 选项 |
| 保留 | `generate_strategies.py` | 作为独立工具保留                 |
| 保留 | `check_scores.py`        | 作为独立诊断工具                 |
| 保留 | `examples.py`            | 文档示例                         |

---

## 🏗️ 新的项目架构

```
j-stock-analyzer/
├── main.py ⭐ NEW - 统一入口CLI
├── config.json ⭐ NEW - 简化的单一配置文件
│
├── src/
│   ├── data_fetch_manager.py ⭐ RENAMED (from main.py)
│   │
│   ├── data/                      # 📦 模块1: 数据抓取
│   │   ├── pipeline.py
│   │   ├── stock_data_manager.py
│   │   ├── candidate_manager.py
│   │   └── benchmark_manager.py
│   │
│   ├── analysis/                  # 📊 模块2: 策略判定
│   │   ├── signals.py             # 核心数据结构
│   │   ├── scoring_utils.py       # 打分工具
│   │   ├── technical_indicators.py # 技术指标
│   │   │
│   │   └── strategies/            # ✅ 保留
│   │       ├── entry/
│   │       │   ├── base_entry_strategy.py
│   │       │   ├── scorer_strategy.py
│   │       │   └── macd_crossover.py
│   │       └── exit/
│   │           ├── base_exit_strategy.py
│   │           ├── atr_exit.py
│   │           ├── score_based_exit.py
│   │           └── layered_exit.py
│   │
│   ├── backtest/                  # 🔄 模块3: 策略回测
│   │   ├── engine.py              # 单股票回测
│   │   ├── portfolio_engine.py    # 组合回测
│   │   ├── portfolio.py
│   │   ├── signal_ranker.py
│   │   ├── lot_size_manager.py
│   │   ├── models.py
│   │   ├── metrics.py
│   │   └── report.py
│   │
│   └── client/
│       └── jquants_client.py
│
├── data/
│   └── monitor_list.txt ⭐ NEW - 简化的股票代码列表
│
├── tools/ ⭐ NEW - 独立工具脚本
│   ├── generate_strategies.py
│   └── check_scores.py
│
└── tests/                          # 单元测试
    ├── test_technical_indicators.py
    └── test_stock_data_manager.py
```

---

## 📝 配置文件简化

### ❌ 删除复杂配置

- `backtest_config.json` → 删除
- `portfolio_config.json` → 删除
- `data/monitor_list.json` → 删除

### ✅ 新的简化配置

#### `config.json` - 统一配置文件

```json
{
  "data": {
    "monitor_list_file": "data/monitor_list.txt",
    "data_dir": "data"
  },

  "backtest": {
    "start_date": "2021-01-01",
    "end_date": "2026-01-08",
    "starting_capital_jpy": 5000000,
    "output_dir": "backtest_results"
  },

  "portfolio": {
    "max_positions": 5,
    "max_position_pct": 0.3,
    "min_position_pct": 0.05,
    "output_dir": "portfolio_backtest_results"
  },

  "lot_sizes": {
    "1321": 1,
    "1343": 1,
    "default": 100
  },

  "default_strategies": {
    "entry": "SimpleScorerStrategy",
    "exit": "ATRExitStrategy"
  }
}
```

#### `data/monitor_list.txt` - 简化的监视列表

```
# 监视股票代码列表 (每行一个代码)
# 半导体
8035
# 金融
8306
# 游戏
7974
# 防卫
7011
# 自动化
6861
# 商社
8058
# 制造
6501
# 医药
4063
# 汽车
7203
# REIT
1321
```

---

## 🎯 新的 main.py CLI 设计

```python
"""
J-Stock-Analyzer - 统一入口
"""
import argparse

def main():
    parser = argparse.ArgumentParser(description='J-Stock-Analyzer')
    subparsers = parser.add_subparsers(dest='command')

    # 1. 数据抓取
    fetch_parser = subparsers.add_parser('fetch', help='抓取股票数据')
    fetch_parser.add_argument('--tickers', nargs='+', help='指定股票代码')
    fetch_parser.add_argument('--all', action='store_true', help='抓取监视列表所有股票')

    # 2. 策略信号
    signal_parser = subparsers.add_parser('signal', help='生成交易信号')
    signal_parser.add_argument('ticker', help='股票代码')
    signal_parser.add_argument('--date', help='指定日期 (默认今天)')
    signal_parser.add_argument('--entry', default='SimpleScorerStrategy')
    signal_parser.add_argument('--exit', default='ATRExitStrategy')

    # 3. 单股票回测
    backtest_parser = subparsers.add_parser('backtest', help='单股票回测')
    backtest_parser.add_argument('ticker', help='股票代码')
    backtest_parser.add_argument('--entry', default='SimpleScorerStrategy')
    backtest_parser.add_argument('--exit', default='ATRExitStrategy')
    backtest_parser.add_argument('--start', default='2021-01-01')
    backtest_parser.add_argument('--end', default='2026-01-08')

    # 4. 组合回测
    portfolio_parser = subparsers.add_parser('portfolio', help='组合投资回测')
    portfolio_parser.add_argument('--tickers', nargs='+', help='股票代码列表')
    portfolio_parser.add_argument('--all', action='store_true', help='使用监视列表所有股票')
    portfolio_parser.add_argument('--entry', default='SimpleScorerStrategy')
    portfolio_parser.add_argument('--exit', default='ATRExitStrategy')

    args = parser.parse_args()

    if args.command == 'fetch':
        from src.data_fetch_manager import run_data_fetch
        run_data_fetch(args)
    elif args.command == 'signal':
        from src.signal_generator import generate_signal
        generate_signal(args)
    elif args.command == 'backtest':
        from src.backtest.engine import run_single_backtest
        run_single_backtest(args)
    elif args.command == 'portfolio':
        from src.backtest.portfolio_engine import run_portfolio_backtest
        run_portfolio_backtest(args)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
```

### 使用示例

```bash
# 数据抓取
python main.py fetch --all
python main.py fetch --tickers 7974 8035

# 生成今日信号
python main.py signal 7974
python main.py signal 7974 --date 2026-01-10

# 单股票回测
python main.py backtest 7974
python main.py backtest 7974 --entry EnhancedScorerStrategy --exit LayeredExitStrategy

# 组合回测
python main.py portfolio --all
python main.py portfolio --tickers 7974 8035 6501
```

---

## 🚀 执行步骤

### Phase 1: 删除冗余代码 ✅

1. 删除 `src/analysis/scorers/`
2. 删除 `src/analysis/exiters/`
3. 删除临时测试脚本 (`test_*.py` 除了 tests/ 下的)

### Phase 2: 重命名核心文件 ✅

1. `src/main.py` → `src/data_fetch_manager.py`
2. 更新内部导入

### Phase 3: 简化配置 ✅

1. 创建 `config.json`
2. 创建 `data/monitor_list.txt`
3. 删除旧配置文件

### Phase 4: 创建新入口 ✅

1. 创建新的 `main.py` CLI
2. 创建 `src/signal_generator.py` (策略判定模块)
3. 移动工具脚本到 `tools/`

### Phase 5: 测试验证 ✅

1. 测试数据抓取
2. 测试信号生成
3. 测试单股票回测
4. 测试组合回测

---

## 🎁 扩展性设计

### 添加新指标

```python
# src/analysis/indicators/custom_indicator.py
def calculate_my_indicator(prices, params):
    """新的技术指标"""
    pass

# 在 scoring_utils.py 中使用
from src.analysis.indicators.custom_indicator import calculate_my_indicator
```

### 添加新策略

```python
# src/analysis/strategies/entry/my_strategy.py
from src.analysis.strategies.base_entry_strategy import BaseEntryStrategy

class MyCustomStrategy(BaseEntryStrategy):
    def generate_signal(self, market_data):
        # 实现你的策略逻辑
        pass
```

然后在 CLI 中使用：

```bash
python main.py backtest 7974 --entry MyCustomStrategy
```

---

## ✅ 验收标准

- [ ] 项目启动只需 `python main.py`
- [ ] 配置文件简单直观（JSON 和 TXT）
- [ ] 无重复代码（scorers/exiters 删除）
- [ ] 模块清晰分离（数据/策略/回测）
- [ ] 易于扩展（添加新指标和策略）
- [ ] 向后兼容（旧的回测结果依然有效）

---

**生成时间**: 2026-01-14
**状态**: 待用户确认后执行
