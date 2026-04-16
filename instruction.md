# Instruction

## 大前提（所有任务通用）

- **推荐使用 `uv run`**：无需手动激活 venv，`uv run python` 会自动使用项目虚拟环境。
- 传统方式：先启动并激活项目虚拟环境（venv）后，再执行 `.venv/Scripts/python.exe` 命令。
- 所有代码与命令均在当前终端目录下执行，统一使用相对路径，不写绝对项目路径。
- **等价规则**：所有 `.venv/Scripts/python.exe` 命令均可替换为 `uv run python`。

## Task 1: 入场退场策略评估

### 目标

在统一时间区间内，对多个入场策略 + 单一出场策略进行年度评估，并输出可复盘结果文件。

### 前置条件

- 在当前终端目录下使用相对调用，不写绝对项目路径

### 標準 CLI（必须使用）

```powershell
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverEnhancedA2_V11 MACDCrossoverEnhancedA2_V12 MACDCrossoverEnhancedA2_V13 MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0
# uv:
uv run python main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverEnhancedA2_V11 MACDCrossoverEnhancedA2_V12 MACDCrossoverEnhancedA2_V13 MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0
```

#### 排名策略评估（--ranking-strategies）

evaluate 命令支持 `--ranking-strategies` 参数，可同时评估多种 BUY 信号排序策略：

```powershell
uv run python main.py evaluate --mode annual --years 2022 2023 2024 2025 \
  --entry-strategies MACDPreCross2BarEntry \
  --exit-strategies MVXW_N5_R3p35_T1p45_D21_B20p0 \
  --ranking-strategies default random score_only confidence_weighted risk_adjusted composite momentum volatility_penalty trend_alignment
```

可用排名策略：`default`, `random`, `score_only`, `confidence_weighted`, `risk_adjusted`, `composite`, `momentum`, `volatility_penalty`, `trend_alignment`

> **2026-04-16 评估结论**：`momentum` 为最优排名策略（4年连续收益1661%，Sharpe 3.20，胜率65%），已设为生产默认。

`pos-evaluation` 与 `evaluate` 共享同一套时间段/策略/filter/universe 参数，仓位维度通过 `--position-file` 与 `--profile-name` 控制：

```powershell
.venv/Scripts/python.exe main.py pos-evaluation --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --position-file evaluation-position.json
# uv:
uv run python main.py pos-evaluation --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --position-file evaluation-position.json
```

如需一次评估 overlay on/off 两种仓位结果：

```powershell
.venv/Scripts/python.exe main.py pos-evaluation --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --position-file evaluation-position.json --overlay-modes off on
# uv:
uv run python main.py pos-evaluation --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --position-file evaluation-position.json --overlay-modes off on
```

如需在 evaluation 中按需启用 overlay（默认关闭）：

```powershell
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverEnhancedA2_V11 MACDCrossoverEnhancedA2_V12 MACDCrossoverEnhancedA2_V13 MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --enable-overlay
# uv:
uv run python main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverEnhancedA2_V11 MACDCrossoverEnhancedA2_V12 MACDCrossoverEnhancedA2_V13 MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --enable-overlay
```

5年双MVX对比（使用默认：overlay=off、filter=off、仓位=7x0.18、evaluation输出目录=G盘）：

```powershell
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 MVX_N9_R3p4_T1p6_D18_B20p0
# uv:
uv run python main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 MVX_N9_R3p4_T1p6_D18_B20p0
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
# uv:
uv run python main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 MVX_N9_R3p4_T1p6_D18_B20p0

# 仅使用单一filter
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --entry-filter-mode single --entry-filter-name f01_base
# uv:
uv run python main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --entry-filter-mode single --entry-filter-name f01_base

# 使用所有filter网格（例如1*1*9）
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --entry-filter-mode grid
# uv:
uv run python main.py evaluate --mode annual --years 2021 2022 2023 --entry-strategies MACDCrossoverStrategy --exit-strategies MVX_N9_R3p6_T1p7_D18_B20p0 --entry-filter-mode grid

# 仅查看可用filter
.venv/Scripts/python.exe main.py evaluate --list-entry-filters
# uv:
uv run python main.py evaluate --list-entry-filters
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
# uv:
uv run python main.py universe-sector --score-model v2 --size-balance
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
# uv:
uv run python main.py universe-sector --score-model v2 --size-balance --no-fetch --resume
```

