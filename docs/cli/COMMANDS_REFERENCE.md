# CLI 命令参考（源码对齐）

## 1) 统一入口：`python main.py`

主入口定义于 `main.py`，包含 7 个子命令：`production / fetch / signal / backtest / portfolio / universe / evaluate`。

---

## 1.1 `production`

执行生产流程：加载状态 →（可选）抓取数据 → 生成信号 → 生成日报。

参数：

- `--dry-run`
- `--skip-fetch`

---

## 1.2 `fetch`

抓取/更新数据，或仅重算 feature 层。

参数：

- `--all` 或 `--tickers <code...>`（二选一）
- `--recompute`

---

## 1.3 `signal`

为单只股票生成信号。

参数：

- `ticker`
- `--date YYYY-MM-DD`
- `--entry <EntryStrategyName>`
- `--exit <ExitStrategyName>`

---

## 1.4 `backtest`

单股票回测。

参数：

- `ticker`
- `--entry <name...>`
- `--exit <name...>`
- `--all-strategies`
- `--years <int>`
- `--start YYYY-MM-DD`
- `--end YYYY-MM-DD`
- `--capital <int>`

---

## 1.5 `portfolio`

组合回测。

参数：

- `--all` 或 `--tickers <code...>`（二选一）
- `--entry <name...>`
- `--exit <name...>`
- `--all-strategies`
- `--years <int>`
- `--start YYYY-MM-DD`
- `--end YYYY-MM-DD`
- `--capital <int>`

---

## 1.6 `universe`

宇宙选股（批处理 + checkpoint + resume）。

参数：

- `--csv-file <path>`
- `--top-n <int>`
- `--limit <int>`
- `--batch-size <int>`
- `--resume`
- `--checkpoint <path>`
- `--no-fetch`

---

## 1.7 `evaluate`

策略综合评价（多时间段、多策略组合）。

参数：

- `--mode annual|quarterly|monthly|custom`
- `--years <int...>`
- `--months <int...>`
- `--custom-periods '<json>'`
- `--entry-strategies <name...>`
- `--exit-strategies <name...>`
- `--output-dir <path>`
- `--verbose`

---

## 2) 历史脚本归档说明

此前根目录辅助脚本（`quick_backtest.py`、`run_universe_selector.py`、`start_backtest.py`、`start_portfolio_backtest.py`）已从仓库移除。

请统一使用 `python main.py` 对应子命令，避免入口分散并确保参数行为一致。
