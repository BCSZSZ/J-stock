# Crossover Entry Group Plan

This note defines the candidate entry group for entry-signal-analysis. The goal is to avoid a MACD-heavy pool and compare distinct entry logic families across 5, 10, 20, and 40 trading-day forward returns.

## Design Principles

- Keep existing MACD-family entries to at most 10.
- Group entries by market logic, not by small parameter variations.
- Prefer named, readable entries over large generated grids for the first pass.
- Keep external `entry_filter_mode=off` for these combo entries so entry quality is measured from the entry strategy itself.
- Separate current executable entries from target entries that still need implementation.

## Current Executable Group

The current executable manifest is `tmp/entry_signal_analysis_crossover_input.json`.

### Existing MACD Family, Capped At 10

| Entry | Role |
| --- | --- |
| `MACDHist2BarAnySignMaxBiasPct10Entry` | Current production-style baseline. |
| `MACDHist2BarAnySignStrictFreshEntry` | Fresh 2-bar histogram improvement. |
| `MACDHist3BarAnySignStrictFreshEntry` | Slower fresh 3-bar histogram improvement. |
| `MACDPreCross2BarLiteComboEntry` | Early pre-cross momentum combo. |
| `MACDPreCross3BarStrictFreshEntry` | Slower strict pre-cross setup. |
| `MACDPreCross2BarMinHistDeltaNorm0015Entry` | Pre-cross with minimum histogram delta. |
| `MACDHistHysteresisEntry` | Confirmed histogram hysteresis cross. |
| `MACDHistHysteresisPreCrossEntry` | Hysteresis with early pre-cross path. |
| `CrossTrendMACDVolumeEntry` | Trend + MACD golden cross + volume, MACD above zero. |
| `CrossTrendMACDVolumeLooseEntry` | Same trend/volume setup without MACD zero-axis requirement. |

### Current Non-MACD And Cross-Family Controls

| Entry | Role |
| --- | --- |
| `CrossReboundKDJRSIEntry` | Short MA5/SMA10 cross + low KDJ cross + RSI cap. |
| `MovingAverageCrossoverEntry` | Generic EMA20/EMA50 MA golden cross. |
| `MACX_FE20_SE50_P0p0_A1_C0p58` | EMA20/EMA50 representative. |
| `MACX_FS20_SE50_P0p1_A1_C0p62` | SMA20/EMA50 representative. |
| `MACX_FE20_SE200_P0p1_A1_C0p62` | EMA20/EMA200 long-trend representative. |
| `MACX_FS25_SE200_P0p1_A1_C0p62` | SMA25/EMA200 long-trend representative. |
| `MACXF_FE20_SE50_P0p05_A1_C0p6` | Fine-grid EMA20/EMA50 representative. |
| `MACXF_FS25_SE200_P0p1_A1_C0p62` | Fine-grid SMA25/EMA200 representative. |
| `BollingerSqueezeStrategy` | Existing BOLL squeeze breakout control. |
| `IchimokuStochStrategy` | Ichimoku + stochastic/KDJ control. |
| `SimpleScorerStrategy` | Non-cross score baseline. |
| `EnhancedScorerStrategy` | Enhanced non-cross score baseline. |

## Target New Entries To Implement First

These are not yet registered in `strategy_loader.py`; do not put them into an executable manifest until implemented and tested.

| Entry | Family | Rule Summary |
| --- | --- | --- |
| `CrossShortMA5SMA10KDJ9Entry` | Short rebound | `Close > SMA10`, SMA5 crosses SMA10, KDJ9 golden cross, `KDJ_K_9 < 50`, `RSI_9 < 70`. |
| `CrossShortMA5SMA10KDJ9VolumeEntry` | Short rebound + volume | Above plus `Volume >= 1.2 * Volume_SMA_20`. |
| `CrossShortMA5SMA20KDJ9Entry` | Short rebound, slower line | `Close > SMA20`, SMA5 crosses SMA20, KDJ9 golden cross, `KDJ_K_9 < 55`, `RSI_9 < 70`. |
| `CrossMidMA10SMA20RSIVolumeEntry` | Mid trend | `Close > SMA20`, SMA10 crosses SMA20, `RSI_9 > RSI_14`, `RSI_9 < 75`, volume >= 1.2x. |
| `CrossMidMA20SMA60RSIEntry` | Mid trend | `Close > SMA60`, SMA20 crosses SMA60, `50 < RSI_14 < 75`. |
| `CrossMidMA20SMA60RSIVolumeEntry` | Mid trend + volume | Above plus `Volume >= 1.2 * Volume_SMA_20`. |
| `CrossLongSMA20SMA60PriceConfirmEntry` | Long trend | `Close > SMA60`, SMA20 crosses SMA60, `Volume >= Volume_SMA_20`. |
| `CrossLongEMA20EMA200Entry` | Long trend | `Close > EMA200`, EMA20 crosses EMA200, `Volume >= Volume_SMA_20`. |
| `CrossBollMidSqueezeExpandEntry` | BOLL recovery | Close crosses BOLL mid, bandwidth low percentile, bandwidth expanding, volume >= average. |
| `CrossBollUpperSqueezeVolumeEntry` | BOLL breakout | Close crosses BOLL upper after squeeze expansion, volume >= 1.5x, `Close > SMA60`. |
| `CrossPriceSMA20VolumeEntry` | Price/volume breakout | Close crosses SMA20, volume >= 1.5x, bullish candle, `RSI_9 < 75`. |
| `CrossMAKDJWithin3Entry` | Sequential double cross | SMA5/SMA10 cross and KDJ9 cross both occur within 3 trading days, `Close > SMA10`, `RSI_9 < 70`. |

## Second Batch Candidates

Use these only after the first batch shows enough signal count and distinct behavior.

| Entry | Reason |
| --- | --- |
| `CrossShortMA10SMA20KDJ14Entry` | Slower short rebound comparison. |
| `CrossMidMA10SMA30RSIVolumeEntry` | MA10/30 mid-trend comparison. |
| `CrossMidEMA10EMA30RSIVolumeEntry` | EMA version of mid-trend comparison. |
| `CrossLongSMA20SMA120Entry` | Slower long-trend transition. |
| `CrossVolumeVMA5VMA20PriceTrendEntry` | Volume MA golden cross with price trend. |
| `CrossBreakHH20VolumeEntry` | 20-day high breakout with volume. |
| `CrossBollMidKDJConfirmEntry` | BOLL mid recovery with KDJ confirmation. |
| `CrossBollMAWithin5Entry` | BOLL mid cross and short MA cross within 5 days. |

## Review Criteria

- Sample count: at least 200 selected samples for production candidacy.
- Median return: positive at the relevant horizon.
- Tail risk: compare P10, P25, average loss, and minimum return.
- Overlap: if two entries overlap more than 70% by signal identity, keep the cleaner or better performer.
- Regime split: separate bull, sideways, and bear behavior before treating an entry as general-purpose.
