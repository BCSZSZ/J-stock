import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd


@dataclass
class FoldConfig:
    test_year: int
    train_years: List[int]


def extract_year(period_value: str) -> int:
    m = re.match(r"^(\d{4})", str(period_value or ""))
    if not m:
        raise ValueError(f"Cannot parse year from period: {period_value}")
    return int(m.group(1))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generic walk-forward stability analysis for evaluation raw CSV."
    )
    p.add_argument("--raw-csv", required=True, help="Path to evaluation raw CSV")
    p.add_argument(
        "--group-cols",
        nargs="+",
        default=["entry_strategy", "exit_strategy", "entry_filter"],
        help="Columns defining one strategy unit",
    )
    p.add_argument(
        "--min-train-years",
        type=int,
        default=2,
        help="Minimum number of years before each test year",
    )
    p.add_argument(
        "--std-penalty",
        type=float,
        default=0.50,
        help="Penalty coefficient for fold-to-fold utility std",
    )
    p.add_argument(
        "--oos-positive-weight",
        type=float,
        default=0.20,
        help="Weight for positive OOS alpha rate in stability score",
    )
    p.add_argument(
        "--selection-model",
        default="risk60_profit40_v2",
        choices=["risk60_profit40_v2", "rank60_40"],
        help="Scoring model for fold train selection and OOS utility",
    )
    p.add_argument(
        "--output-dir",
        default="strategy_evaluation",
        help="Directory for output CSV/MD",
    )
    return p.parse_args()


