# MACD + KDJ 入场/出场策略设计文档（伪代码级）

## 1. 文档目标与范围

本文档用于在**不修改业务代码**的前提下，完成以下工作：

1. 对照当前项目实现，评审新策略规则的差异与风险点。
2. 给出可执行的伪代码级设计（Entry + Exit）。
3. 明确在现有策略框架中的接入位置、参数接口与验证清单。

> 范围约束：今天仅产出设计，不进行代码实现、不调试。

---

## 2. 需求规则（按用户给定定义原样落地）

### 2.1 MACD 计算逻辑（12, 26, 9）

1. 快速与慢速 EMA：
   - $EMA_{12,t} = Price_t \times \frac{2}{13} + EMA_{12,t-1} \times \frac{11}{13}$
   - $EMA_{26,t} = Price_t \times \frac{2}{27} + EMA_{26,t-1} \times \frac{25}{27}$
2. 差离值（DIF）：
   - $DIF_t = EMA_{12,t} - EMA_{26,t}$
3. 信号线（DEA）：
   - $DEA_t = DIF_t \times \frac{2}{10} + DEA_{t-1} \times \frac{8}{10}$
4. 能量柱（Histogram）：
   - $MACD_{hist,t} = 2 \times (DIF_t - DEA_t)$

### 2.2 KDJ 计算逻辑（9, 3, 3）

1. RSV：
   - $RSV_t = \frac{Close_t - LLV_{9,t}}{HHV_{9,t} - LLV_{9,t}} \times 100$
   - 其中 $LLV_{9,t}=min(Low_{t-8..t})$，$HHV_{9,t}=max(High_{t-8..t})$
2. K：
   - $K_t = \frac{2}{3}K_{t-1} + \frac{1}{3}RSV_t$
3. D：
   - $D_t = \frac{2}{3}D_{t-1} + \frac{1}{3}K_t$
4. J：
   - $J_t = 3K_t - 2D_t$

### 2.3 交易规则

#### 入场（必须同时满足，且顺序相关）

1. 趋势初步止跌（MACD 收敛）
   - $MACD_{hist,t} > MACD_{hist,t-1}$
2. 超卖区金叉（KDJ）
   - $D_t < 30$
   - $K_{t-1} \le D_{t-1}$ 且 $K_t > D_t$
3. 价格支撑确认
   - $Close_t > LLV_{9,t}$ 且 $Close_t > MA_{20,t}$

#### 出场（任一条件触发立即平仓）

1. 高位风险：$D_t > 80$ 且 $K_t < D_t$
2. 趋势走坏：$DIF_t < DEA_t$
3. 防御止损：$Price_t < EntryPrice \times (1 - 5\%)$
4. 时间成本过滤：持有超过 15 个**交易日**且盈利 $<2\%$

---

## 3. 与当前代码的差异评估（必须先解决/对齐）

### 3.1 指标层差异

1. **MACD Histogram 缩放差异**
   - 当前 `StockDataManager` 使用 `ta.trend.MACD(...).macd_diff()`，其定义是：
     - `MACD_Hist = MACD - MACD_Signal`
   - 新规则要求：
     - `MACD_hist = 2 * (DIF - DEA)`
   - 影响：若直接使用现有 `MACD_Hist`，仅比较“增减/符号”大多不受影响；但若后续接阈值，将产生尺度偏差。

2. **KDJ 的 J 值缺失**
   - 当前特征列有 `Stoch_K`, `Stoch_D`，无 `J`。
   - 本轮规则未直接使用 `J` 作为触发条件，但数学定义要求存在，建议在策略内部或特征层补齐计算。

3. **20 日均线字段可复用**
   - 当前已有 `EMA_20`，规则写的是 `MA(20)`。
   - 需决策：
     - 严格按 SMA20 计算；或
     - 先按 `EMA_20` 近似替代。
   - 建议：首次实现使用 **SMA20**（更贴合规则文本），避免指标口径混淆。

### 3.2 策略行为差异

1. 当前 `MACDCrossoverStrategy` 是“柱线过零 + 可选量能/趋势确认”，不等同于本规则的三段式条件链。
2. 现有 Exit 策略（ATR/Layered/ScoreBased）均非本次“4 条硬规则立即平仓”。
3. 当前常见持有天数逻辑使用自然日差值（`(current_date - entry_date).days`）；本规则要求交易日计数。

