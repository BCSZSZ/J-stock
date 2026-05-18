# Instruction

## 大前提（所有任务通用）

- 先启动并激活项目虚拟环境（venv）后，再执行以下命令。
- 所有代码与命令均在当前终端目录下执行，统一使用相对路径，不写绝对项目路径。

## 全局策略：Overlay 默认 OFF（强制）

**所有 evaluation 与 production 默认 overlay=OFF。** 这是不可省略的项目级前提。

- 历史教训：`SectorBreadthOverlay` 在 2022–2024 风险偏离区间会触发 `risk_off_max_new_positions=0`，把约 99% 的入场信号拦截掉，导致回测仅 2–4 笔交易、累计收益骤降到 5.96%。同一出场策略 `MVXW_N5_R3p35_T1p45_D10_B20p0` 在 overlay=OFF 下 4 年累计 1949.69% / 1127 笔交易（基线见 `position_eval_p7x018_overlay_off_univ_default_continuous_report_20260421_212027.md`）。
- 因此：
  - `evaluate` / `pos-evaluation` 命令**不要主动加 `--enable-overlay`**，除非任务明确要求“overlay 对比”。
  - `production --daily` 仅在 `config.*.json` 的 `overlays.enabled=true` 或显式 CLI `--enable-overlay` 时启用 overlay；默认配置都是 `overlays.enabled=false`。
  - 任何对比 overlay 影响的实验，必须显式标注 `--overlay-modes off on`，并在报告里写明两条收益线。
- 配置约定（`config.json` / `config.local.json` / `config.aws.json` / `config.aws-sim.json` / `G:\My Drive\AI-Stock-Sync\config.json`）：
  - `overlays.enabled`：**布尔**，默认 `false`。
  - `overlays.active`：列表，**仅在 `enabled=true` 时**实例化的 overlay 名（如 `["SectorBreadthOverlay"]`）。
  - `evaluation.default_overlay_enabled`：默认 `false`（已废弃字段，保留为 `false` 以避免被误读）。

实现细节：
- `src/cli/evaluate.py::_resolve_effective_overlay_enabled` 解析顺序：override > `--enable-overlay` CLI > `config.overlays.enabled`（bool）→ 默认 False。
- `src/cli/production_daily.py` 解析顺序：`--enable-overlay` / `--disable-overlay` > `config.overlays.enabled` → 默认 False。
- `src/config/service.py::_normalize_overlays` 强制 `enabled` 必须为 bool，否则归一化为 False。

## Task 1: 入场退场策略评估

### 目标

在统一时间区间内，对多个入场策略 + 单一出场策略进行年度评估，并输出可复盘结果文件。

### 前置条件

- 在当前终端目录下使用相对调用，不写绝对项目路径
- 下方每个命令块中，第一行为 `.venv/Scripts/python.exe` 版本，第二行为等价的 `uv run` 版本

### 标准 CLI（必须使用）

```powershell
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverEnhancedA2_V11 MACDCrossoverEnhancedA2_V12 MACDCrossoverEnhancedA2_V13 MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0
uv run main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverEnhancedA2_V11 MACDCrossoverEnhancedA2_V12 MACDCrossoverEnhancedA2_V13 MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0
```

`pos-evaluation` 与 `evaluate` 共享同一套时间段/策略/filter/universe 参数，仓位维度通过 `--position-file` 与 `--profile-name` 控制：

```powershell
.venv/Scripts/python.exe main.py pos-evaluation --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --position-file evaluation-position.json
uv run main.py pos-evaluation --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --position-file evaluation-position.json
```

如需一次评估 overlay on/off 两种仓位结果：

```powershell
.venv/Scripts/python.exe main.py pos-evaluation --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --position-file evaluation-position.json --overlay-modes off on
uv run main.py pos-evaluation --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --position-file evaluation-position.json --overlay-modes off on
```

如需在 evaluation 中**按需启用 overlay（默认关闭，仅用于 overlay 对比研究）**：

