# CLI 命令参考（源码对齐）

## 1) 统一入口：`python main.py`

主入口定义于 `main.py`，包含 7 个子命令：`production / fetch / signal / backtest / portfolio / universe / evaluate`。

---

## 1.1 `production`

执行生产工作流（当前默认单组，保留多组扩展）：

- `--daily`: 盘后流程（加载状态 → 可选抓取 → 生成信号 → 生成日报）
- `--input`: 次日人工成交回传（读取前一日信号并写入 state/history）
- `--status`: 查看当前资金/持仓/历史概览
- `--set-cash`: 管理员修正分组现金
- `--set-position`: 管理员覆盖分组持仓

说明：

- `--daily` 会自动使用“最新可用数据日”生成信号（避免凌晨误用当天日期）
- 日报包含完整评估表（策略列动态适配）、可执行建议与 Final Picks
- SELL 推荐区块始终列出所有持仓，并标注是否建议卖出与原因

参数：

- `--daily`
- `--input`
- `--status`
- `--set-cash <GROUP_ID> <AMOUNT>`
- `--set-position <GROUP_ID> <TICKER> <QTY> <PRICE>`
- `--signal-date YYYY-MM-DD`（配合 `--input`）
- `--trade-date YYYY-MM-DD`（配合 `--input`）
- `--entry-date YYYY-MM-DD`（配合 `--set-position`）
- `--yes`（配合 `--input` 跳过确认）
- `--manual`（配合 `--input` 追加手动CSV成交录入）
- `--manual-file <path>`（配合 `--input --manual` 指定CSV路径）
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

默认输出行为（2026-02 重构后）：

- 未指定 `--output-dir` 时，优先输出到 `G:\My Drive\AI-Stock-Sync\strategy_evaluation`
- 若该路径不可写，自动回退到本地 `strategy_evaluation`，并打印提醒

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
