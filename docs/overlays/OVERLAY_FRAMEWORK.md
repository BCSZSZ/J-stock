# Overlay Framework (Global Control Layer)

本文件说明 Overlay 的设计目标、接口与落地点。

## 1. 设计目标

- Overlay 是全局风控层，不绑定具体策略。
- 可叠加多个 Overlay，统一输出控制信号。
- 作用范围覆盖 production / portfolio / backtest / evaluation。

## 2. 输入与输出

### 2.1 输入 (OverlayContext)

- current_date: 当前评估日期
- portfolio_cash: 现金
- portfolio_value: 组合总资产
- positions: 当前持仓
- current_prices: 当前价格字典
- benchmark_data: 基准指数数据（可选）
- group_id: 生产组ID（可选）
- config: overlay 配置

### 2.2 输出 (OverlayDecision)

- target_exposure: 总体仓位目标 (0~1)
- position_scale: 单笔仓位缩放系数
- max_new_positions: 新开仓上限
- block_new_entries: 是否暂停新开仓
- force_exit: 是否强制减仓/清仓
- exit_overrides: 覆盖卖出信号 (ticker -> reason)
- metadata: 解释性信息

## 3. 叠加规则

- target_exposure / position_scale / max_new_positions: 取最保守值 (min)
- block_new_entries / force_exit: 任一触发即为 True
- exit_overrides: 合并并去重

## 4. 当前实现: RegimeOverlay

判断逻辑 (默认):

- Risk-ON: TOPIX > EMA200 且 20d 波动率 < 阈值
- Risk-OFF: 其他情况

输出:

- target_exposure: Risk-ON = 1.0, Risk-OFF = 0.4
- 可选: block_new_entries_when_off = true

波动率默认使用年化 (20 日收益率标准差 \* sqrt(252))。

## 5. 接入点

- production: [src/cli/production_daily.py](../../src/cli/production_daily.py)
- portfolio backtest: [src/backtest/portfolio_engine.py](../../src/backtest/portfolio_engine.py)
- single-stock backtest: [src/backtest/engine.py](../../src/backtest/engine.py)
- evaluation: [src/evaluation/strategy_evaluator.py](../../src/evaluation/strategy_evaluator.py)

## 6. 配置示例

```json
"overlays": {
  "enabled": ["RegimeOverlay"],
  "RegimeOverlay": {
    "benchmark": "TOPIX",
    "ema_window": 200,
    "vol_lookback": 20,
    "vol_threshold": 0.22,
    "risk_on_target_exposure": 1.0,
    "risk_off_target_exposure": 0.4,
    "block_new_entries_when_off": false
  }
}
```

## 7. 后续扩展示例

- DrawdownOverlay: 组合回撤超过阈值后降仓
- TakeProfitOverlay: 全局止盈/锁利
- LiquidityGateOverlay: 流动性不足时限制新开仓
- EventRiskOverlay: 财报/宏观事件窗口限制新开仓
