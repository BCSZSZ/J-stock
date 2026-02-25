# Instruction

## 大前提（所有任务通用）

- 先启动并激活项目虚拟环境（venv）后，再执行以下命令。
- 所有代码与命令均在当前终端目录下执行，统一使用相对路径，不写绝对项目路径。

## Task 1: 入场退场策略评估

### 目标

在统一时间区间内，对多个入场策略 + 单一出场策略进行年度评估，并输出可复盘结果文件。

### 前置条件

- 在当前终端目录下使用相对调用，不写绝对项目路径

### 标准 CLI（必须使用）

```powershell
.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-strategies MACDCrossoverEnhancedA2_V11 MACDCrossoverEnhancedA2_V12 MACDCrossoverEnhancedA2_V13 MACDCrossoverStrategy --exit-strategies MVX_N9_R3p4_T1p6_D18_B20p0
```

### 策略命名与注册规范（必须遵守）

- 同一策略的不同参数版本，必须注册为不同策略名（不可共用一个名）。
- 命名应直接体现参数差异，便于评估追踪与回放。
- 参考命名风格：
  - 入场策略参数版：`MACDCrossoverEnhancedA2_V11` / `MACDCrossoverEnhancedA2_V12` / `MACDCrossoverEnhancedA2_V13`
  - 出场策略参数版：`MVX_N9_R3p4_T1p6_D18_B20p0`

## Task 2: 板块代表池构建（33板块）

### 目标

基于全市场打分结果，构建 33 板块代表池（默认每板块 9-12 支）。

### 标准命令（推荐）

```powershell
.venv/Scripts/python.exe main.py universe-sector --score-model v2 --size-balance
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
```

### 外部文件导入成交（production --input）

```powershell
.venv/Scripts/python.exe main.py production --input --manual --manual-file today.csv --yes
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

- 信号文件: `G:/My Drive/AI-Stock-Sync/signals/YYYY-MM-DD.json`
- 日报文件: `G:/My Drive/AI-Stock-Sync/reports/YYYY-MM-DD.md`

### 完成判定

- 终端出现 `Report saved:` 且无报错即视为成功。

## Task 4: 财报数据去重（raw_financials）

### 目标

清理 `data/raw_financials/*.parquet` 的历史重复记录（仅处理财报层）。

### 标准 CLI（必须使用）

```powershell
.venv/Scripts/python.exe tools/dedup_raw_financials.py
```

### 预检查（可选）

```powershell
.venv/Scripts/python.exe tools/dedup_raw_financials.py --dry-run
```

### 完成判定

- 终端输出 `Summary`，且 `rows_removed` 为去重删除行数。
