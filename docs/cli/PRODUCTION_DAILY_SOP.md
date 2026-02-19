# Production 实操概要（单组 + 双终端）

本文是日常执行手册，面向当前实盘模式：

- 单组：`group_main`
- 盘后生成信号：`production --daily`
- 次日人工成交后回传：`production --input`
- 运行态文件同步：Google Drive（`G:\\My Drive\\AI-Stock-Sync`）

---

## 0) 执行前检查（每次 30 秒）

1. 确认 Google Drive 图标状态为“已同步”。
2. 在本机项目目录执行：

```bash
python main.py production --status
```

3. 核对现金/持仓是否符合你预期（避免使用旧副本）。
4. 同一时段只在一台电脑操作（避免并发写冲突）。

---

## 1) 盘后流程（每日）

命令：

```bash
python main.py production --daily
```

行为：

- 抓取/更新当日数据（可重试 429 限流）
- 检查是否已拿到“最新可用数据日”，若未拿到会提醒并中断
- 若在凌晨/未开盘时执行，会自动使用“最新可用数据日”生成信号
- 用当前策略生成次日 BUY/SELL 信号
- 输出信号与日报（默认写 Google Drive 路径）
- 日报包含完整评估表（策略列动态适配）、可执行建议与 Final Picks
- SELL 推荐区块始终列出所有持仓，并标注是否建议卖出与原因

常用变体：

```bash
python main.py production --daily --skip-fetch
```

适用于当日数据已提前更新，仅需重跑评分与报告。

---

## 2) 次日回传（人工成交后）

命令：

```bash
python main.py production --input
```

若有“信号以外”的成交，使用CSV手动录入（仅执行CSV，不走信号交互）：

```bash
python main.py production --input --manual --manual-file today.csv
```

CSV格式（可含表头）：

```
ticker,action,qty,price,date
```

说明：

- `action` 仅支持 `BUY` / `SELL`
- `date` 可省略，默认使用 `--trade-date` 或今天

可选：

```bash
python main.py production --input --signal-date 2026-02-17 --trade-date 2026-02-18
```

流程：

- 自动读取最近（或指定日期）信号文件
- 按提示逐条录入实际成交数量/价格
- 写回：
  - `production_state.json`（现金与持仓）
  - `trade_history.json`（交易记录）

---

## 3) 持仓同步（重要）

**使用场景**：

- 手动买入了不在监视列表中的股票
- 持仓中存在系统未跟踪的股票（无法生成正确的卖出信号）

命令：

```bash
python main.py production --sync-positions
```

**行为**：

1. 扫描所有分组的持仓，找出所有 ticker
2. 对比监视列表，找出缺失的 ticker
3. 自动抓取缺失股票的数据（5年历史）
4. 更新 3 个监视列表文件：
   - `G:\My Drive\AI-Stock-Sync\state\production_monitor_list.json`（生产环境）
   - `data/production_monitor_list.json`（本地备份）
   - `data/monitor_list.json`（普通监视列表，含详细信息）

**建议执行时机**：

- 每次手动买入新股票后
- 每周执行一次作为例行检查
- 运行 `--daily` 发现卖出信号为空但确实持有该股票时

**示例输出**：

```
[1/5] Found 6 unique ticker(s) in positions:
  - 1321
  - 2737
  - 4530
  - 7011
  - 7013
  - 8058

[3/5] Found 1 missing ticker(s):
  ⚠️  7013

[4/5] Fetching data for missing tickers...
  Fetching 7013... ✅

[5/5] Updating monitor lists...
  ✅ Updated: G:\My Drive\...\production_monitor_list.json
  ✅ Updated: data\production_monitor_list.json
  ✅ Updated: data\monitor_list.json
```

---

## 4) 管理员修正命令（谨慎使用）

```bash
python main.py production --set-cash group_main 8000000
python main.py production --set-position group_main 8035 100 31500 --entry-date 2026-02-18
```

说明：

- `--set-cash`：直接覆盖现金余额
- `--set-position`：直接覆盖指定持仓
- 建议只在“明显录入错误”时使用

---

## 5) 双终端运行规则（关键）

- 规则 1：同一时间只允许一台电脑执行写操作（`--daily` / `--input` / `--sync-positions` / 管理员修正）
- 规则 2：执行前先 `--status` 对账
- 规则 3：切换电脑前确认 Google Drive 已同步完成
- 规则 4：若发现状态异常，先暂停操作，再用 `trade_history.json` 回溯

---

## 6) 常见问题速查

### Q1: 看到 `Rate limit hit (429)`

属于 API 限流，系统会自动重试（带退避等待）。通常无需人工处理。

### Q2: `--daily` 提示未拿到当日数据并中断

一般是运行太早（收盘后数据尚未可用）。等待后重试即可。

### Q3: 为什么今天没有 SELL 信号？

若当前空仓或持仓未触发退出条件，SELL 可能为 0，这是正常现象。

### Q4: 多电脑状态不一致怎么办？

先停止两边写操作，确认 Google Drive 同步完成后，再执行 `production --status` 比对；必要时用管理员修正命令对齐。

### Q5: 我手动买入的股票为什么没有卖出信号？

可能该股票不在监视列表中。运行 `production --sync-positions` 同步持仓到监视列表，系统会自动抓取数据并在下次 `--daily` 时生成信号。
