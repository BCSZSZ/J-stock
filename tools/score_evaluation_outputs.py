"""Re-score completed evaluation output directories with a global MDD-Win score."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.scoring import (
    MDD_WIN_V1_COMPONENTS,
    apply_weighted_score,
    candidate_key_columns,
    period_sort_values,
)


DISPLAY_PARAM_COLS = [
    "atr_risk_per_trade_pct",
    "atr_stop_multiple",
    "position_sizing_mode",
    "max_positions",
    "max_position_pct",
    "buy_fill_mode",
    "entry_reference_mode",
    "exit_confirmation_days",
    "ranking_strategy",
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_raw_csv(output_dir: Path) -> Path:
    raw_files = sorted(output_dir.glob("*_raw_*.csv"))
    preferred = [
        path
        for path in raw_files
        if "continuous_raw" not in path.name and "_oos_raw_" not in path.name
    ]
    candidates = preferred or raw_files
    if not candidates:
        raise FileNotFoundError(f"No *_raw_*.csv found under {output_dir}")
    return candidates[0]


def _load_summary_outputs(summary_json: Path) -> list[dict[str, str]]:
    payload = _read_json(summary_json)
    outputs: list[dict[str, str]] = []
    for worker in payload.get("workers", []):
        output_dir = worker.get("output_dir")
        if not output_dir:
            continue
        outputs.append(
            {
                "candidate_id": str(worker.get("worker_id") or worker.get("job_name") or ""),
                "job_name": str(worker.get("job_name") or ""),
                "output_dir": str(output_dir),
            }
        )
    return outputs


def discover_outputs(
    *,
    summary_json: Path | None,
    output_dirs: Iterable[Path],
    output_root: Path | None,
    recursive: bool,
) -> list[dict[str, str]]:
    discovered: list[dict[str, str]] = []
    if summary_json is not None:
        discovered.extend(_load_summary_outputs(summary_json))

    for output_dir in output_dirs:
        discovered.append(
            {
                "candidate_id": output_dir.name,
                "job_name": "",
                "output_dir": str(output_dir),
            }
        )

    if output_root is not None:
        raw_paths = (
            output_root.rglob("*_raw_*.csv") if recursive else output_root.glob("*/*_raw_*.csv")
        )
        for raw_path in raw_paths:
            output_dir = raw_path.parent
            discovered.append(
                {
                    "candidate_id": output_dir.name,
                    "job_name": "",
                    "output_dir": str(output_dir),
                }
            )

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in discovered:
        output_dir = str(Path(item["output_dir"]))
        if output_dir in seen:
            continue
        seen.add(output_dir)
        candidate_id = item["candidate_id"] or Path(output_dir).name
        deduped.append({**item, "candidate_id": candidate_id, "output_dir": output_dir})
    return deduped


def load_raw_panel(outputs: list[dict[str, str]]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for item in outputs:
        output_dir = Path(item["output_dir"])
        try:
            raw_path = _find_raw_csv(output_dir)
            frame = pd.read_csv(raw_path)
        except Exception as exc:
            errors.append(f"{output_dir}: {exc}")
            continue
        frame["source_candidate_id"] = item["candidate_id"]
        frame["source_job_name"] = item.get("job_name", "")
        frame["source_output_dir"] = str(output_dir)
        frame["source_raw_csv"] = str(raw_path)
        frames.append(frame)

    if not frames:
        detail = "\n".join(errors) if errors else "No output directories supplied."
        raise RuntimeError(f"No raw evaluation CSVs could be loaded.\n{detail}")
    return pd.concat(frames, ignore_index=True)


def _first_non_null(series: pd.Series) -> Any:
    non_null = series.dropna()
    if non_null.empty:
        return None
    return non_null.iloc[0]


def summarize_candidates(raw_df: pd.DataFrame, recent_period: str | None = None) -> pd.DataFrame:
    required = {
        "source_candidate_id",
        "source_output_dir",
        "source_raw_csv",
        "period",
        "entry_strategy",
        "exit_strategy",
        "entry_filter",
        "return_pct",
        "max_drawdown_pct",
    }
    missing = required - set(raw_df.columns)
    if missing:
        raise ValueError(f"Missing required raw columns: {', '.join(sorted(missing))}")

    working = raw_df.copy()
    for optional_col in ["win_rate_pct", "sharpe_ratio", "num_trades"]:
        if optional_col not in working.columns:
            working[optional_col] = pd.NA
    for numeric_col in [
        "return_pct",
        "max_drawdown_pct",
        "win_rate_pct",
        "sharpe_ratio",
        "num_trades",
    ]:
        working[numeric_col] = pd.to_numeric(working[numeric_col], errors="coerce")

    key_cols = [
        "source_candidate_id",
        "source_output_dir",
        "source_raw_csv",
    ] + candidate_key_columns(working)
    display_cols = [
        col for col in DISPLAY_PARAM_COLS if col in working.columns and col not in key_cols
    ]

    grouped = (
        working.groupby(key_cols, dropna=False)
        .agg(
            periods=("period", "nunique"),
            period_labels=("period", lambda s: ",".join(map(str, sorted(set(s.astype(str)))))),
            mean_return=("return_pct", "mean"),
            avg_mdd=("max_drawdown_pct", "mean"),
            worst_mdd=("max_drawdown_pct", "max"),
            mean_win_rate=("win_rate_pct", "mean"),
            mean_sharpe=("sharpe_ratio", "mean"),
            total_trades=("num_trades", "sum"),
            source_job_name=("source_job_name", _first_non_null),
            **{col: (col, _first_non_null) for col in display_cols},
        )
        .reset_index()
    )

    if recent_period is None:
        recent_source = (
            working.assign(_period_sort_key=period_sort_values(working["period"]))
            .sort_values(key_cols + ["_period_sort_key", "period"], kind="mergesort")
            .groupby(key_cols, dropna=False)
            .tail(1)
        )
    else:
        recent_source = working[working["period"].astype(str) == str(recent_period)]

    recent_rows = (
        recent_source.groupby(key_cols, dropna=False)
        .agg(
            recent_period=("period", _first_non_null),
            recent_return=("return_pct", "mean"),
            recent_win_rate=("win_rate_pct", "mean"),
            recent_mdd=("max_drawdown_pct", "mean"),
        )
        .reset_index()
    )
    return grouped.merge(recent_rows, on=key_cols, how="left")


def score_candidates(summary_df: pd.DataFrame) -> pd.DataFrame:
    scored = apply_weighted_score(
        summary_df,
        MDD_WIN_V1_COMPONENTS,
        score_col="mdd_win_score",
    )
    scored = scored.sort_values(
        ["mdd_win_score", "mean_return", "mean_win_rate"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    scored.insert(0, "rank", range(1, len(scored) + 1))
    return scored


def _fmt_pct(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "N/A"
    return f"{float(numeric):.2f}%"


def _fmt_ratio_pct(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "N/A"
    return f"{float(numeric) * 100.0:.2f}%"


def _fmt_num(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "N/A"
    return f"{float(numeric):.2f}"


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def write_markdown_report(scored: pd.DataFrame, path: Path, *, top_n: int) -> None:
    top = scored.head(top_n)
    headers = [
        "rank",
        "score",
        "candidate",
        "entry",
        "exit",
        "risk",
        "atr",
        "avg_return",
        "recent_return",
        "avg_win",
        "avg_mdd",
        "worst_mdd",
        "sharpe",
    ]
    rows: list[list[Any]] = []
    for _, row in top.iterrows():
        rows.append(
            [
                int(row["rank"]),
                _fmt_num(row["mdd_win_score"]),
                row["source_candidate_id"],
                row["entry_strategy"],
                row["exit_strategy"],
                _fmt_ratio_pct(row.get("atr_risk_per_trade_pct")),
                _fmt_num(row.get("atr_stop_multiple")),
                _fmt_pct(row["mean_return"]),
                _fmt_pct(row["recent_return"]),
                _fmt_pct(row["mean_win_rate"]),
                _fmt_pct(row["avg_mdd"]),
                _fmt_pct(row["worst_mdd"]),
                _fmt_num(row["mean_sharpe"]),
            ]
        )

    formula = (
        "0.25*mean_return + 0.15*recent_return + 0.25*avg_mdd_inverse "
        "+ 0.10*worst_mdd_inverse + 0.20*mean_win_rate + 0.05*mean_sharpe"
    )
    lines = [
        "# Evaluation Global MDD-Win Score",
        "",
        f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"- Candidates: {len(scored)}",
        f"- Formula: `{formula}`",
        "- Normalization: robust 10%-90% winsorized normalization across this merged candidate pool.",
        "",
        "## Top Candidates",
        "",
        _markdown_table(headers, rows),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Globally re-score completed evaluation output directories."
    )
    parser.add_argument("--summary-json", type=Path, help="Batch runner summary.json.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        action="append",
        default=[],
        help="Evaluation output directory. Repeatable.",
    )
    parser.add_argument("--output-root", type=Path, help="Root containing output dirs.")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively discover raw CSVs under --output-root.",
    )
    parser.add_argument(
        "--recent-period",
        help="Use this period as the recent-return column instead of each candidate's latest period.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("tmp") / "evaluation_global_scores",
        help="Directory for score CSV/Markdown outputs.",
    )
    parser.add_argument(
        "--output-prefix",
        default="evaluation_global_score",
        help="Output filename prefix.",
    )
    parser.add_argument("--top-n", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs = discover_outputs(
        summary_json=args.summary_json,
        output_dirs=args.output_dir,
        output_root=args.output_root,
        recursive=args.recursive,
    )
    if not outputs:
        raise SystemExit("No outputs supplied. Use --summary-json, --output-dir, or --output-root.")

    raw_df = load_raw_panel(outputs)
    summary_df = summarize_candidates(raw_df, recent_period=args.recent_period)
    scored = score_candidates(summary_df)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = args.out_dir / f"{args.output_prefix}_{timestamp}.csv"
    md_path = args.out_dir / f"{args.output_prefix}_{timestamp}.md"
    scored.to_csv(csv_path, index=False, encoding="utf-8-sig")
    write_markdown_report(scored, md_path, top_n=args.top_n)

    print(f"scored_csv={csv_path}")
    print(f"report_md={md_path}")
    display_cols = [
        "rank",
        "mdd_win_score",
        "source_candidate_id",
        "mean_return",
        "recent_return",
        "mean_win_rate",
        "avg_mdd",
        "worst_mdd",
    ]
    print(scored[display_cols].head(args.top_n).to_string(index=False))


if __name__ == "__main__":
    main()
