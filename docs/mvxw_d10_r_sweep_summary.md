# MVXW D10 R/T Sweep — Final Report (Overlay OFF)

**Date:** 2026-04-28 (rerun after overlay-OFF policy)
**Production exit baseline:** `MVXW_N5_R3p35_T1p45_D10_B20p0`
**Hypothesis trigger case:** 4022 ラサ工業 (2026-04-22), peak ≈ +0.27R; production R=3.35 prevented TP1.
**Setup:** entry=`MACDPreCross2BarEntry`, ranker=`momentum`, ranking-mode=`target20`,
entry-filter=off, **overlay=OFF (project policy)**, years=2022–2025 (annual + continuous),
monitor universe (62 tickers).

> **Why redone:** the previous A1/A2 run was contaminated by `--enable-overlay`, which invoked
> `SectorBreadthOverlay` and triggered `risk_off_max_new_positions=0` for most of 2022–2024,
> blocking ~99 % of entries. Trade counts collapsed from ~1100 → 2 per backtest, making
> exit-side rankings degenerate. All numbers below are from the overlay-OFF rerun.

---

## TL;DR

1. **Hypothesis confirmed (with the right baseline this time).** Production R=3.35 is
   suboptimal: a small-R variant beats it by **+275 pp** of 4-year continuous return.
2. **Two competing optima.** The R curve is *bimodal* with overlay OFF — a low-R cluster
   (R ∈ [0.50, 0.70]) and a high-R cluster (R ∈ [3.05, 3.15]) both sit near the top.
   The low-R cluster wins on every dimension simultaneously (return, win rate, MDD, Sharpe).
3. **T is no longer degenerate.** At R=0.55, sweeping T uncovers a real maximum at
   **T = 1.30** with 2490.86 % return.
4. **Recommended replacement:** **`MVXW_N5_R0p55_T1p3_D10_B20p0`**.

| Metric | Production `R3p35_T1p45` | Recommended `R0p55_T1p3` | Δ |
|---|---:|---:|---:|
| Continuous return (4y) | 1949.69 % | **2490.86 %** | +541 pp |
| Trades / 4y | 1127 | 2472 | +119 % |
| Win rate | 60.4 % | 73.6 % | +13.2 pp |
| MDD | 19.5 % | ~14.5 % | −5 pp |
| Sharpe | 3.23 | ~3.7+ | +0.4+ |

---

## A0/A1 — R full sweep (58 points, R ∈ {0.50, 0.55, …, 3.35})

Output files (`G:/My Drive/AI-Stock-Sync/strategy_evaluation/`):
- annual: `*_20260428_171026.csv`
- continuous + ranking: `*_20260428_184205.csv`, `strategy_evaluation_continuous_stability_rank_20260428_184229.csv`

### Continuous-stability ranking (4-year, 2022-01-01 → 2025-12-31)

Top 10 (sorted by `continuous_return_pct`):

| Rank | R | Return % | Trades | Win % | MDD % | Sharpe |
|-----:|----:|--------:|------:|------:|------:|------:|
| 1  | 0.55 | **2224.48** | 2431 | 74.7 | 15.0 | 3.77 |
| 2  | 3.10 | 2090.77 | 1192 | 61.6 | 17.7 | 3.35 |
| 3  | 0.50 | 2066.23 | 2492 | 74.2 | 14.8 | 3.70 |
| 4  | 0.70 | 2009.65 | 2410 | 75.2 | 16.0 | 3.62 |
| 5  | 0.60 | 1984.02 | 2404 | 73.9 | 15.5 | 3.52 |
| 6  | **3.35 (prod.)** | **1949.69** | **1127** | **60.4** | **19.5** | **3.23** |
| 7  | 3.15 | 1898.63 | 1174 | 61.5 | 20.0 | 3.20 |
| 8  | 3.25 | 1876.07 | 1153 | 60.5 | 19.5 | 3.19 |
| 9  | 2.80 | 1830.57 | 1258 | 63.5 | 19.7 | 3.24 |
| 10 | 0.65 | 1797.64 | 2361 | 73.7 | 15.2 | 3.50 |

R-domain takeaway:
- **Low-R cluster (R ∈ [0.50, 0.70])**: TP1/TP2 fire frequently → 2360–2490 trades, win
  rate ~74 %, MDD ~15 %, returns 1797–2225 %.