### 3.3 框架接口兼容性

1. `BaseEntryStrategy.generate_entry_signal(market_data) -> TradingSignal` 可直接承载本规则。
2. `BaseExitStrategy.generate_exit_signal(position, market_data) -> TradingSignal` 可直接承载本规则。
3. `SignalAction` 目前为 `BUY/SELL/HOLD`，本规则“立即平仓”与 `SELL` 完全兼容。

---

## 4. 设计方案（伪代码级）

## 4.1 数据与字段约定

### 输入数据

- `market_data.df_features` 需要至少包含：
  - `Close`, `High`, `Low`
  - `MACD`, `MACD_Signal`（或可推导 DIF/DEA）
  - `Stoch_K`, `Stoch_D`（对应 K/D）
  - `EMA_20`（若先临时替代 MA20）
- `position` 需要：
  - `entry_price`, `entry_date`, `entry_signal`

### 策略内部派生字段（建议）

- `macd_hist_rule = 2 * (DIF - DEA)`
- `llv9 = rolling_min(Low, 9)`
- `hhv9 = rolling_max(High, 9)`
- `rsv9`, `k_rule`, `d_rule`, `j_rule`
- `ma20_rule = rolling_mean(Close, 20)`
- `holding_days_trading = trading_bar_count(entry_date -> current_date)`

> 说明：若直接复用 `Stoch_K/Stoch_D`，则 `k_rule/d_rule` 可映射为这两列；但为严格一致，推荐保留“按公式重算”的可选路径。

---

## 4.2 Entry 伪代码（顺序判定）

```text
FUNCTION generate_entry_signal(market_data):
    df = market_data.df_features

    IF df is empty OR len(df) < minimum_required_bars:
        RETURN HOLD("Insufficient data")

    latest = df[-1]
    prev = df[-2]

    # Step 0: 准备指标（优先复用现有列，缺失则按规则重算）
    DIF_t = latest.MACD
    DEA_t = latest.MACD_Signal
    DIF_prev = prev.MACD
    DEA_prev = prev.MACD_Signal

    MACD_hist_t = 2 * (DIF_t - DEA_t)
    MACD_hist_prev = 2 * (DIF_prev - DEA_prev)

    K_t, D_t = get_kd(latest)      # 映射或重算
    K_prev, D_prev = get_kd(prev)

    LLV9_t = rolling_min_low_9_at_t
    MA20_t = SMA20_at_t
    Close_t = latest.Close

    # Step 1: MACD 收敛（必须先满足）
    cond1 = (MACD_hist_t > MACD_hist_prev)
    IF NOT cond1:
        RETURN HOLD("Cond1 fail: MACD histogram not converging")

    # Step 2: 低位 KDJ 金叉（第二门）
    cond2 = (D_t < 30) AND (K_prev <= D_prev) AND (K_t > D_t)
    IF NOT cond2:
        RETURN HOLD("Cond2 fail: no oversold KDJ golden cross")

    # Step 3: 价格支撑确认（第三门）
    cond3 = (Close_t > LLV9_t) AND (Close_t > MA20_t)
    IF NOT cond3:
        RETURN HOLD("Cond3 fail: price not above support/MA20")

    # 三条件全部通过 -> BUY
    RETURN BUY(
        confidence=predefined_or_rule_based,
        metadata={
            "entry_rule": "MACD_KDJ_3stage",
            "dif": DIF_t,
            "dea": DEA_t,
            "macd_hist_rule": MACD_hist_t,
            "k": K_t,
            "d": D_t,
            "llv9": LLV9_t,
            "ma20": MA20_t,
            "close": Close_t
        }
    )
```

---

## 4.3 Exit 伪代码（任一触发立即平仓）