```powershell
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverEnhancedA2_V11 MACDCrossoverEnhancedA2_V12 MACDCrossoverEnhancedA2_V13 MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --enable-overlay
uv run main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverEnhancedA2_V11 MACDCrossoverEnhancedA2_V12 MACDCrossoverEnhancedA2_V13 MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --enable-overlay
```

5年双MVX对比（使用默认：overlay=off、filter=off、仓位=7x0.18、evaluation输出目录=G盘）：

```powershell
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 MVX_N9_R3p4_T1p6_D18_B20p0
uv run main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 MVX_N9_R3p4_T1p6_D18_B20p0
```

### Entry Filter 层开关（evaluation）

- `--entry-filter-mode off|single|grid|auto`
  - `off`: 关闭过滤层（不启用二级过滤）
  - `single`: 只使用单一过滤器（默认 `evaluation.filters.default`）
  - `grid`: 使用 `evaluation.filters.variants` 做网格评估
  - `auto`: 有 `filters.variants` 就走网格，否则走单一（默认）
- `--entry-filter-name ...`
  - `single` 模式下指定 1 个过滤器名
  - `grid` 模式下可指定多个过滤器名作为子集
- `--list-entry-filters`
  - 查看当前可用过滤器并退出

示例：

```powershell
# 默认filter=off时，无需显式传 --entry-filter-mode off
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 MVX_N9_R3p4_T1p6_D18_B20p0
uv run main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 MVX_N9_R3p4_T1p6_D18_B20p0

# 仅使用单一filter
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --entry-filter-mode single --entry-filter-name f01_base
uv run main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --entry-filter-mode single --entry-filter-name f01_base

# 使用所有filter网格（例如1*1*9）
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --entry-filter-mode grid
uv run main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --entry-filter-mode grid

# 仅查看可用filter
.venv/Scripts/python.exe main.py evaluate --list-entry-filters
uv run main.py evaluate --list-entry-filters
```

### 策略命名与注册规范（必须遵守）

- 同一策略的不同参数版本，必须注册为不同策略名（不可共用一个名）。
- 命名应直接体现参数差异，便于评估追踪与回放。
- 参考命名风格：
  - 入场策略参数版：`MACDCrossoverEnhancedA2_V11` / `MACDCrossoverEnhancedA2_V12` / `MACDCrossoverEnhancedA2_V13`
  - 出场策略参数版：`MVX_N9_R3p6_T1p7_D18_B20p0`

## Task 2: 板块代表池构建（33板块）

### 目标

基于全市场打分结果，构建 33 板块代表池（默认每板块 9-12 支）。

### 标准命令（推荐）

```powershell
.venv/Scripts/python.exe main.py universe-sector --score-model v2 --size-balance
uv run main.py universe-sector --score-model v2 --size-balance
```

### 参数说明（必要）

- `--score-model v2`：使用 v2 打分模型。
- `--size-balance`：板块内按规模分层抽样，降低样本偏斜。
- `--min-per-sector` / `--max-per-sector`：控制每板块入选区间（默认 9/12）。
- `--no-fetch`：仅使用本地数据，不抓取增量。
- `--resume --checkpoint <path>`：中断后断点续跑。

### 本地数据齐全时（可选）

```powershell
.venv/Scripts/python.exe main.py universe-sector --score-model v2 --size-balance --no-fetch --resume
uv run main.py universe-sector --score-model v2 --size-balance --no-fetch --resume
```

### 输出位置

- 评分中间文件: `G:/My Drive/AI-Stock-Sync/universe/scoring/`
- 板块池结果: `G:/My Drive/AI-Stock-Sync/universe/sector_pool/`

### 失败排查

1. 若提示 `JQUANTS_API_KEY` 缺失: 先加载 `.env` 或设置环境变量。
2. 若首次运行且用了 `--no-fetch`: 去掉 `--no-fetch` 重新执行。
3. 若中断: 加 `--resume` 并保持相同 `--checkpoint`。