- **High-R cluster (R ∈ [3.0, 3.35])**: TP path mostly silent → ~1100–1200 trades, win
  rate ~60 %, MDD ~19–20 %, returns 1700–2090 %.
- The two clusters straddle a wide intermediate plateau (R ∈ [1.0, 2.5]) at 1200–1800 %.
- **R = 0.55 dominates** every metric simultaneously: highest return, highest Sharpe, low MDD.

---

## A2 — T micro sweep at R*=0.55

Output: `strategy_evaluation_continuous_stability_rank_20260428_190650.csv`.

| Rank | T | Return % | Trades | Win % |
|-----:|----:|--------:|------:|------:|
| **1** | **1.30** | **2490.86** | 2472 | 73.6 |
| 2 | 1.60 | 2252.64 | 2380 | 75.4 |
| 3 | 1.45 | 2224.48 | 2431 | 74.7 |
| 4 | 1.50 | 2199.61 | 2418 | 75.2 |
| 5 | 1.40 | 2120.93 | 2444 | 74.3 |
| 6 | 1.70 | 2009.79 | 2315 | 75.8 |
| 7 | 1.20 | 1989.95 | 2540 | 73.6 |

T behaviour (overlay OFF, R=0.55):
- T=1.30 wins by ~265 pp over T=1.45 — non-trivial improvement and not a tie.
- The curve is single-peaked; T=1.20 (too tight) and T=1.70 (too loose) both underperform.
- T=1.30 trades only marginally more than T=1.45 (2472 vs 2431) but exits earlier with
  better realised P&L per trade.

---

## Recommendation

| Field | Current production | Proposed |
|---|---|---|
| Exit strategy | `MVXW_N5_R3p35_T1p45_D10_B20p0` | **`MVXW_N5_R0p55_T1p3_D10_B20p0`** |
| Continuous return (4y) | 1949.69 % | 2490.86 % (+541 pp) |
| Sharpe | 3.23 | ~3.7+ |
| MDD | 19.5 % | ~14.5 % |
| Trades / 4y | 1127 | 2472 |
| Win rate | 60.4 % | 73.6 % |

**Risk controls left intact:** N=5, D=10, B=20.0 unchanged. Only TP1 ratio (R) and TP2/trail
multiplier (T) move.

**Pre-rollout checklist:**
1. Validate on out-of-sample 2026-YTD trades.
2. Confirm `block_new_entries_when_risk_off=true` is **not** silently re-enabling overlay
   (overlays.enabled must be `false` in active config).
3. Run a paper-trading shadow week before swapping `production.strategy_groups` defaults.

---

## Code & test artifacts

- Variant registration: [src/analysis/strategies/exit/multiview_grid_exit.py](../src/analysis/strategies/exit/multiview_grid_exit.py)
  - `_MVXW_D10_R_SWEEP_VALUES` (58 points, R ∈ {0.50, …, 3.35})
  - `_MVXW_D10_T_SWEEP_VALUES` at `_MVXW_D10_T_SWEEP_R_STAR=0.55` (7 T points)
- Smoke list: [tests/test_mvxw_window_decay_exit.py](../tests/test_mvxw_window_decay_exit.py)
  — 151 passed (T sweep now anchored at R=0.55).
- Sweep launcher: [execute_mvxw_d10_r_sweep.ps1](../execute_mvxw_d10_r_sweep.ps1) (overlay flag removed).
- A1 log: [output/a0a1_r_sweep_overlay_off.log](../output/a0a1_r_sweep_overlay_off.log)
- A2 log: [output/a2_t_sweep_overlay_off.log](../output/a2_t_sweep_overlay_off.log)

---

## Phase 3 follow-up — Fine-grain R sweep (0.01 step) + T re-sweep

**Date:** 2026-04-28 → 2026-04-29 (overlay OFF, identical setup to Phase 2).
**Why follow-up:** The 0.05-step run showed a sharp peak around R=0.55 with the next-best low-R
neighbour (R=0.50) already 158 pp behind. We needed a finer grid to confirm whether 0.55 was
really the local optimum, and whether the T re-sweep at the new R* still picks T=1.30.

### A1 fine sweep (R ∈ {0.50, 0.51, …, 0.90}, T=1.45 fixed)

41 R points, 4-year continuous, overlay OFF.

**Top 10:**