### 输出位置

- 评分中间文件: `G:/My Drive/AI-Stock-Sync/universe/scoring/`
- 板块池结果: `G:/My Drive/AI-Stock-Sync/universe/sector_pool/`

### 失败排查

1. 若提示 `JQUANTS_API_KEY` 缺失: 先加载 `.env` 或设置环境变量。
2. 若首次运行且用了 `--no-fetch`: 去掉 `--no-fetch` 重新执行。
3. 若中断: 加 `--resume` 并保持相同 `--checkpoint`。

## Task 3: 盘后生产任务（production --daily）

### 目标

一键执行盘后生产流程，自动完成数据更新、信号生成和日报输出。

### 标准 CLI（直接执行）

```powershell
.venv/Scripts/python.exe main.py production --daily
# uv:
uv run python main.py production --daily
```

```powershell
.venv/Scripts/python.exe main.py production --daily --no-fetch
# uv:
uv run python main.py production --daily --no-fetch
```

说明：production 流程已接入 overlay，并在日报 `Overlay Summary` 区块输出 overlay 指标与判断结果（默认主用 SectorBreadthOverlay；RegimeOverlay 为 deprecated 兼容项）。

### BUY 信号排名策略（signal_ranking_strategy）

生产环境通过 G盘 `config.json` 的 `production.signal_ranking_strategy` 字段指定 BUY 信号排序策略。
**当前配置值：`momentum`**（2026-04-16 基于4年回测评估结果切换，原为未设置/default）。

- 配置位置：`G:/My Drive/AI-Stock-Sync/config.json` → `production.signal_ranking_strategy`
- 生产无 CLI 参数，仅通过 config 文件控制
- 若省略该字段，则不进行排名（等同于 default）
- 可选值：`default`, `random`, `score_only`, `confidence_weighted`, `risk_adjusted`, `composite`, `momentum`, `volatility_penalty`, `trend_alignment`

### 外部文件导入成交（production --input）

```powershell
.venv/Scripts/python.exe main.py production --input --manual --manual-file today.csv --yes
# uv:
uv run python main.py production --input --manual --manual-file today.csv --yes
```

```powershell
.venv/Scripts/python.exe main.py production --input --manual --manual-file today.csv --yes --aws-profile personal
# uv:
uv run python main.py production --input --manual --manual-file today.csv --yes --aws-profile personal
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

## Task 4: 财报数据去重（raw_financials）

### 目标

清理 `data/raw_financials/*.parquet` 的历史重复记录（仅处理财报层）。

### 标准 CLI（必须使用）

```powershell
.venv/Scripts/python.exe tools/dedup_raw_financials.py
# uv:
uv run python tools/dedup_raw_financials.py
```

### 预检查（可选）

```powershell
.venv/Scripts/python.exe tools/dedup_raw_financials.py --dry-run
# uv:
uv run python tools/dedup_raw_financials.py --dry-run
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
# uv:
uv run python tools/config_sync.py pull
```

仅同步 `config.json`（跳过 `otherconfig.json`）：

```powershell
.venv/Scripts/python.exe tools/config_sync.py pull --no-otherconfig
# uv:
uv run python tools/config_sync.py pull --no-otherconfig
```

将本地覆盖到 G盘（危险操作，双确认）：

```powershell
.venv/Scripts/python.exe tools/config_sync.py push
# uv:
uv run python tools/config_sync.py push
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
# uv:
uv run python tools/sync_ops_state_s3.py push --ops-s3-prefix s3://bcszsz-ai-j-stock-bucket/prod/ops
```

需要从 S3 拉回本地时：

```powershell
.venv/Scripts/python.exe tools/sync_ops_state_s3.py pull --ops-s3-prefix s3://bcszsz-ai-j-stock-bucket/prod/ops
# uv:
uv run python tools/sync_ops_state_s3.py pull --ops-s3-prefix s3://bcszsz-ai-j-stock-bucket/prod/ops
```
