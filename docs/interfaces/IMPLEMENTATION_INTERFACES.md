# 功能实现接口定义（源码对齐）

本文聚焦“实装接口”，即各功能模块的主要类/函数、输入输出与调用关系。

## 1. 统一信号契约（策略层核心）

定义于 `src/analysis/signals.py`：

- `SignalAction`: `BUY | SELL | HOLD`
- `TradingSignal`
  - `action: SignalAction`
  - `confidence: float`
  - `reasons: List[str]`
  - `metadata: Dict[str, Any]`
  - `strategy_name: str`
- `MarketData`
  - `ticker`, `current_date`
  - `df_features`, `df_trades`, `df_financials`, `metadata`
- `Position`
  - `entry_price`, `entry_date`, `quantity`, `entry_signal`, `peak_price_since_entry`

策略抽象基类：

- `BaseEntryStrategy.generate_entry_signal(market_data) -> TradingSignal`
- `BaseExitStrategy.generate_exit_signal(position, market_data) -> TradingSignal`

---

## 2. 策略加载接口

定义于 `src/utils/strategy_loader.py`：

- `load_strategy_class(strategy_name, strategy_type)`
- `create_strategy_instance(strategy_name, strategy_type, params=None)`
- `load_entry_strategy(name, params=None)`
- `load_exit_strategy(name, params=None)`
- `get_all_strategy_combinations() -> List[(entry, exit)]`
- `get_strategy_combinations_from_lists(entry_names, exit_names)`
- `parse_strategy_config(config) -> (entry_instance, exit_instance)`

---

## 3. 数据层接口

## 3.1 `StockDataManager`（`src/data/stock_data_manager.py`）

采集 + 特征 + 读取统一入口：

- OHLC
  - `fetch_and_update_ohlc(code) -> (DataFrame, has_new_data)`
- Feature
  - `compute_features(code, force_recompute=False) -> DataFrame`
- 辅助数据
  - `fetch_and_save_financials(code)`
  - `fetch_and_save_investor_trades(code)`
  - `fetch_and_save_metadata(code)`
- 全流程
  - `run_full_etl(code, force_recompute=False) -> Dict`
- 读取
  - `load_stock_features(ticker)`
  - `load_raw_prices(ticker)`
  - `load_trades(ticker)`
  - `load_financials(ticker)`
  - `load_metadata(ticker)`

## 3.2 `StockETLPipeline`（`src/data/pipeline.py`）

- `run_batch(tickers, fetch_aux_data=True, recompute_features=False) -> summary`
- `retry_failed()` / `get_failed_tickers()` / `print_summary()`

## 3.3 `MarketDataBuilder`（`src/data/market_data_builder.py`）

统一把原始 DataFrame 规整成 `MarketData`：

- `build_from_manager(data_manager, ticker, current_date)`
- `build_from_parquet(ticker, current_date, data_root='data')`
- `build_from_dataframes(ticker, current_date, df_features, df_trades, df_financials, metadata)`

---

## 4. 信号与回测接口

## 4.1 信号生成（`src/signal_generator.py`）

- `generate_trading_signal(ticker, date, entry_strategy, exit_strategy, ...) -> dict`
  - 用于 CLI 单点信号输出
- `generate_signal_v2(market_data, entry_strategy, exit_strategy=None, position=None, ...) -> TradingSignal`
  - 统一供 backtest / portfolio / production 调用

## 4.2 单票回测（`src/backtest/engine.py`）

- 类：`BacktestEngine`
  - `backtest_strategy(ticker, entry_strategy, exit_strategy, start_date, end_date) -> BacktestResult`
- 便捷函数：
  - `backtest_strategy(...)`（模块级包装）
  - `backtest_strategies(tickers, strategies, ...)`

核心执行规则：

- 当日收盘用历史数据生成信号
- 下一交易日开盘执行挂单

## 4.3 组合回测（`src/backtest/portfolio_engine.py`）

- 类：`PortfolioBacktestEngine`
  - `backtest_portfolio_strategy(tickers, entry_strategy, exit_strategy, start_date, end_date, ...) -> BacktestResult`

主要接口能力：

- 多持仓管理（`Portfolio`）
- 信号排序（`SignalRanker`）
- 仓位约束与 lot size 管理

---

## 5. 选股与评估接口

## 5.1 Universe（`src/universe/stock_selector.py`）

- `run_selection(top_n=50, test_mode=False, ..., return_full=False, no_fetch=False)`
- `fetch_universe_data(...)`
- `apply_hard_filters(df)`
- `normalize_features(df)`
- `calculate_scores(df)`
- `select_top_n(df, n=50)`
- `save_selection_results(df_top, format='both')`

## 5.2 评估（`src/evaluation/strategy_evaluator.py`）

- 类：`StrategyEvaluator`
  - `run_evaluation(periods, entry_strategies=None, exit_strategies=None) -> DataFrame`
  - `analyze_by_market_regime()`
  - `get_top_strategies_by_regime(top_n=3)`
  - `save_results(prefix='evaluation')`
- 时间段工厂函数：
  - `create_annual_periods(years)`
  - `create_quarterly_periods(years)`
  - `create_monthly_periods(year, months)`

---

## 6. CLI 层接口映射

定义于 `main.py` + `src/cli/*.py`：

- `cmd_production`
- `cmd_fetch`
- `cmd_signal`
- `cmd_backtest`
- `cmd_portfolio`
- `cmd_universe`
- `cmd_evaluate`

每个 `cmd_*` 负责：参数解释、配置加载、调用核心服务层接口，不承载策略数学逻辑。

---

## 7. Production 报告接口

定义于 `src/production/report_builder.py`：

- `ReportBuilder.generate_daily_report(signals, execution_results=None, report_date=None, comprehensive_evaluations=None) -> str`
- 当提供 `comprehensive_evaluations` 时，报告使用动态策略列（来自 `evaluations.keys()`）
- SELL 推荐区块始终列出全部持仓，并标注是否建议卖出与理由