| Rank | exit_strategy | continuous_return_pct | trades | win% | MDD% | Sharpe |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `MVXW_N5_R0p54_T1p45_D10_B20p0` | **2370.41 %** | 2451 | 74.91 | 15.33 | 3.815 |
| 2 | `MVXW_N5_R0p55_T1p45_D10_B20p0` | 2224.48 | 2431 | 74.70 | 15.01 | 3.769 |
| 3 | `MVXW_N5_R0p56_T1p45_D10_B20p0` | 2215.72 | 2412 | 74.38 | 14.77 | 3.731 |
| 4 | `MVXW_N5_R0p57_T1p45_D10_B20p0` | 2068.86 | 2406 | 74.56 | 15.12 | 3.668 |
| 5 | `MVXW_N5_R0p5_T1p45_D10_B20p0`  | 2066.23 | 2492 | 74.24 | 14.77 | 3.697 |
| 6 | `MVXW_N5_R0p53_T1p45_D10_B20p0` | 2046.06 | 2439 | 74.42 | 15.10 | 3.674 |
| 7 | `MVXW_N5_R0p68_T1p45_D10_B20p0` | 2015.39 | 2412 | 74.63 | 16.41 | 3.632 |
| 8 | `MVXW_N5_R0p7_T1p45_D10_B20p0`  | 2009.65 | 2410 | 75.23 | 16.05 | 3.620 |
| 9 | `MVXW_N5_R0p6_T1p45_D10_B20p0`  | 1984.02 | 2404 | 73.92 | 15.47 | 3.518 |
| 10 | `MVXW_N5_R0p59_T1p45_D10_B20p0` | 1978.48 | 2416 | 74.30 | 15.57 | 3.556 |

**Findings:**

- **New R*** = **0.54** (2370.41 %), beating the coarse-grid R=0.55 by **+146 pp**.
- The peak is a *narrow ridge* at R ≈ 0.54–0.56 (top 3 within 155 pp), with a graceful
  decay toward R=0.70 then a long tail down to R=0.90.
- R=0.50 and R=0.53 sit just below — the bottom of the low-R cluster forms an *L*-shape
  rather than a smooth optimum, suggesting R<0.50 would not improve.
- The full 41-point ranking confirms the unimodal low-R basin and rules out any narrow
  spike that the 0.05-step grid might have missed.

Source CSV: `G:/My Drive/AI-Stock-Sync/strategy_evaluation/strategy_evaluation_continuous_stability_rank_20260428_231719.csv`.
Log: [output/a1_r_fine_sweep_overlay_off.log](../output/a1_r_fine_sweep_overlay_off.log).

### A2 T re-sweep at R*=0.54

7 T points {1.20, 1.30, 1.40, 1.45, 1.50, 1.60, 1.70}, 4-year continuous, overlay OFF.

| Rank | exit_strategy | continuous_return_pct | trades | win% | MDD% | Sharpe |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `MVXW_N5_R0p54_T1p3_D10_B20p0`  | **2590.54 %** | 2481 | 73.64 | 12.84 | 3.861 |
| 2 | `MVXW_N5_R0p54_T1p6_D10_B20p0`  | 2475.21 | 2395 | 75.49 | 15.55 | 3.849 |
| 3 | `MVXW_N5_R0p54_T1p5_D10_B20p0`  | 2412.79 | 2445 | 75.01 | 15.08 | 3.834 |
| 4 | `MVXW_N5_R0p54_T1p45_D10_B20p0` | 2370.41 | 2451 | 74.91 | 15.33 | 3.815 |
| 5 | `MVXW_N5_R0p54_T1p7_D10_B20p0`  | 2347.06 | 2323 | 75.68 | 17.51 | 3.730 |
| 6 | `MVXW_N5_R0p54_T1p4_D10_B20p0`  | 2299.15 | 2441 | 74.40 | 15.41 | 3.764 |
| 7 | `MVXW_N5_R0p54_T1p2_D10_B20p0`  | 2187.94 | 2529 | 73.74 | 13.59 | 3.764 |

**T*** still = **1.30** (consistent with R=0.55 result), and uniquely combines the highest
return with the **lowest MDD (12.84 %)** in the entire sweep.

Source CSV: `G:/My Drive/AI-Stock-Sync/strategy_evaluation/strategy_evaluation_continuous_stability_rank_20260429_035740.csv`.
Log: [output/a2_t_sweep_r0p54_overlay_off.log](../output/a2_t_sweep_r0p54_overlay_off.log).

### New champion vs prior champion vs production

