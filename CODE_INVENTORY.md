# Python代码清单 - 完整函数和类列表

## 📁 根目录脚本

### 🚀 主要入口脚本

| 文件名 | 主要函数/类 | 功能说明 |
|-------|-----------|---------|
| **start_backtest.py** | `OutputRedirector`, `load_config()`, `parse_strategies()`, `run_backtest_from_config()`, `main()` | **单股票回测入口** - 全仓交易回测系统 |
| **start_portfolio_backtest.py** | `OutputRedirector`, `load_config()`, `parse_strategies()`, `run_portfolio_backtest_from_config()`, `main()` | **组合投资回测入口** - 多股票分散投资回测系统 |
| **quick_backtest.py** | `list_strategies()`, `parse_strategies()`, `main()` | **快速回测工具** - 命令行快速回测 |

### 🧪 测试脚本

| 文件名 | 主要函数/类 | 功能说明 |
|-------|-----------|---------|
| **test_backtest.py** | `OutputRedirector`, `load_config()`, `parse_strategies()`, `main()` | 回测功能测试 |
| **test_scorer.py** | `load_stock_data()`, `test_single_ticker()`, `test_all_monitor_list()`, `compare_scorers()`, `main()` | 打分器测试 - 测试SimpleScorer和EnhancedScorer |
| **test_exit.py** | `load_stock_data()`, `create_sample_position()`, `test_exit_strategy()`, `compare_exit_strategies()`, `test_your_position()`, `main()` | 出场策略测试 - 测试ATR/LayeredExit |
| **test_new_strategies.py** | `test_strategy_combination()`, `main()` | 新策略组合测试 |
| **test_beta_ir.py** | (待检查) | Beta和信息比率测试 |

### 🛠️ 工具脚本

| 文件名 | 主要函数/类 | 功能说明 |
|-------|-----------|---------|
| **check_scores.py** | (main script) | **诊断工具** - 检查股票历史得分分布 |
| **generate_strategies.py** | `generate_all_combinations()` | **策略生成器** - 自动生成Entry×Exit组合配置 |
| **examples.py** | `example_single_stock_etl()`, `example_batch_processing()`, `example_read_data_lake()`, `example_incremental_update()`, `example_custom_features()`, `example_daily_workflow()`, `example_screening()` | **使用示例集** - 各种功能的示例代码 |

---

## 📦 src/backtest/ - 回测引擎

### 核心回测引擎

| 文件名 | 主要类/函数 | 功能说明 |
|-------|-----------|---------|
| **engine.py** | `BacktestEngine`, `backtest_strategy()`, `backtest_strategies()`, `calculate_benchmark_return()` | **单股票回测引擎** - 全仓交易逻辑 |
| **portfolio_engine.py** | `PortfolioBacktestEngine` | **组合回测引擎** - 多股票分散投资逻辑 |
| **models.py** | `Trade`, `BacktestResult` | 回测数据模型 - 交易记录和结果 |
| **metrics.py** | `calculate_sharpe_ratio()`, `calculate_max_drawdown()`, `calculate_equity_curve()`, `calculate_profit_factor()`, `calculate_annualized_return()`, `calculate_beta()`, `calculate_tracking_error_and_ir()`, `calculate_trade_statistics()` | **性能指标计算** - 夏普比率、最大回撤、Beta等 |
| **report.py** | `create_comparison_table()`, `find_best_strategy()`, `aggregate_by_strategy()`, `print_summary_report()` | 回测报告生成 |

### 组合投资组件

| 文件名 | 主要类 | 功能说明 |
|-------|-------|---------|
| **portfolio.py** | `Position`, `Portfolio` | **组合管理器** - 多持仓管理、资金分配 |
| **signal_ranker.py** | `SignalRanker` | **信号排序器** - 买入信号优先级排序 |
| **lot_size_manager.py** | `LotSizeManager` | **购买单位管理** - REIT 1股/普通股100股 |

---

## 📊 src/analysis/ - 分析模块

### 信号和数据模型

| 文件名 | 主要类 | 功能说明 |
|-------|-------|---------|
| **signals.py** | `SignalAction` (Enum), `TradingSignal`, `MarketData`, `Position` | **核心数据结构** - 信号、市场数据、持仓 |

### 入场策略 (src/analysis/strategies/entry/)

