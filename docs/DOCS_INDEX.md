# J-Stock-Analyzer Documentation（2026-02 清洗版）

本目录以“源码为准”重建为四类文档：

1. CLI 命令参数与效果
2. 入场/出场策略逻辑与数学公式
3. 功能代码实装接口定义
4. Feature 计算方法与全集

## 文档入口

- [CLI 命令参考](cli/COMMANDS_REFERENCE.md)
- [Production 实操概要（单组 + 双终端）](cli/PRODUCTION_DAILY_SOP.md)
- [策略逻辑与公式](strategies/ENTRY_EXIT_STRATEGIES.md)
- [实现接口说明](interfaces/IMPLEMENTATION_INTERFACES.md)
- [Feature 目录与计算方法](features/FEATURE_CATALOG.md)
- [Agent 实施设计简报（Momentum + Regime）](AGENT_IMPLEMENTATION_BRIEF_MOMENTUM_REGIME.md)

## 清洗说明

- 旧版历史文档已从仓库移除，不再保留归档目录
- 当前文档以 `main.py` + `src/` 实际行为为准

## 2026-02 重构要点

- `production` 已切换为盘后信号引擎工作流：`--daily` / `--input` / `--status`
- 默认实盘配置采用单组（`group_main`），同时保留多组扩展能力
- production 运行态文件支持放在 Google Drive 目录，便于多终端同步
- `evaluate` 未指定 `--output-dir` 时默认云端优先，失败回退本地并提示
