# Evaluation 专用：退出信号连续确认（多终端同步说明）

## 目标

仅在 `evaluation / pos-evaluation` 回测路径启用“连续 N 天出现退出信号才执行卖出”，不影响 `production`。

## 本次实现

- 新增 CLI 参数：`--exit-confirm-days`
  - 作用命令：`evaluate`、`evaluation`、`pos-evaluation`
  - 优先级：CLI 参数 > `config.json` 的 `evaluation.exit_confirmation_days` > 默认值 `1`
- 新增配置项：`evaluation.exit_confirmation_days`
  - 本地默认建议：`2`
- 回测引擎新增确认层：
  - 持仓股票若当天出现 `SELL`，计数 +1
  - 仅当连续计数 `>= N` 时才产生实际卖出信号（按原有 T+1 执行卖出）
  - 若中间某天不是 `SELL`，计数重置为 0
  - 平仓/无持仓后，会清理该股票计数

## 使用示例

### 1) 使用配置默认值（推荐）

```bash
python main.py pos-evaluation --years 2021 2022 2023 2024 2025
```

### 2) 临时覆盖为 2 天确认

```bash
python main.py pos-evaluation --years 2021 2022 2023 2024 2025 --exit-confirm-days 2
```

### 3) 恢复旧行为（单日 SELL 即退出）

```bash
python main.py pos-evaluation --years 2021 2022 2023 2024 2025 --exit-confirm-days 1
```

## 多终端同步步骤（避免配置漂移）

1. 在主终端完成代码提交并推送。
2. 其他终端执行：
   - `git fetch origin`
   - `git checkout main`
   - `git pull --rebase origin main`
3. 确认本地 `config.json` 含有：

```json
"evaluation": {
  "exit_confirmation_days": 2
}
```

4. 若某终端不希望改本地 `config.json`，可统一通过命令行覆盖：
   - `--exit-confirm-days 2`

## 影响范围

- 影响：`evaluation` / `pos-evaluation` 回测结果（交易频率、回撤、收益曲线会变化）
- 不影响：`production --daily` 的真实信号流程