| 文件名 | 主要类 | 功能说明 |
|-------|-------|---------|
| **base_entry_strategy.py** | `BaseEntryStrategy` (ABC) | 入场策略抽象基类 |
| **scorer_strategy.py** | `SimpleScorerStrategy`, `EnhancedScorerStrategy` | **综合打分策略** - Simple权重 vs Enhanced权重 |
| **macd_crossover.py** | `MACDCrossoverStrategy` | **MACD交叉策略** - 技术指标入场 |

### 出场策略 (src/analysis/strategies/exit/)

| 文件名 | 主要类 | 功能说明 |
|-------|-------|---------|
| **base_exit_strategy.py** | `BaseExitStrategy` (ABC) | 出场策略抽象基类 |
| **atr_exit.py** | `ATRExitStrategy` | **ATR技术出场** - HardStop/TrailingStop/TrendBreakdown |
| **score_based_exit.py** | `ScoreBasedExitStrategy` | **分数衰减出场** - 基于得分变化 |
| **layered_exit.py** | `LayeredExitStrategy` | **分层出场** - 5层风险控制（Emergency/HardStop/TrendBreakdown等） |

### 打分工具

| 文件名 | 主要函数 | 功能说明 |
|-------|---------|---------|
| **scoring_utils.py** | `calculate_technical_score()`, `calculate_institutional_score()`, `calculate_fundamental_score()`, `calculate_volatility_score()`, `calculate_composite_score()`, `check_earnings_risk()`, `detect_institutional_exodus()`, `detect_trend_breakdown()`, `detect_market_deterioration()` | **综合打分工具集** - 技术/机构/基本面/波动率评分 |
| **technical_indicators.py** | `calculate_ema()`, `calculate_rsi()`, `calculate_macd()`, `calculate_atr()` | **技术指标计算** - EMA/RSI/MACD/ATR |

### 旧版打分器 (已弃用?)

| 文件名 | 主要类 | 功能说明 | 状态 |
|-------|-------|---------|------|
| **scorers/base_scorer.py** | `BaseScorer` (ABC), `ScoreResult` | 旧版打分器基类 | ⚠️ 可能已被strategies/替代 |
| **scorers/simple_scorer.py** | `SimpleScorer` | 旧版Simple打分器 | ⚠️ 可能已被scorer_strategy.py替代 |
| **scorers/enhanced_scorer.py** | `EnhancedScorer` | 旧版Enhanced打分器 | ⚠️ 可能已被scorer_strategy.py替代 |

### 旧版出场器 (已弃用?)

| 文件名 | 主要类 | 功能说明 | 状态 |
|-------|-------|---------|------|
| **exiters/base_exiter.py** | `BaseExiter` (ABC), `ExitSignal`, `Position` | 旧版出场器基类 | ⚠️ 可能已被strategies/exit/替代 |
| **exiters/atr_exiter.py** | `ATRExiter` | 旧版ATR出场器 | ⚠️ 可能已被atr_exit.py替代 |
| **exiters/layered_exiter.py** | `LayeredExiter` | 旧版分层出场器 | ⚠️ 可能已被layered_exit.py替代 |

---

## 💾 src/data/ - 数据管理

| 文件名 | 主要类/函数 | 功能说明 |
|-------|-----------|---------|
| **pipeline.py** | `StockETLPipeline`, `run_daily_update()`, `run_weekly_full_sync()` | **ETL管道** - 数据提取、转换、加载 |
| **stock_data_manager.py** | `StockDataManager` | 股票数据管理器 - 读取/保存数据 |
| **candidate_manager.py** | `CandidateManager`, `CandidateResult` | 候选股票管理 - 筛选和评分 |
| **benchmark_manager.py** | `BenchmarkManager`, `update_benchmarks()` | **TOPIX基准管理** - 基准数据下载和管理 |

---

## 🔌 src/client/ - API客户端

| 文件名 | 主要类 | 功能说明 |
|-------|-------|---------|
| **jquants_client.py** | `JQuantsV2Client` | **J-Quants API客户端** - 获取日本股票数据 |

---

## ⚙️ src/config/ - 配置

| 文件名 | 内容 | 功能说明 |
|-------|-----|---------|
| **settings.py** | (待检查) | 全局配置设置 |

---

## 🧰 src/utils/ - 工具函数