def ensure_columns(df: pd.DataFrame, cols: List[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def pct_rank(series: pd.Series, higher_is_better: bool) -> pd.Series:
    if higher_is_better:
        return series.rank(pct=True, ascending=True, method="average")
    return series.rank(pct=True, ascending=False, method="average")


def minmax_normalize(series: pd.Series, higher_is_better: bool) -> pd.Series:
    s = series.fillna(0.0).astype(float)
    s_min = float(s.min())
    s_max = float(s.max())
    span = s_max - s_min
    if span <= 1e-12:
        return pd.Series(np.full(len(s), 0.5), index=s.index)
    if higher_is_better:
        return (s - s_min) / span
    return (s_max - s) / span


def build_fold_configs(years: List[int], min_train_years: int) -> List[FoldConfig]:
    years = sorted(set(years))
    folds: List[FoldConfig] = []
    for y in years:
        train = [t for t in years if t < y]
        if len(train) < min_train_years:
            continue
        folds.append(FoldConfig(test_year=y, train_years=train))
    return folds


def aggregate_metrics(df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    agg = (
        df.groupby(group_cols, dropna=False)
        .agg(
            return_mean=("return_pct", "mean"),
            alpha_mean=("alpha", "mean"),
            sharpe_mean=("sharpe_ratio", "mean"),
            mdd_mean=("max_drawdown_pct", "mean"),
            worst_year_return=("return_pct", "min"),
            positive_alpha_ratio=("alpha", lambda s: float((s > 0).mean())),
            periods=("period", "nunique"),
        )
        .reset_index()
    )
    for c in [
        "return_mean",
        "alpha_mean",
        "sharpe_mean",
        "mdd_mean",
        "worst_year_return",
        "positive_alpha_ratio",
    ]:
        agg[c] = agg[c].fillna(0.0)
    return agg


def add_train_score(agg: pd.DataFrame, model: str) -> pd.DataFrame:
    out = agg.copy()
    if model == "risk60_profit40_v2":
        out["mdd_inverse_norm"] = minmax_normalize(out["mdd_mean"], higher_is_better=False)
        out["worst_year_return_norm"] = minmax_normalize(
            out["worst_year_return"], higher_is_better=True
        )
        out["avg_alpha_norm"] = minmax_normalize(out["alpha_mean"], higher_is_better=True)
        out["positive_alpha_ratio_norm"] = minmax_normalize(
            out["positive_alpha_ratio"], higher_is_better=True
        )
        out["train_score"] = (
            0.35 * out["mdd_inverse_norm"]
            + 0.25 * out["worst_year_return_norm"]
            + 0.25 * out["avg_alpha_norm"]
            + 0.15 * out["positive_alpha_ratio_norm"]
        )
        return out

    out["ret_rank"] = pct_rank(out["return_mean"], higher_is_better=True)
    out["sharpe_rank"] = pct_rank(out["sharpe_mean"], higher_is_better=True)
    out["mdd_quality_rank"] = pct_rank(out["mdd_mean"], higher_is_better=False)
    out["risk_quality"] = 0.5 * out["sharpe_rank"] + 0.5 * out["mdd_quality_rank"]
    out["train_score"] = 0.6 * out["ret_rank"] + 0.4 * out["risk_quality"]
    return out


def add_test_utility(agg: pd.DataFrame, model: str) -> pd.DataFrame:
    out = agg.copy()
    if model == "risk60_profit40_v2":
        out["mdd_inverse_norm_test"] = minmax_normalize(
            out["mdd_mean"], higher_is_better=False
        )
        out["worst_year_return_norm_test"] = minmax_normalize(
            out["worst_year_return"], higher_is_better=True
        )
        out["avg_alpha_norm_test"] = minmax_normalize(
            out["alpha_mean"], higher_is_better=True
        )
        out["positive_alpha_ratio_norm_test"] = minmax_normalize(
            out["positive_alpha_ratio"], higher_is_better=True
        )
        out["oos_utility"] = (
            0.35 * out["mdd_inverse_norm_test"]
            + 0.25 * out["worst_year_return_norm_test"]
            + 0.25 * out["avg_alpha_norm_test"]
            + 0.15 * out["positive_alpha_ratio_norm_test"]
        )
        return out

    out["ret_rank_test"] = pct_rank(out["return_mean"], higher_is_better=True)
    out["sharpe_rank_test"] = pct_rank(out["sharpe_mean"], higher_is_better=True)
    out["mdd_quality_rank_test"] = pct_rank(out["mdd_mean"], higher_is_better=False)
    out["risk_quality_test"] = (
        0.5 * out["sharpe_rank_test"] + 0.5 * out["mdd_quality_rank_test"]
    )
    out["oos_utility"] = 0.6 * out["ret_rank_test"] + 0.4 * out["risk_quality_test"]
    return out


def strategy_label(row: pd.Series, cols: List[str]) -> str:
    return " | ".join(f"{c}={row[c]}" for c in cols)


def main() -> None:
    args = parse_args()

    raw_path = Path(args.raw_csv)
    if not raw_path.exists():
        raise FileNotFoundError(f"raw csv not found: {raw_path}")

    df = pd.read_csv(raw_path)
    ensure_columns(
        df,
        args.group_cols
        + ["period", "return_pct", "alpha", "sharpe_ratio", "max_drawdown_pct"],
    )

    df["year"] = df["period"].apply(extract_year)
    years = sorted(df["year"].unique().tolist())
    folds = build_fold_configs(years, args.min_train_years)
    if not folds:
        raise ValueError("No valid folds. Check min-train-years and period coverage.")

    fold_winners = []
    oos_all = []

    for fold in folds:
        train_df = df[df["year"].isin(fold.train_years)]
        test_df = df[df["year"] == fold.test_year]

        train_agg = add_train_score(
            aggregate_metrics(train_df, args.group_cols), args.selection_model
        )
        train_agg = train_agg.sort_values("train_score", ascending=False).reset_index(
            drop=True
        )

        test_agg = add_test_utility(
            aggregate_metrics(test_df, args.group_cols), args.selection_model
        )
        test_agg = test_agg.sort_values("oos_utility", ascending=False).reset_index(
            drop=True
        )
        test_agg["oos_rank"] = np.arange(1, len(test_agg) + 1)
        test_agg["oos_rank_pct"] = test_agg["oos_rank"] / len(test_agg)

        winner = train_agg.iloc[0]
        winner_key = tuple(winner[c] for c in args.group_cols)

        merged = test_agg.copy()
        merged["test_year"] = fold.test_year
        merged["train_years"] = ",".join(map(str, fold.train_years))
        oos_all.append(merged)

        winner_test = test_agg[
            test_agg[args.group_cols].apply(tuple, axis=1) == winner_key
        ]
        if winner_test.empty:
            continue
        wt = winner_test.iloc[0]

        fold_winners.append(
            {
                "test_year": fold.test_year,
                "train_years": ",".join(map(str, fold.train_years)),
                "winner_label": strategy_label(winner, args.group_cols),
                "train_score": float(winner["train_score"]),
                "train_return_mean": float(winner["return_mean"]),
                "train_sharpe_mean": float(winner["sharpe_mean"]),
                "train_mdd_mean": float(winner["mdd_mean"]),
                "test_return": float(wt["return_mean"]),
                "test_alpha": float(wt["alpha_mean"]),
                "test_sharpe": float(wt["sharpe_mean"]),
                "test_mdd": float(wt["mdd_mean"]),
                "test_oos_rank": int(wt["oos_rank"]),
                "test_oos_rank_pct": float(wt["oos_rank_pct"]),
                "test_oos_utility": float(wt["oos_utility"]),
            }
        )

    oos_df = pd.concat(oos_all, ignore_index=True)

    grp = (
        oos_df.groupby(args.group_cols, dropna=False)
        .agg(
            folds=("test_year", "nunique"),
            oos_utility_mean=("oos_utility", "mean"),
            oos_utility_std=("oos_utility", "std"),
            oos_return_mean=("return_mean", "mean"),
            oos_return_median=("return_mean", "median"),
            oos_alpha_mean=("alpha_mean", "mean"),
            oos_sharpe_mean=("sharpe_mean", "mean"),
            oos_mdd_mean=("mdd_mean", "mean"),
            oos_mdd_worst=("mdd_mean", "max"),
            oos_positive_alpha_rate=("alpha_mean", lambda s: float((s > 0).mean())),
            oos_top_quartile_rate=(
                "oos_rank_pct",
                lambda s: float((s <= 0.25).mean()),
            ),
        )
        .reset_index()
    )

    grp["oos_utility_std"] = grp["oos_utility_std"].fillna(0.0)

    stability_core = grp["oos_utility_mean"] - args.std_penalty * grp["oos_utility_std"]
    grp["stability_score"] = 100.0 * (
        (1.0 - args.oos_positive_weight) * stability_core
        + args.oos_positive_weight * grp["oos_positive_alpha_rate"]
    )
    grp["stability_score"] = grp["stability_score"].clip(lower=0.0, upper=100.0)

    grp["strategy_label"] = grp.apply(lambda r: strategy_label(r, args.group_cols), axis=1)
    grp = grp.sort_values("stability_score", ascending=False).reset_index(drop=True)

    winners_df = pd.DataFrame(fold_winners)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    winners_csv = out_dir / f"walk_forward_fold_winners_{ts}.csv"
    oos_csv = out_dir / f"walk_forward_oos_panel_{ts}.csv"
    stability_csv = out_dir / f"walk_forward_stability_{ts}.csv"
    report_md = out_dir / f"walk_forward_report_{ts}.md"

    winners_df.to_csv(winners_csv, index=False, encoding="utf-8-sig")
    oos_df.to_csv(oos_csv, index=False, encoding="utf-8-sig")
    grp.to_csv(stability_csv, index=False, encoding="utf-8-sig")

    with open(report_md, "w", encoding="utf-8") as f:
        f.write("# Generic Walk-Forward Stability Report\n\n")
        f.write(f"- raw_csv: {raw_path.as_posix()}\n")
        f.write(f"- years: {years}\n")
        f.write(f"- folds: {len(folds)}\n")
        f.write(f"- group_cols: {args.group_cols}\n")
        f.write(f"- selection_model: {args.selection_model}\n")
        f.write("\n")
        f.write("## Train Selection Formula\n\n")
        if args.selection_model == "risk60_profit40_v2":
            f.write(
                "train_score = 0.35*mdd_inverse_norm + 0.25*worst_year_return_norm + 0.25*avg_alpha_norm + 0.15*positive_alpha_ratio_norm\n\n"
            )
        else:
            f.write(
                "train_score = 0.6*ret_rank + 0.4*(0.5*sharpe_rank + 0.5*mdd_quality_rank)\n\n"
            )
        f.write("## OOS Utility Formula\n\n")
        if args.selection_model == "risk60_profit40_v2":
            f.write(
                "oos_utility = 0.35*mdd_inverse_norm_test + 0.25*worst_year_return_norm_test + 0.25*avg_alpha_norm_test + 0.15*positive_alpha_ratio_norm_test\n\n"
            )
        else:
            f.write(
                "oos_utility = 0.6*ret_rank_test + 0.4*(0.5*sharpe_rank_test + 0.5*mdd_quality_rank_test)\n\n"
            )
        f.write("## Stability Formula\n\n")
        f.write(
            "stability_score = 100 * ((1-w)*[mean(oos_utility) - lambda*std(oos_utility)] + w*positive_alpha_rate)\n\n"
        )
        f.write(f"- lambda (std penalty): {args.std_penalty}\n")
        f.write(f"- w (positive alpha weight): {args.oos_positive_weight}\n\n")

        f.write("## Fold Winners (train winner -> next-year test)\n\n")
        if winners_df.empty:
            f.write("No winners generated.\n\n")
        else:
            f.write("| test_year | train_years | winner_label | test_oos_rank | test_oos_utility | test_return | test_alpha |\n")
            f.write("|---|---|---|---:|---:|---:|---:|\n")
            for _, r in winners_df.iterrows():
                f.write(
                    f"| {int(r['test_year'])} | {r['train_years']} | {r['winner_label']} | "
                    f"{int(r['test_oos_rank'])} | {r['test_oos_utility']:.4f} | {r['test_return']:.2f}% | {r['test_alpha']:.2f}% |\n"
                )
            f.write("\n")

        f.write("## Top 20 by Stability Score\n\n")
        top = grp.head(20)
        f.write("| rank | strategy | stability_score | oos_utility_mean | oos_utility_std | oos_positive_alpha_rate | oos_return_mean | oos_mdd_worst |\n")
        f.write("|---:|---|---:|---:|---:|---:|---:|---:|\n")
        for i, (_, r) in enumerate(top.iterrows(), 1):
            f.write(
                f"| {i} | {r['strategy_label']} | {r['stability_score']:.2f} | {r['oos_utility_mean']:.4f} | "
                f"{r['oos_utility_std']:.4f} | {r['oos_positive_alpha_rate']:.2f} | {r['oos_return_mean']:.2f}% | {r['oos_mdd_worst']:.2f}% |\n"
            )

    print(f"winners_csv={winners_csv.as_posix()}")
    print(f"oos_csv={oos_csv.as_posix()}")
    print(f"stability_csv={stability_csv.as_posix()}")
    print(f"report_md={report_md.as_posix()}")


if __name__ == "__main__":
    main()