```text
FUNCTION generate_exit_signal(position, market_data):
    df = market_data.df_features

    IF df is empty:
        RETURN HOLD("No feature data")

    latest = df[-1]

    DIF_t = latest.MACD
    DEA_t = latest.MACD_Signal
    K_t, D_t = get_kd(latest)

    current_price = latest.Close
    stop_price = position.entry_price * 0.95

    holding_days_trading = trading_bar_count(position.entry_date, market_data.current_date, df.index)
    pnl_pct = ((current_price / position.entry_price) - 1) * 100

    # E1: KDJ 高位死叉
    IF (D_t > 80) AND (K_t < D_t):
        RETURN SELL("E1 high-level KDJ death cross", trigger="E1")

    # E2: MACD 死叉（DIF < DEA）
    IF (DIF_t < DEA_t):
        RETURN SELL("E2 MACD dead cross", trigger="E2")

    # E3: 防御止损
    IF (current_price < stop_price):
        RETURN SELL("E3 stop loss -5%", trigger="E3", stop_price=stop_price)

    # E4: 时间成本过滤（交易日）
    IF (holding_days_trading > 15) AND (pnl_pct < 2.0):
        RETURN SELL("E4 time-cost filter", trigger="E4", holding_days_trading=holding_days_trading)

    RETURN HOLD("No exit condition met")
```

---

## 5. 接入设计（仅规划，不改代码）

## 5.1 新增策略类（建议命名）

1. Entry
   - `src/analysis/strategies/entry/macd_kdj_three_stage_entry.py`
   - 类名：`MACDKDJThreeStageEntry`
   - 继承：`BaseEntryStrategy`

2. Exit
   - `src/analysis/strategies/exit/macd_kdj_rule_exit.py`
   - 类名：`MACDKDJRuleExit`
   - 继承：`BaseExitStrategy`

## 5.2 策略注册点

- 文件：`src/utils/strategy_loader.py`
- 在 `ENTRY_STRATEGIES` 和 `EXIT_STRATEGIES` 中新增映射。

## 5.3 可配置参数（建议）

### Entry 参数

- `kd_oversold_threshold`（默认 30）
- `llv_window`（默认 9）
- `ma_window`（默认 20）
- `use_strict_rule_hist`（默认 True，是否使用 `2*(DIF-DEA)`）
- `use_strict_kd_recalc`（默认 False，True 时按 RSV 递推重算 K/D/J）

### Exit 参数

- `kd_overbought_threshold`（默认 80）
- `stop_loss_pct`（默认 0.05）
- `max_hold_trading_days`（默认 15）
- `min_profit_pct_after_max_hold`（默认 2.0）

---

## 6. 边界条件与防错设计

1. **样本不足**：
   - MA20 至少需要 20 根 bar；LLV9 需要 9 根 bar；KDJ 初始递推需要种子值。
2. **除零问题**：
   - 当 `HHV9 == LLV9` 时，`RSV` 分母为 0；建议令 `RSV=50` 或沿用上一值。
3. **NaN 传播**：
   - 任一关键字段 NaN 时返回 HOLD，并写明原因。
4. **交易日计数**：
   - 不能用自然日差值，需用 `df_features` 的交易日索引计数。
5. **口径一致性**：
   - 若同日存在多个来源的 K/D（`Stoch_*` 与重算值），需固定一套作为交易判定真值。

---

## 7. 最小验证清单（实现阶段执行）

1. **指标一致性测试**
   - 验证 `macd_hist_rule == 2*(MACD - MACD_Signal)`。
   - 验证 KDJ 重算结果与预期趋势方向一致（非严格逐点同值也可接受，需说明口径差异）。

2. **Entry 规则单测**
   - 分别构造 Cond1/Cond2/Cond3 单独失败样本。
   - 构造三条件全满足样本，预期 BUY。

3. **Exit 规则单测**
   - 分别触发 E1/E2/E3/E4，且每次返回 SELL。
   - 构造全部不触发样本，预期 HOLD。

4. **交易日计数测试**
   - 跨周末与节假日样本中验证“15 交易日”而非自然日。

---

## 8. 实施前待确认项（建议一次性锁定）

1. `MA(20)` 是否必须为 SMA20（而非 `EMA_20`）。
2. K/D 是否必须按文中 RSV 递推重算，还是允许直接使用 `Stoch_K/Stoch_D`。
3. 出场规则优先级是否固定为 E1→E2→E3→E4（当前文档按此顺序）。
4. 当同日多条件同时触发时，`metadata.trigger` 是否只保留首个触发条件。

---

## 9. 结论

在当前框架下，该策略可通过“新增 1 个 Entry + 1 个 Exit”低侵入接入；核心风险集中在指标口径（MACD 柱缩放、KDJ 重算）与交易日计数。按本设计实现后，可保证规则语义与用户给定公式/判定点一一对应。