## Task 2.5: 全量抓取（fetch --all）

### 目标

按当前 monitor list / fetch universe 配置，执行一次全量抓取。

### 标准 CLI

```powershell
.venv/Scripts/python.exe main.py fetch --all
uv run main.py fetch --all
```

### 常用变体

```powershell
.venv/Scripts/python.exe main.py fetch --all --recompute
uv run main.py fetch --all --recompute
```

说明：

- `--all` 会基于当前 production 配置中的 monitor list / fetch universe 执行批量抓取。
- `--recompute` 仅重算特征层，不重新抓取远端原始数据。

## Task 3: 盘后生产任务（production --daily）

### 目标

一键执行盘后生产流程，自动完成数据更新、信号生成和日报输出。

### 标准 CLI（直接执行）

```powershell
.venv/Scripts/python.exe main.py production --daily
uv run main.py production --daily
```

```powershell
.venv/Scripts/python.exe main.py production --daily --no-fetch
uv run main.py production --daily --no-fetch
```

说明：production 流程已接入 overlay，并在日报 `Overlay Summary` 区块输出 overlay 指标与判断结果（默认主用 SectorBreadthOverlay；RegimeOverlay 为 deprecated 兼容项）。

### 外部文件导入成交（production --input）

```powershell
.venv/Scripts/python.exe main.py production --input --manual --manual-file today.csv --yes
uv run main.py production --input --manual --manual-file today.csv --yes
```

```powershell
.venv/Scripts/python.exe main.py production --input --manual --manual-file today.csv --yes --aws-profile personal
uv run main.py production --input --manual --manual-file today.csv --yes --aws-profile personal
```

CSV 必填列（顺序）：

- `ticker,action,qty,price`（第5列 `date` 可选）
- `action` 仅支持 `BUY` / `SELL`
- `qty` 必须为正整数，`price` 必须为正数

示例：

```csv
ticker,action,qty,price,date
4530,SELL,200,6030,2026-02-25
```

### 输出位置

- 本地信号文件: `output/signals/YYYY-MM-DD.json`
- 本地日报文件: `output/reports/YYYY-MM-DD.md`
- AWS 生产落盘（S3）: `s3://bcszsz-ai-j-stock-bucket/prod/ops/signals/` 与 `s3://bcszsz-ai-j-stock-bucket/prod/ops/reports/`

### 完成判定

- 终端出现 `Report saved:` 且无报错即视为成功。

## Task 3.5: 退出事件分类分析（exit_breakdown）

### 目标

针对指定的 `(entry_strategy, exit_strategy)` 组合，从已有的回测交易明细 CSV 中聚合出每种 `exit_urgency`（P_TP1 / P_TP2 / R1_ATRTrailing / L2_HistWindowDecay / T1_TimeStop / P_BiasOverheat）的：交易/事件次数、占比、胜率、平均/中位收益率、累计 JPY、平均持有天。

### 输入

- 任意 `evaluate` / `pos-evaluation` 产出的 `strategy_evaluation_*_trades_*.csv`（continuous 或 annual 均可）。

### 标准 CLI

```powershell
.venv/Scripts/python.exe tools/exit_breakdown.py `
  --trades-csv "<path-to-trades.csv>" `
  --exit-strategy MVXW_N5_R0p55_T1p3_D10_B20p0

uv run tools/exit_breakdown.py `
  --trades-csv "<path-to-trades.csv>" `
  --exit-strategy MVXW_N5_R0p55_T1p3_D10_B20p0
```

### 常用参数

- `--entry-strategy <name>`：再按入场策略过滤（同一 CSV 含多入场时使用）。
- `--period <label>`：仅统计某个 period（例如 `2024` 或 `2022-2025_continuous`）。
- `--scope events`（默认）：每个退出事件单独计数（含 TP1 半仓兑现）。
- `--scope full_only`：仅统计 `exit_is_full_exit=True`，按完整生命周期计数。
- `--csv-out <path>`：把表格落地为 CSV。

