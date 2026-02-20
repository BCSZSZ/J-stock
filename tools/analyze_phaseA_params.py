from pathlib import Path
import re

import pandas as pd


def main() -> None:
    raw = Path(r"G:/My Drive/AI-Stock-Sync/strategy_evaluation/phaseA_mvx_3m_raw_20260220_161229.csv")
    df = pd.read_csv(raw)

    pattern = re.compile(r"MVX_N(?P<N>\d+)_R(?P<R>[0-9p]+)_T(?P<T>[0-9p]+)_D(?P<D>\d+)_B(?P<B>\d+)")
    parts = df["exit_strategy"].str.extract(pattern)

    for col in ["N", "D", "B"]:
        parts[col] = parts[col].astype(int)
    for col in ["R", "T"]:
        parts[col] = parts[col].str.replace("p", ".", regex=False).astype(float)

    df = pd.concat([df, parts], axis=1)

    print(f"rows={len(df)}")
    print(f"overall_mean_return={df['return_pct'].mean():.4f}")
    print(f"overall_mean_alpha={df['alpha'].mean():.4f}")

    for col in ["N", "R", "T", "D", "B"]:
        print(f"\n=== {col} main effect (mean return/alpha) ===")
        grouped = (
            df.groupby(col)
            .agg(
                mean_return=("return_pct", "mean"),
                mean_alpha=("alpha", "mean"),
                best_return=("return_pct", "max"),
                worst_return=("return_pct", "min"),
            )
            .reset_index()
            .sort_values("mean_return", ascending=False)
        )
        print(grouped.round(4).to_string(index=False))

    print("\n=== N x R pivot (mean return) ===")
    print(df.pivot_table(index="N", columns="R", values="return_pct", aggfunc="mean").round(4).to_string())

    print("\n=== R x T pivot (mean return) ===")
    print(df.pivot_table(index="R", columns="T", values="return_pct", aggfunc="mean").round(4).to_string())

    print("\n=== Top 20 combos ===")
    print(
        df[["exit_strategy", "return_pct", "alpha", "sharpe_ratio", "win_rate_pct"]]
        .sort_values("return_pct", ascending=False)
        .head(20)
        .round(4)
        .to_string(index=False)
    )

    trade_path = Path("strategy_evaluation/mvx_vs_score_tradelevel_20260220_164214.csv")
    if trade_path.exists():
        td = pd.read_csv(trade_path)
        mvx = td[td["strategy"] == "MVX_N4_R1p8_T2p2_D20_B15"]
        print(f"\nMVX trades={len(mvx)}")
        print("=== MVX trigger counts ===")
        print(mvx["exit_urgency"].value_counts(dropna=False).to_string())
    else:
        print(f"\nTrade-level file not found: {trade_path}")


if __name__ == "__main__":
    main()
