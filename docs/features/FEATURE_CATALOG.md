# Feature 计算方法与全集（源码对齐）

本文覆盖：

1. `StockDataManager.compute_features` 产出的技术指标列
2. `UniverseSelector` 计算的派生选股特征
3. universe 全局归一化与总分列

## 1. 原始输入列

来自 `data/raw_prices/{ticker}.parquet`：

- `Date`
- `Open`
- `High`
- `Low`
- `Close`
- `Volume`

---

## 2. 技术指标特征（`compute_features`）

## 2.1 趋势类

- `EMA_20`, `EMA_50`, `EMA_200`
- `SMA_20`
- `ADX_14`
- `Ichi_Tenkan`, `Ichi_Kijun`, `Ichi_SpanA`, `Ichi_SpanB`

## 2.2 动量类

- `RSI`（window=14）
- `MACD`, `MACD_Signal`, `MACD_Hist`（12,26,9）
- `Stoch_K`, `Stoch_D`（window=14, smooth=3）
- `KDJ_K_9`, `KDJ_D_9`, `KDJ_J_9`

其中：
\[
KDJ_J_9 = 3\cdot KDJ_K_9 - 2\cdot KDJ_D_9
\]

## 2.3 波动类

- `ATR`（window=14）
- `BB_Upper`, `BB_Lower`, `BB_Middle`
- `BB_Width`, `BB_PctB`

## 2.4 成交量类

- `Volume_SMA_20`
- `OBV`

说明：

- 指标由 `ta` 库计算
- 特征文件落盘：`data/features/{ticker}_features.parquet`

---

## 3. Universe 派生特征（单股）

定义于 `src/universe/stock_selector.py::_extract_stock_features`。

对每只股票，基于最新指标和历史窗口计算：

- `MedianTurnover`
  \[
  TradingValue*t = Close_t \cdot Volume_t,
  \quad MedianTurnover = \text{median}(TradingValue*{t-19:t})
  \]

- `ATR_Ratio`
  \[
  ATR_Ratio = \frac{ATR_t}{Close_t}
  \]

- `TrendStrength`
  \[
  TrendStrength = \frac{Close_t - EMA200_t}{EMA200_t}
  \]

- `Momentum_20d`
  \[
  Momentum\_{20d} = \frac{Close*t - Close*{t-20}}{Close\_{t-20}}
  \]

- `Volume_Surge`
  \[
  Volume_Surge = \frac{\text{mean}(Volume*{t-19:t})}{\text{mean}(Volume*{t-119:t-20})}
  \]

输出字段：

- `Code`, `CompanyName`, `Close`, `ATR`, `ATR_Ratio`, `EMA_200`
- `MedianTurnover`, `TrendStrength`, `Momentum_20d`, `Volume_Surge`, `DataDate`

---

## 4. Universe 过滤与归一化特征

## 4.1 硬过滤

- `Close > 100`
- `MedianTurnover > 500,000,000`
- `0.015 < ATR_Ratio < 0.050`

## 4.2 排名归一化（百分位）

在 `main.py cmd_universe` 中，进行全局归一化：

- `Rank_Vol = rank_pct(ATR_Ratio)`
- `Rank_Liq = rank_pct(MedianTurnover)`
- `Rank_Trend = rank_pct(TrendStrength)`
- `Rank_Momentum = rank_pct(Momentum_20d)`
- `Rank_VolSurge = rank_pct(Volume_Surge)`

## 4.3 最终总分

\[
TotalScore = 0.25\cdot Rank_Vol + 0.25\cdot Rank_Liq + 0.20\cdot Rank_Trend + 0.20\cdot Rank_Momentum + 0.10\cdot Rank_VolSurge
\]

并取 `Top N` 输出。

---

## 5. 与策略消费关系（关键映射）

常见策略依赖列：

- MACD 系：`MACD`, `MACD_Signal`, `MACD_Hist`
- KDJ 系：`KDJ_K_9`, `KDJ_D_9`, `KDJ_J_9` 或 `Stoch_K`, `Stoch_D`
- 趋势过滤：`EMA_20`, `EMA_50`, `EMA_200`, `ADX_14`
- 波动退出：`ATR`, `BB_PctB`, `BB_Width`
- 资金确认：`Volume`, `Volume_SMA_20`, `OBV`
- 一目均衡：`Ichi_SpanA`, `Ichi_SpanB`

这也是回测/生产/信号统一能够工作的最小特征依赖集合。
