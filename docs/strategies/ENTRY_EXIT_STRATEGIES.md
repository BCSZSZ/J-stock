# 入场/出场策略逻辑与数学公式（源码对齐）

本文覆盖 `src/utils/strategy_loader.py` 注册的全部策略。

## 1. 策略全集

Entry（8）：

- `SimpleScorerStrategy`
- `EnhancedScorerStrategy`
- `MACDCrossoverStrategy`
- `MACDKDJThreeStageEntry`
- `MACDKDJThreeStageEntryA`
- `MACDKDJThreeStageEntryB`
- `BollingerSqueezeStrategy`
- `IchimokuStochStrategy`

Exit（9）：

- `ATRExitStrategy`
- `ScoreBasedExitStrategy`
- `LayeredExitStrategy`
- `BollingerDynamicExit`
- `ADXTrendExhaustionExit`
- `MACDKDJRuleExit`
- `MACDKDJRuleExitA`
- `MACDKDJRuleExitB`
- `MVX_N9_R3p5_T1p6_D20_B15`

---

## 2. 打分体系（Scorer 相关）

## 2.1 综合分数

\[
\text{CompositeScore}=w_t S_t+w_i S_i+w_f S_f+w_v S_v
\]

- `Simple`: \((w_t,w_i,w_f,w_v)=(0.4,0.3,0.2,0.1)\)
- `Enhanced`: \((0.35,0.35,0.2,0.1)\)

### 技术分 \(S_t\)

基准 50，按条件加减：

- Close > EMA20 > EMA50 > EMA200：+20
- Close > EMA200：+10；Close < EMA200：-20
- RSI 在 [40,65]：+10；RSI>75：-10；RSI<30：+5
- MACD_Hist>0：+10；且 MACD>0 再 +5

最终 clip 到 [0,100]。

### 机构分 \(S_i\)

简单版（默认）：近 `lookback_days` 外资净流入 `FrgnBal`：

- 净流入 >0：+20；且最新值高于均值再 +10
- 净流入 <0：-15

增强版（Smart Money 模式）会聚合 Smart vs Dumb 资金并加入加速项。

### 基本面分 \(S_f\)

基准 50，依据环比（上一期财报）：

- 营收增速 \(>10\%\)：+15；\(>5\%\)：+10；\(<-5\%\)：-15
- 营业利润增速 \(>15\%\)：+20；\(>8\%\)：+12；\(<-10\%\)：-20
- 实际销售额 > 预测销售额 × 1.03：+15

最终 clip 到 [0,100]。

### 波动风险分 \(S_v\)

基准 50，以 ATR 的 z-score 判断：
\[
z*{ATR}=\frac{ATR_t-\mu*{60}}{\sigma\_{60}}
\]

- \(z\_{ATR}< -0.5\)：+20（低波动）
- \(z\_{ATR}>1.0\)：-20（高波动）

最终 clip 到 [0,100]。

### 财报风险惩罚

- `Simple`: 若未来 7 天内有财报，\(Score\leftarrow 0.8\times Score\)
- `Enhanced`: 分段惩罚
  - 1 天内：×0.5
  - 3 天内：×0.7
  - 7 天内：×0.85

---

## 3. Entry 策略

## 3.1 `SimpleScorerStrategy` / `EnhancedScorerStrategy`

买入条件：
\[
\text{CompositeScore}\_{adj} \ge \text{buy_threshold} \;(默认65)
\]

信号置信度：
\[
\text{confidence}=\min\left(\frac{\text{score}}{100},1\right)
\]

## 3.2 `MACDCrossoverStrategy`

核心触发：MACD 柱由负转正（金叉）
\[
MACD_Hist\_{t-1}<0\land MACD_Hist_t>0
\]

初始 `confidence=0.7`，再按确认项加减：

- 量能确认：\(Volume_t / SMA20(Volume) >1.2\) 加 0.1，否则减 0.05
- 趋势确认：\(Close_t>EMA200_t\) 加 0.1，否则减 0.15

最终 `clip` 到 [0,1]，且需 `confidence >= min_confidence`（默认 0.6）才 BUY。

## 3.3 `MACDKDJThreeStageEntry`（含 A/B）

必须同时满足：

1. MACD 收敛：\(2\cdot Hist*t > 2\cdot Hist*{t-1}\)
2. KDJ 超卖金叉：\(K*{t-1}\le D*{t-1}\land K_t>D_t\land D_t<\theta\)
3. 价格支撑：\(Close*t>LLV*{n}(Low)\land Close_t>SMA20_t\)
4. 趋势过滤（可选）：`require_above_ema200`、`require_macd_positive`
5. 波动过滤：\(ATR_t/Close_t \le max_atr_pct\)

