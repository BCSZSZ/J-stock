# MVX Walk-Forward Validation Design (Fixed 7x0.18)

## 1) Objective

Use walk-forward validation to test whether MVX exit parameters are robust or overfit.

Scope is intentionally narrow:

- Entry strategy fixed: MACDCrossoverStrategy
- Position policy fixed: max_positions=7, max_position_pct=0.18
- Overlay fixed: off
- Entry filter fixed: off
- Initial capital fixed: 8,000,000 JPY (for the first version)

## 2) Parameter Universe

Current MVX grid in code:

- D fixed at 18
- N in {8, 9, 10}
- R in {3.4, 3.5, 3.6}
- T in {1.5, 1.6, 1.7}
- B in {19.5, 20.0, 20.5}

Total candidates: 3 x 3 x 3 x 3 = 81.

## 3) Backtest Matrix and Count

Assumption: one strategy x one year = one backtest task.

- Years: 2021, 2022, 2023, 2024, 2025 (5 years)
- Strategies: 81 MVX variants

Strict arithmetic is 81 x 5 = 405 annual tasks.

If you want to keep the planning envelope as 420 tasks, treat it as 405 core tasks + 15 reserve tasks (reruns/sanity checks/report regeneration).

## 4) Walk-Forward Folds

Fold A:

- Train: 2021-2022
- Test: 2023

Fold B:

- Train: 2021-2023
- Test: 2024

Fold C:

- Train: 2021-2024
- Test: 2025

## 5) Train-Time Ranking Rule (Selection Rule)

For each fold, compute a train score per MVX variant:

- Return score: normalized train cumulative return
- Risk score: 50% normalized Sharpe + 50% normalized drawdown quality

Composite score:

Score = 0.6 x ReturnScore + 0.4 x RiskScore

Select Top 1 (and optionally Top 3 for robustness view).

## 6) What Happens After 405/420 Tasks Finish

After annual tasks finish, no new backtests are required for the first analysis pass.
The next steps are pure analysis on the result table:

1. Build a panel table: (year, mvx_variant, return, sharpe, mdd, trades).
2. For each fold, rank all 81 variants on train years using the 60/40 rule.
3. Take train winner(s), evaluate only on the next-year test set.
4. Record out-of-sample rank and out-of-sample metrics.
5. Aggregate over folds:
   - average test rank
   - median test return
   - worst test drawdown
   - fold-to-fold winner overlap (stability)
6. Produce final recommendation buckets:
   - robust candidate
   - aggressive candidate
   - unstable/overfit candidates to avoid

## 7) Capital Handling Across Years (Critical Clarification)

In the current annual evaluation workflow, each year is an independent period.

- 2022 does NOT start from 2021 ending capital.
- Each year starts from the configured starting capital.

So the annual result set is for comparability across years, not capital compounding across years.

If a compounding test is desired, add a separate continuous-period experiment (2021-2025 as one uninterrupted backtest) and compare conclusions.

## 8) Outputs

Mandatory outputs:

1. Walk-forward summary table by fold.
2. OOS leaderboard (mean/median test performance).
3. Stability diagnostics (winner churn, rank volatility).
4. Final decision memo: keep current MVX or switch.

## 9) Phase-2 Extension (Only If Needed)

If fold stability is weak under D=18-fixed grid, extend D dimension in a controlled way:

- D in {16, 18, 20, 22}

Then repeat the same walk-forward protocol.