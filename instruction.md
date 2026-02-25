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

基于全市场打分结果，构建 33 板块代表池（每板块 12-15 支）。

### 首次全量运行（标准命令，无 `--no-fetch`）

```powershell
.venv/Scripts/python.exe main.py universe-sector --score-model v2 --size-balance --min-per-sector 12 --max-per-sector 15 --batch-size 100 --workers 8 --output-dir data/universe
```

说明: 首次运行会先执行批量 ETL 预处理（抓取 OHLC + 计算特征），再进入板块打分与选股。

### 增量运行（本地数据已齐全时）

```powershell
.venv/Scripts/python.exe main.py universe-sector --score-model v2 --size-balance --min-per-sector 12 --max-per-sector 15 --no-fetch --resume
```

### 输出位置

- 评分中间文件: `data/universe/scoring/`
- 板块池结果: `data/universe/sector_pool/`

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

### 输出位置

- 信号文件: `G:/My Drive/AI-Stock-Sync/signals/YYYY-MM-DD.json`
- 日报文件: `G:/My Drive/AI-Stock-Sync/reports/YYYY-MM-DD.md`

### 完成判定

- 终端出现 `Report saved:` 且无报错即视为成功。