### 完成判定

- 终端打印形如下表，且 `TOTAL` 行的 `trades` 等于 CSV 中匹配过滤条件的行数。

```
exit_urgency  trades  share_pct  win_pct  avg_ret_pct  median_ret_pct  total_ret_jpy  avg_hold_days
...
TOTAL          ...     100.0%     ...      ...          ...             ...            ...
```

## Task 4: 财报数据去重（raw_financials）

### 目标

清理 `data/raw_financials/*.parquet` 的历史重复记录（仅处理财报层）。

### 标准 CLI（必须使用）

```powershell
.venv/Scripts/python.exe tools/dedup_raw_financials.py
uv run tools/dedup_raw_financials.py
```

### 预检查（可选）

```powershell
.venv/Scripts/python.exe tools/dedup_raw_financials.py --dry-run
uv run tools/dedup_raw_financials.py --dry-run
```

### 完成判定

- 终端输出 `Summary`，且 `rows_removed` 为去重删除行数。

## Task 5: 配置文件手动同步（config_sync）

### 目标

在多终端环境中，手动同步 `config.json`（以及可选 `otherconfig.json`）。

### 规则（必须遵守）

- `push` 只能单独运行，且必须通过双重确认。
- 每次 `push` 前，G盘旧 `config.json` 会自动按时间戳重命名并移动到 `old/`。

### G盘目录规范

- `G:/My Drive/AI-Stock-Sync/config.json`
- `G:/My Drive/AI-Stock-Sync/otherconfig.json`
- `G:/My Drive/AI-Stock-Sync/old/`

### 手动命令

从 G盘同步到本地：

```powershell
.venv/Scripts/python.exe tools/config_sync.py pull
uv run tools/config_sync.py pull
```

仅同步 `config.json`（跳过 `otherconfig.json`）：

```powershell
.venv/Scripts/python.exe tools/config_sync.py pull --no-otherconfig
uv run tools/config_sync.py pull --no-otherconfig
```

将本地覆盖到 G盘（危险操作，双确认）：

```powershell
.venv/Scripts/python.exe tools/config_sync.py push
uv run tools/config_sync.py push
```

## Task 6: G盘 state 迁移到 S3（一次性 + 日常）

### 目标

把历史 G 盘 state 文件迁移到 `prod/ops`，并建立本地与 S3 的日常同步。

### 一次性迁移（已验证可用）

```powershell
aws s3 cp "G:/My Drive/AI-Stock-Sync/state/production_state.json" s3://bcszsz-ai-j-stock-bucket/prod/ops/state/production_state.json
aws s3 cp "G:/My Drive/AI-Stock-Sync/state/trade_history.json" s3://bcszsz-ai-j-stock-bucket/prod/ops/state/trade_history.json
aws s3 cp "G:/My Drive/AI-Stock-Sync/state/fetch_universe.json" s3://bcszsz-ai-j-stock-bucket/prod/ops/state/fetch_universe.json
aws s3 cp "G:/My Drive/AI-Stock-Sync/state/production_monitor_list.json" s3://bcszsz-ai-j-stock-bucket/prod/ops/config/production_monitor_list.json
```

### 日常同步（推荐）

本地手动录入后推送到 S3：

```powershell
.venv/Scripts/python.exe tools/sync_ops_state_s3.py push --ops-s3-prefix s3://bcszsz-ai-j-stock-bucket/prod/ops
uv run tools/sync_ops_state_s3.py push --ops-s3-prefix s3://bcszsz-ai-j-stock-bucket/prod/ops
```

需要从 S3 拉回本地时：

```powershell
.venv/Scripts/python.exe tools/sync_ops_state_s3.py pull --ops-s3-prefix s3://bcszsz-ai-j-stock-bucket/prod/ops
uv run tools/sync_ops_state_s3.py pull --ops-s3-prefix s3://bcszsz-ai-j-stock-bucket/prod/ops
```