变体参数：

- A：`kd_oversold_threshold=20`, `require_macd_positive=True`, `max_atr_pct=0.04`
- B：`kd_oversold_threshold=25`, `require_macd_positive=False`, `max_atr_pct=0.06`

## 3.4 `BollingerSqueezeStrategy`

关键条件：

- 挤压：\(BB_Width*t < P_q(BB_Width*{hist})\)（默认 20 分位）
- 突破：\(BB_PctB*t>1\land BB_PctB*{t-1}\le1\)
- 放量：\(Volume_t > m\cdot Volume_SMA20_t\)（默认 \(m=1.5\)）
- 趋势确认：\(ADX14_t>20\)

通过加权累积 `confidence` 判定，默认 `min_confidence=0.6`。

## 3.5 `IchimokuStochStrategy`

关键条件：

- 云上：\(Close_t>\max(SpanA_t,SpanB_t)\)
- 云层多头：\(SpanA_t>SpanB_t\)
- KDJ 金叉：\(K*{t-1}<D*{t-1}\land K_t>D_t\)
- 超卖强化：\(K_t<stoch_oversold\)
- OBV 斜率：
  \[
  \text{obv_slope}=\frac{OBV*t-OBV*{t-L}}{L}
  \]
  `obv_slope>0` 视为资金配合。

---

## 4. Exit 策略

## 4.1 `ATRExitStrategy`

按优先级触发（先命中先卖）：

1. 硬止损：\(Close_t < EntryPrice-2\cdot ATR_t\)
2. 跟踪止损：\(Close_t < PeakPrice-3\cdot ATR_t\)
3. 动量衰竭：\(RSI_t>70\land Close_t<EMA20_t\)
4. 趋势破坏：`detect_trend_breakdown` 返回非空

## 4.2 `ScoreBasedExitStrategy`

计算当前综合分，若相对入场分衰减超阈值则退出：
\[
\Delta S = S*{entry}-S*{current}
\]
当 \(\Delta S > score_buffer\)（默认 15）触发 SELL。

## 4.3 `LayeredExitStrategy`

6 层退出，按顺序：

1. 机构撤离 `detect_institutional_exodus`
2. 趋势破坏 `detect_trend_breakdown`
3. 入场后市场恶化 `detect_market_deterioration`
4. 多维弱化（评分组件或纯技术弱化）
5. ATR 跟踪止损：\(Close_t < Peak-2\cdot ATR_t\)
6. 时间审查（默认每 90 天）

## 4.4 `BollingerDynamicExit`

分层：

- P0 紧急：\(BB_PctB_t<0\)
- P1 利润保护：盈利 >5% 且 `PctB` 从高位阈值（默认 0.7）下穿，同时 OBV 斜率 <0
- P2 超买回落：\(BB_PctB_t>0.9\) 且 KDJ 超买死叉

## 4.5 `ADXTrendExhaustionExit`

分层：

- P0 ADX 衰竭：
  \[
  \text{decline\%}=\left(1-\frac{ADX*t}{ADX*{peak}}\right)\times100
  \]
  当 `decline% >= 50` 且 `ADX_peak >= 25` 触发
- P1 云层破位：由云上跌破云底
- P2 缩量破位：\(Volume/Volume_SMA20<0.7\land Close<EMA20\)
- P3 EMA20 下穿 EMA50

## 4.6 `MACDKDJRuleExit`（含 A/B）

按 E1→E4：

- E1：\(D_t>80\land K_t<D_t\)
- E2：MACD 死叉连续 N 天（默认 N=3）
- E3：止损：\(Close_t<Entry\cdot(1-stop_loss_pct)\)
- E4：持有交易日数超过上限且收益低于阈值

变体：

- A：`stop_loss_pct=0.04`
- B：`stop_loss_pct=0.06`, `kd_overbought_threshold=85`

## 4.7 `MultiViewCompositeExit`（MVX 默认参数）

默认策略名：`MVX_N9_R3p5_T1p6_D20_B15`

参数映射：

- `N=9` -> `hist_shrink_n`
- `R=3.5` -> `r_mult`
- `T=1.6` -> `trail_mult`
- `D=20` -> `time_stop_days`
- `B=15` -> `bias_exit_threshold_pct`