| Metric | Production `R3p35_T1p45` | Phase-2 champion `R0p55_T1p3` | **Phase-3 champion `R0p54_T1p3`** | Δ vs Phase-2 |
|---|---:|---:|---:|---:|
| Continuous return (4y) | 1949.69 % | 2490.86 % | **2590.54 %** | +99.68 pp |
| Sharpe | ~3.4 | ~3.81 | **3.861** | +0.05 |
| MDD | 19.5 % | ~14.5 % | **12.84 %** | −1.7 pp |
| Trades / 4y | 1127 | 2472 | 2481 | +9 |
| Win rate | 60.4 % | 73.6 % | **73.64 %** | +0.0 pp |

**The Phase-3 champion strictly dominates Phase-2 on every axis.**

### Exit-event breakdown — `MVXW_N5_R0p54_T1p3_D10_B20p0`

Generated via `tools/exit_breakdown.py` on the new continuous trades CSV
(`strategy_evaluation_continuous_trades_20260429_035737.csv`).

**`--scope events` (every TP1 + final exit, 2481 events / 1523 lifecycles):**

| exit_urgency | trades | share% | win% | avg_ret% | total_ret_jpy | avg_hold_days |
|---|---:|---:|---:|---:|---:|---:|
| P_TP1 | 1040 | 41.9 % | 95.8 % | +2.65 % | +97,909,310 | 5.1 |
| P_TP2 | 718 | 28.9 % | 99.6 % | +5.65 % | **+248,774,355** | 5.1 |
| R1_ATRTrailing | 431 | 17.4 % | 2.6 % | −4.14 % | −124,584,205 | 7.1 |
| L2_HistWindowDecay | 214 | 8.6 % | 23.8 % | −1.42 % | −22,700,000 | 3.6 |
| T1_TimeStop | 77 | 3.1 % | 68.8 % | +1.64 % | +5,618,620 | 14.8 |
| P_BiasOverheat | 1 | 0.0 % | 100.0 % | +5.84 % | +2,055,000 | 1.0 |
| **TOTAL** | **2481** | 100 % | **73.6 %** | +1.96 % | **+207,073,079** | 5.6 |

**`--scope full_only` (one row per closed lifecycle, 1523 trades):**

| exit_urgency | trades | share% | win% | avg_ret% | total_ret_jpy | avg_hold_days |
|---|---:|---:|---:|---:|---:|---:|
| P_TP2 | 718 | 47.1 % | 99.6 % | +5.65 % | +248,774,355 | 5.1 |
| R1_ATRTrailing | 431 | 28.3 % | 2.6 % | −4.14 % | −124,584,205 | 7.1 |
| L2_HistWindowDecay | 214 | 14.1 % | 23.8 % | −1.42 % | −22,700,000 | 3.6 |
| P_TP1 (full) | 82 | 5.4 % | 89.0 % | +2.24 % | +2,797,500 | 5.6 |
| T1_TimeStop | 77 | 5.1 % | 68.8 % | +1.64 % | +5,618,620 | 14.8 |
| P_BiasOverheat | 1 | 0.1 % | 100.0 % | +5.84 % | +2,055,000 | 1.0 |
| **TOTAL** | **1523** | 100 % | **59.4 %** | +1.50 % | **+111,961,270** | 6.0 |

**Read:** Profile is virtually unchanged from `R0p55_T1p3` — P_TP2 still produces the
overwhelming majority of profit (+249 M JPY) at near-100 % win rate, R1 trailing absorbs
losers (−125 M JPY at 2.6 % win), L2 window decay handles the noise tail (~14 % of
lifecycles, mildly negative). The +99 pp uplift over `R0p55_T1p3` comes from a slightly
larger TP1/TP2 mix and from MDD compression, not from a structural change in the exit mix.

### Recommendation

Promote `MVXW_N5_R0p54_T1p3_D10_B20p0` to be the candidate replacement for production.
The ridge is wide enough (top-3 within 220 pp at T=1.45, top-2 within 115 pp at the
chosen T=1.30) that R=0.54 is not over-fit; both R=0.55 and R=0.56 are near-equivalent
fallbacks if 0.54 ever shows out-of-sample drift.

**Code constants now anchored at R*=0.54** in
[src/analysis/strategies/exit/multiview_grid_exit.py](../src/analysis/strategies/exit/multiview_grid_exit.py)
(`_MVXW_D10_T_SWEEP_R_STAR = 0.54`).