| 文件名 | 主要函数 | 功能说明 |
|-------|---------|---------|
| **helpers.py** | `some_utility_function()`, `another_utility_function()` | 通用工具函数 |

---

## 🧪 tests/ - 单元测试

| 文件名 | 主要类 | 功能说明 |
|-------|-------|---------|
| **test_technical_indicators.py** | `TestTechnicalIndicators` | 技术指标单元测试 |
| **test_stock_data_manager.py** | `TestStockDataManager` | 数据管理器单元测试 |

---

## 🔍 重复/冗余代码识别

### ⚠️ 可能的重复：scorers/ vs strategies/entry/

| 旧版 (scorers/) | 新版 (strategies/entry/) | 建议 |
|----------------|------------------------|------|
| `simple_scorer.py` → `SimpleScorer` | `scorer_strategy.py` → `SimpleScorerStrategy` | **合并或删除旧版** |
| `enhanced_scorer.py` → `EnhancedScorer` | `scorer_strategy.py` → `EnhancedScorerStrategy` | **合并或删除旧版** |
| `base_scorer.py` → `BaseScorer` | `base_entry_strategy.py` → `BaseEntryStrategy` | **统一接口** |

### ⚠️ 可能的重复：exiters/ vs strategies/exit/

| 旧版 (exiters/) | 新版 (strategies/exit/) | 建议 |
|----------------|------------------------|------|
| `atr_exiter.py` → `ATRExiter` | `atr_exit.py` → `ATRExitStrategy` | **合并或删除旧版** |
| `layered_exiter.py` → `LayeredExiter` | `layered_exit.py` → `LayeredExitStrategy` | **合并或删除旧版** |
| `base_exiter.py` → `BaseExiter` | `base_exit_strategy.py` → `BaseExitStrategy` | **统一接口** |

### 📝 Position类重复

| 位置 | 说明 |
|-----|------|
| `src/analysis/signals.py` → `Position` | 策略使用的Position |
| `src/backtest/portfolio.py` → `Position` | 组合投资使用的Position |
| `src/analysis/exiters/base_exiter.py` → `Position` | 旧版Exiter的Position |

**建议**: 统一使用 `src/analysis/signals.py` 中的Position定义

---

## 📊 统计总结

- **总Python文件数**: ~60个
- **主要入口脚本**: 3个 (start_backtest.py, start_portfolio_backtest.py, quick_backtest.py)
- **测试脚本**: 7个
- **工具脚本**: 3个
- **核心类数量**: ~40个
- **主要函数数量**: ~80个

---

## 🎯 重命名/整理建议

### 优先级1: 删除冗余代码
1. ❌ 删除 `src/analysis/scorers/` 文件夹 (已被strategies/entry/替代)
2. ❌ 删除 `src/analysis/exiters/` 文件夹 (已被strategies/exit/替代)
3. ✅ 保留 `src/analysis/strategies/` 作为唯一策略实现

### 优先级2: 统一命名规范
- Entry策略统一后缀: `*Strategy` (如 SimpleScorerStrategy)
- Exit策略统一后缀: `*ExitStrategy` (如 ATRExitStrategy)
- 管理器类统一后缀: `*Manager` (如 StockDataManager)
- 引擎类统一后缀: `*Engine` (如 BacktestEngine)

### 优先级3: 文件名整理
| 当前名称 | 建议名称 | 原因 |
|---------|---------|------|
| `start_backtest.py` | ✅ 保持 | 清晰明了 |
| `start_portfolio_backtest.py` | ✅ 保持 | 清晰明了 |
| `quick_backtest.py` | 考虑重命名为 `cli_backtest.py` | 更明确是CLI工具 |
| `check_scores.py` | 考虑重命名为 `diagnose_scores.py` | 更明确是诊断工具 |

---

## ❓ 需要确认的问题

1. **旧版scorers/和exiters/是否完全废弃？** 
   - 如果是，可以删除
   - 如果还在使用，需要迁移

2. **test_*.py脚本是否还需要？**
   - test_backtest.py看起来功能重复
   - 可能需要整合到统一的测试框架

3. **examples.py是否需要更新？**
   - 可能包含过时的API调用

4. **src/utils/helpers.py几乎是空的**
   - 可以删除或填充实用工具

---

**生成时间**: 2026-01-14
**用途**: 代码整理和重命名参考
