# Instruction

## Task 1: 入场退场策略评估

### 目标
在统一时间区间内，对多个入场策略 + 单一出场策略进行年度评估，并输出可复盘结果文件。

### 前置条件
- 当前终端目录已经是项目根目录：`E:\Code\AI-stock\J-stock`
- 使用相对调用，不写绝对项目路径

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


