# Agent Implementation Brief: Momentum + Regime Overlay

本文件用于新 session 的 agent 快速上手与实施。
目标：在现有项目中新增两个方向：

1) 中期截面动量 Entry 策略（weekly/monthly 节奏）
2) 市场状态切换 + 仓位目标（Risk Overlay）

---

## 1. 先读这些文档（按顺序）

1. 项目总览与当前 CLI 行为：
   - `README.md`
2. 命令参数与 production/evaluate 现状：
   - `docs/cli/COMMANDS_REFERENCE.md`
   - `docs/cli/PRODUCTION_DAILY_SOP.md`
3. 特征列与来源：
   - `docs/features/FEATURE_CATALOG.md`
4. 策略接口约定：
   - `docs/interfaces/IMPLEMENTATION_INTERFACES.md`
5. 现有策略逻辑：
   - `docs/strategies/ENTRY_EXIT_STRATEGIES.md`

---

## 2. 必看代码入口（按顺序）

### 2.1 策略注册与加载
- `src/utils/strategy_loader.py`
  - 查看 ENTRY/EXIT 注册表与 `create_strategy_instance`、`load_entry_strategy`

### 2.2 特征计算与数据读取
- `src/data/stock_data_manager.py`
  - `compute_features`
  - `load_stock_features`

### 2.3 信号统一契约
- `src/analysis/signals.py`
- `src/signal_generator.py`（`generate_signal_v2`）

### 2.4 现有 entry 参考实现
- `src/analysis/strategies/entry/macd_crossover.py`
- `src/analysis/strategies/entry/scorer_strategy.py`

### 2.5 回测与组合层
- `src/backtest/portfolio_engine.py`
- `src/backtest/signal_ranker.py`

### 2.6 production 工作流
- `src/cli/production.py`
- `src/production/comprehensive_evaluator.py`
- `src/production/report_builder.py`

---

## 3. 约束与实现原则

- 默认交易节奏：收盘后出信号，次日开盘执行。
- 不做小时级/分钟级微观交易逻辑。
- 默认整手 100 股，按 `config.json -> lot_sizes` 例外支持 1 股单位。
- 保持与当前回测/production 统一信号契约，不破坏已有策略。
- 优先小步改动，避免重构无关模块。

---

## 4. 方向 A：中期截面动量 Entry（新策略）

## 4.1 新增内容

1. 新策略文件：
   - `src/analysis/strategies/entry/cross_section_momentum_entry.py`
2. 在 loader 注册：
   - `src/utils/strategy_loader.py`（加入新 Entry 策略名）
3. 新特征（在 `compute_features` 中追加）：
   - `Return_60d = Close.pct_change(60)`
   - `Return_120d = Close.pct_change(120)`

## 4.2 策略逻辑（建议）

- 每天可计算，但仅在再平衡日触发 BUY（参数：weekly/monthly）。
- 基础信号需要：
  - `Return_60d`、`Return_120d` 为正
  - `Close > EMA_200`（可配置）
  - `Turnover_Median_20`、`ATR_Ratio` 通过阈值
- 信号 confidence 由多条件加权，输出 metadata 包含关键特征值。

## 4.3 为什么做成新策略而不是改旧策略

- 保持策略正交性与可回测性。
- 便于与现有 8 个 Exit 组合做横向比较。

---

## 5. 方向 B：Regime Risk Overlay（组合层）

## 5.1 新增内容

1. 新模块：
   - `src/production/regime_overlay.py`（或 `src/backtest/regime_overlay.py`）
2. 在回测与 production 的执行前接入同一逻辑：
   - `src/backtest/portfolio_engine.py`
   - `src/cli/production.py`

## 5.2 Overlay 逻辑（建议最小版）

- 使用 TOPIX 判断市场状态：
  - Risk-ON: TOPIX > EMA200 且 20d 波动低于阈值
  - Risk-OFF: 其他情况
- 输出：`target_exposure`（例如 ON=1.0, OFF=0.4）
- 对 BUY 的影响：
  - OFF 时降低每笔可用仓位或暂停新开仓

## 5.3 为什么不做成 entry 策略

- 这是全局风险控制，不是个股选点。
- 单独模块可统一作用于所有 entry/exit 组合。

---

## 6. 配置建议

在 `config.json` 增加：

```json
{
  "regime": {
    "enabled": true,
    "benchmark": "TOPIX",
    "risk_on_target_exposure": 1.0,
    "risk_off_target_exposure": 0.4,
    "vol_lookback": 20,
    "vol_threshold": 0.22,
    "ema_window": 200
  },
  "momentum_entry": {
    "rebalance": "weekly",
    "require_above_ema200": true,
    "min_turnover": 500000000,
    "atr_ratio_min": 0.015,
    "atr_ratio_max": 0.05
  }
}
```

---

## 7. 验证与回归检查

1. 语法与静态检查：
   - `get_errors` 对新增/修改文件检查
2. 快速功能验证：
   - `python main.py signal <ticker> --entry CrossSectionMomentumEntryStrategy`
3. 评估对比：
   - `python main.py evaluate --mode annual --years 2023 2024 2025 --entry-strategies CrossSectionMomentumEntryStrategy --exit-strategies ScoreBasedExitStrategy ATRExitStrategy`
4. production 验证：
   - `python main.py production --daily --skip-fetch`
   - 检查 signals/report 输出与 reason

---

## 8. 交付标准（Done Definition）

- 新 Entry 策略可被 loader 识别并在 signal/backtest/evaluate 使用。
- 新特征列在 features parquet 中可见。
- Regime overlay 可开关，并对仓位建议/新开仓产生可观测影响。
- README 与 docs 至少更新：
  - 策略列表
  - evaluate/prod 使用说明
  - 新增配置字段说明

---

## 9. 风险提示（避免过拟合）

- 不只看最优参数点，需看参数邻域稳定性。
- 使用 annual + quarterly 双视角验证。
- 将交易成本/滑点作为后续敏感性检查（可先做常数近似）。
