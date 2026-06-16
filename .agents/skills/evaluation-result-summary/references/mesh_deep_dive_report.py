from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Iterable


MOMENTUM_THRESHOLD_FLAGS = (
    "--momentum-exhaustion-max-score",
    "--momentum-exhaustion-count-threshold",
    "--momentum-exhaustion-threshold",
)


@dataclass(frozen=True)
class AxisSpec:
    key: str
    label: str
    direction: str
    formatter: Callable[[Any], str]


AXES = (
    AxisSpec("momentum", "Momentum threshold", "momentum", str),
    AxisSpec("daily", "Daily buy cap", "desc", lambda value: str(int(value))),
    AxisSpec("total", "Total position cap", "desc", lambda value: str(int(value))),
    AxisSpec("atr", "ATR stop multiple", "asc", lambda value: f"{float(value):.2f}"),
    AxisSpec("risk", "Risk per trade", "desc", lambda value: f"{float(value) * 100:.2f}%"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a mesh deep-dive markdown report from completed J-stock evaluation outputs.",
    )
    parser.add_argument("--output-root", required=True, help="Directory containing completed evaluation output dirs.")
    parser.add_argument("--source-summary", help="Existing summary markdown used as context/provenance.")
    parser.add_argument("--output", required=True, help="Markdown report path to create or overwrite.")
    parser.add_argument("--title", default="Mesh 深挖报告", help="Markdown H1 title.")
    parser.add_argument("--expected-count", type=int, help="Expected output directory count.")
    parser.add_argument(
        "--previous-champion-mean-return",
        type=float,
        help="Optional prior report champion mean_return for a one-line comparison.",
    )
    parser.add_argument(
        "--previous-label",
        default="上一轮",
        help="Label used with --previous-champion-mean-return.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return data


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def first_file(directory: Path, pattern: str) -> Path | None:
    files = sorted(directory.glob(pattern))
    return files[0] if files else None


def flag_value(args: list[Any], flag: str) -> str | None:
    for idx, item in enumerate(args):
        if str(item) == flag and idx + 1 < len(args):
            return str(args[idx + 1])
    return None


def first_flag_value(args: list[Any], flags: Iterable[str]) -> str | None:
    for flag in flags:
        value = flag_value(args, flag)
        if value not in (None, ""):
            return value
    return None


def to_float(value: Any, default: float = math.nan) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def decode_p_number(token: str) -> float:
    return float(token.replace("p", "."))


def safe_mean(values: Iterable[float]) -> float:
    clean = [value for value in values if not math.isnan(value)]
    return mean(clean) if clean else math.nan


def safe_median(values: Iterable[float]) -> float:
    clean = [value for value in values if not math.isnan(value)]
    return median(clean) if clean else math.nan


def fmt_num(value: Any, digits: int = 2) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return ""
    return f"{number:.{digits}f}"


def fmt_pct(value: Any, digits: int = 2) -> str:
    return fmt_num(value, digits)


def fmt_risk(value: Any) -> str:
    return "" if value is None else f"{float(value) * 100:.2f}%"


def fmt_atr(value: Any) -> str:
    return "" if value is None else f"{float(value):.2f}"


def md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(md_escape(cell) for cell in row) + " |")
    return "\n".join(lines)


def sorted_counter_text(values: Iterable[Any], formatter: Callable[[Any], str] = str) -> str:
    counter = Counter(values)
    parts = []
    for value, count in counter.most_common():
        parts.append(f"{formatter(value)}: {count}")
    return ", ".join(parts)


def axis_counter_text(combos: list[dict[str, Any]], spec: AxisSpec) -> str:
    counter = Counter(combo[spec.key] for combo in combos)
    parts = []
    for value in axis_value_order(counter.keys(), spec):
        parts.append(f"{spec.formatter(value)}: {counter[value]}")
    return ", ".join(parts)


def combo_counter_text(counter: Counter[tuple[Any, ...]]) -> str:
    return ", ".join(f"{item}: {count}" for item, count in counter.most_common())


def axis_value_order(values: Iterable[Any], spec: AxisSpec) -> list[Any]:
    unique = list(dict.fromkeys(values))
    if spec.direction == "momentum":
        off_values = [value for value in unique if str(value) == "off"]
        numeric_values = [value for value in unique if str(value) != "off"]
        numeric_values.sort(key=lambda value: to_float(value), reverse=True)
        return off_values + numeric_values
    if spec.direction == "asc":
        return sorted(unique, key=lambda value: to_float(value))
    if spec.direction == "desc":
        return sorted(unique, key=lambda value: to_float(value), reverse=True)
    return sorted(unique, key=str)


def extract_worker_from_path(path: Path) -> str:
    match = re.search(r"_(w\d+)$", path.name)
    return match.group(1) if match else path.name


def extract_params(output_dir: Path, job: dict[str, Any] | None, raw_rows: list[dict[str, str]]) -> dict[str, Any]:
    job = job or {}
    base_args = job.get("base_args") if isinstance(job.get("base_args"), list) else []
    first_raw = raw_rows[0] if raw_rows else {}
    worker = str(job.get("worker_id") or extract_worker_from_path(output_dir))
    job_name = str(job.get("job_name") or "")
    searchable = " ".join([worker, job_name, output_dir.name, str(job.get("notes") or "")])

    momentum_mode = flag_value(base_args, "--momentum-exhaustion-mode")
    momentum_threshold = first_flag_value(base_args, MOMENTUM_THRESHOLD_FLAGS)
    if momentum_mode == "off":
        momentum: str = "off"
    elif momentum_threshold:
        momentum = str(to_int(momentum_threshold, momentum_threshold))  # type: ignore[arg-type]
    else:
        momentum_match = re.search(r"(?:me|mom_enf_s)(\d+)", searchable)
        momentum = momentum_match.group(1) if momentum_match else str(momentum_mode or "")

    daily = to_int(flag_value(base_args, "--max-buy-per-industry-per-day"))
    if daily is None:
        daily_match = re.search(r"(?:daily|_d)(\d+)", searchable)
        daily = int(daily_match.group(1)) if daily_match else None

    total = to_int(flag_value(base_args, "--max-total-positions-per-industry"))
    if total is None:
        total_match = re.search(r"(?:total|_t)(\d+)", searchable)
        total = int(total_match.group(1)) if total_match else None

    atr = to_float(flag_value(base_args, "--atr-stop-multiple"), math.nan)
    if math.isnan(atr):
        atr = to_float(first_raw.get("atr_stop_multiple"), math.nan)
    if math.isnan(atr):
        atr_match = re.search(r"atr([0-9]+p[0-9]+|[0-9]+)", searchable)
        if atr_match:
            atr = decode_p_number(atr_match.group(1))

    risk = to_float(flag_value(base_args, "--risk-per-trade-pct"), math.nan)
    if math.isnan(risk):
        risk = to_float(first_raw.get("atr_risk_per_trade_pct"), math.nan)
    if math.isnan(risk):
        risk_match = re.search(r"risk([0-9]+p[0-9]+)", searchable)
        if risk_match:
            risk = decode_p_number(risk_match.group(1))

    return {
        "worker": worker,
        "job_name": job_name,
        "momentum": momentum,
        "daily": daily,
        "total": total,
        "atr": atr,
        "risk": risk,
    }


def period_metric(period_rows: dict[int, dict[str, float]], period: int, key: str) -> float:
    row = period_rows.get(period)
    return math.nan if row is None else row.get(key, math.nan)


def build_combo(output_dir: Path) -> dict[str, Any] | None:
    raw_path = first_file(output_dir, "*_raw_*.csv")
    rank_path = first_file(output_dir, "*_prs_train_rank_*.csv")
    if raw_path is None or rank_path is None:
        return None

    job_path = first_file(output_dir, "evaluation_batch_job_*.json")
    job = read_json(job_path) if job_path else None
    raw_rows = read_csv_rows(raw_path)
    rank_rows = read_csv_rows(rank_path)
    params = extract_params(output_dir, job, raw_rows)

    period_rows: dict[int, dict[str, float]] = {}
    for row in raw_rows:
        period = to_int(row.get("period"))
        if period is None:
            continue
        period_rows[period] = {
            "return_pct": to_float(row.get("return_pct")),
            "alpha": to_float(row.get("alpha")),
            "sharpe_ratio": to_float(row.get("sharpe_ratio")),
            "max_drawdown_pct": to_float(row.get("max_drawdown_pct")),
            "num_trades": to_float(row.get("num_trades")),
            "win_rate_pct": to_float(row.get("win_rate_pct")),
        }

    returns = [row["return_pct"] for row in period_rows.values()]
    alphas = [row["alpha"] for row in period_rows.values()]
    sharpes = [row["sharpe_ratio"] for row in period_rows.values()]
    drawdowns = [row["max_drawdown_pct"] for row in period_rows.values()]
    trades = [row["num_trades"] for row in period_rows.values()]
    win_rates = [row["win_rate_pct"] for row in period_rows.values()]
    train_score = to_float(rank_rows[0].get("prs_train_score")) if rank_rows else math.nan

    combo = {
        **params,
        "output_dir": str(output_dir),
        "periods": sorted(period_rows),
        "period_rows": period_rows,
        "mean_ret": safe_mean(returns),
        "median_ret": safe_median(returns),
        "mean_alpha": safe_mean(alphas),
        "avg_mdd": safe_mean(drawdowns),
        "worst_mdd": max(drawdowns) if drawdowns else math.nan,
        "avg_sharpe": safe_mean(sharpes),
        "avg_trades": safe_mean(trades),
        "total_trades": sum(value for value in trades if not math.isnan(value)),
        "avg_win": safe_mean(win_rates),
        "train_score": train_score,
        "raw_path": str(raw_path),
        "rank_path": str(rank_path),
    }
    for period in sorted(period_rows):
        combo[f"ret_{period}"] = period_metric(period_rows, period, "return_pct")
        combo[f"alpha_{period}"] = period_metric(period_rows, period, "alpha")
        combo[f"mdd_{period}"] = period_metric(period_rows, period, "max_drawdown_pct")
        combo[f"sharpe_{period}"] = period_metric(period_rows, period, "sharpe_ratio")
        combo[f"win_{period}"] = period_metric(period_rows, period, "win_rate_pct")
    combo["ret_25_26"] = safe_mean([combo.get("ret_2025", math.nan), combo.get("ret_2026", math.nan)])
    combo["win_25_26"] = safe_mean([combo.get("win_2025", math.nan), combo.get("win_2026", math.nan)])
    combo["mdd_25_26"] = safe_mean([combo.get("mdd_2025", math.nan), combo.get("mdd_2026", math.nan)])
    return combo


def load_combos(output_root: Path) -> list[dict[str, Any]]:
    combos: list[dict[str, Any]] = []
    for output_dir in sorted(path for path in output_root.iterdir() if path.is_dir()):
        combo = build_combo(output_dir)
        if combo is not None:
            combos.append(combo)
    if not combos:
        raise RuntimeError(f"No evaluation outputs with raw/rank CSVs found under {output_root}")
    return combos


def aggregate(combos: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for combo in combos:
        groups[tuple(combo[key] for key in keys)].append(combo)

    rows: list[dict[str, Any]] = []
    for key_values, items in groups.items():
        best = sorted(items, key=lambda item: item["mean_ret"], reverse=True)[0]
        row = {key: value for key, value in zip(keys, key_values)}
        row.update(
            {
                "n": len(items),
                "mean_ret": safe_mean(item["mean_ret"] for item in items),
                "median_ret": safe_median(item["mean_ret"] for item in items),
                "ret_2026": safe_mean(item.get("ret_2026", math.nan) for item in items),
                "ret_25_26": safe_mean(item.get("ret_25_26", math.nan) for item in items),
                "avg_win": safe_mean(item["avg_win"] for item in items),
                "win_2026": safe_mean(item.get("win_2026", math.nan) for item in items),
                "avg_mdd": safe_mean(item["avg_mdd"] for item in items),
                "avg_sharpe": safe_mean(item["avg_sharpe"] for item in items),
                "best_worker": best["worker"],
                "best_ret": best["mean_ret"],
            }
        )
        rows.append(row)
    return rows


def rank_within_slices(combos: list[dict[str, Any]], axis: AxisSpec) -> tuple[dict[Any, float], dict[Any, float]]:
    other_keys = [spec.key for spec in AXES if spec.key != axis.key]
    slice_wins: dict[Any, float] = defaultdict(float)
    rank_sum: dict[Any, float] = defaultdict(float)
    rank_count: dict[Any, int] = defaultdict(int)
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for combo in combos:
        groups[tuple(combo[key] for key in other_keys)].append(combo)

    for items in groups.values():
        ordered = sorted(items, key=lambda item: item["mean_ret"], reverse=True)
        if not ordered:
            continue
        best_value = ordered[0]["mean_ret"]
        winners = [item for item in ordered if abs(item["mean_ret"] - best_value) < 1e-9]
        winner_credit = 1.0 / len(winners)
        for winner in winners:
            slice_wins[winner[axis.key]] += winner_credit
        for rank, item in enumerate(ordered, start=1):
            rank_sum[item[axis.key]] += rank
            rank_count[item[axis.key]] += 1

    avg_rank = {
        level: rank_sum[level] / rank_count[level]
        for level in rank_count
        if rank_count[level]
    }
    return dict(slice_wins), avg_rank


def axis_summary(combos: list[dict[str, Any]], axis: AxisSpec) -> list[dict[str, Any]]:
    top25 = {combo["worker"] for combo in sorted(combos, key=lambda item: item["mean_ret"], reverse=True)[:25]}
    top50 = {combo["worker"] for combo in sorted(combos, key=lambda item: item["mean_ret"], reverse=True)[:50]}
    rows = aggregate(combos, [axis.key])
    wins, avg_rank = rank_within_slices(combos, axis)
    for row in rows:
        level = row[axis.key]
        row["slice_wins"] = wins.get(level, 0.0)
        row["avg_rank"] = avg_rank.get(level, math.nan)
        level_items = [combo for combo in combos if combo[axis.key] == level]
        row["top25"] = sum(1 for combo in level_items if combo["worker"] in top25)
        row["top50"] = sum(1 for combo in level_items if combo["worker"] in top50)
    rows.sort(key=lambda row: row["mean_ret"], reverse=True)
    return rows


def paired_deltas(combos: list[dict[str, Any]], axis: AxisSpec) -> list[dict[str, Any]]:
    levels = axis_value_order((combo[axis.key] for combo in combos), axis)
    if len(levels) < 2:
        return []
    other_keys = [spec.key for spec in AXES if spec.key != axis.key]
    by_key: dict[tuple[Any, ...], dict[Any, dict[str, Any]]] = defaultdict(dict)
    for combo in combos:
        key = tuple(combo[key] for key in other_keys)
        by_key[key][combo[axis.key]] = combo

    rows: list[dict[str, Any]] = []
    for left, right in zip(levels, levels[1:]):
        ret_deltas: list[float] = []
        ret_2026_deltas: list[float] = []
        for level_map in by_key.values():
            if left not in level_map or right not in level_map:
                continue
            left_combo = level_map[left]
            right_combo = level_map[right]
            ret_deltas.append(left_combo["mean_ret"] - right_combo["mean_ret"])
            ret_2026_deltas.append(
                left_combo.get("ret_2026", math.nan) - right_combo.get("ret_2026", math.nan)
            )
        rows.append(
            {
                "pair": f"{axis.formatter(left)} - {axis.formatter(right)}",
                "n": len(ret_deltas),
                "delta_mean_ret": safe_mean(ret_deltas),
                "positive_mean_ret": sum(1 for value in ret_deltas if value > 0),
                "delta_2026": safe_mean(ret_2026_deltas),
                "positive_2026": sum(1 for value in ret_2026_deltas if value > 0),
            }
        )
    return rows


def top_rows(combos: list[dict[str, Any]], metric: str, limit: int) -> list[dict[str, Any]]:
    return sorted(combos, key=lambda item: item.get(metric, math.nan), reverse=True)[:limit]


def combo_table_rows(combos: list[dict[str, Any]], include_2526: bool = True) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for idx, combo in enumerate(combos, start=1):
        row = [
            idx,
            combo["worker"],
            combo["momentum"],
            combo["daily"],
            combo["total"],
            fmt_atr(combo["atr"]),
            fmt_risk(combo["risk"]),
            fmt_num(combo["mean_ret"]),
            fmt_num(combo.get("ret_2026")),
        ]
        if include_2526:
            row.append(fmt_num(combo.get("ret_25_26")))
        row.extend(
            [
                fmt_pct(combo.get("avg_win")),
                fmt_pct(combo.get("win_2026")),
                fmt_num(combo["avg_mdd"]),
                fmt_num(combo["worst_mdd"]),
                fmt_num(combo["avg_sharpe"]),
            ]
        )
        rows.append(row)
    return rows


def axis_table(axis: AxisSpec, rows: list[dict[str, Any]]) -> str:
    return markdown_table(
        [
            "level",
            "n",
            "mean_ret",
            "median_ret",
            "ret_2026",
            "ret_25_26",
            "avg_win",
            "win_2026",
            "avg_mdd",
            "avg_sharpe",
            "slice_wins",
            "avg_rank",
            "top25",
            "top50",
            "best_worker",
            "best_ret",
        ],
        [
            [
                axis.formatter(row[axis.key]),
                row["n"],
                fmt_num(row["mean_ret"]),
                fmt_num(row["median_ret"]),
                fmt_num(row["ret_2026"]),
                fmt_num(row["ret_25_26"]),
                fmt_pct(row["avg_win"]),
                fmt_pct(row["win_2026"]),
                fmt_num(row["avg_mdd"]),
                fmt_num(row["avg_sharpe"]),
                fmt_num(row["slice_wins"], 1),
                fmt_num(row["avg_rank"], 2),
                row["top25"],
                row["top50"],
                row["best_worker"],
                fmt_num(row["best_ret"]),
            ]
            for row in rows
        ],
    )


def paired_delta_table(axis: AxisSpec, combos: list[dict[str, Any]]) -> str:
    deltas = paired_deltas(combos, axis)
    if not deltas:
        return ""
    return markdown_table(
        [
            "pair",
            "matched_slices",
            "delta_mean_ret",
            "positive_mean_ret",
            "delta_2026",
            "positive_2026",
        ],
        [
            [
                row["pair"],
                row["n"],
                fmt_num(row["delta_mean_ret"]),
                f"{row['positive_mean_ret']}/{row['n']}",
                fmt_num(row["delta_2026"]),
                f"{row['positive_2026']}/{row['n']}",
            ]
            for row in deltas
        ],
    )


def plateau_rows(combos: list[dict[str, Any]]) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    top_ret = max(combo["mean_ret"] for combo in combos)
    table_rows: list[list[Any]] = []
    within_95: list[dict[str, Any]] = []
    for ratio in (0.98, 0.95, 0.90, 0.85, 0.80):
        cutoff = top_ret * ratio
        selected = [combo for combo in combos if combo["mean_ret"] >= cutoff]
        if ratio == 0.95:
            within_95 = sorted(selected, key=lambda item: item["mean_ret"], reverse=True)
        table_rows.append(
            [
                f">= {ratio:.0%} of top",
                len(selected),
                fmt_num(cutoff),
                fmt_pct(safe_mean(combo["avg_win"] for combo in selected)),
                sorted_counter_text((combo["momentum"] for combo in selected), str),
                combo_counter_text(Counter((combo["daily"], combo["total"]) for combo in selected)),
                sorted_counter_text((combo["atr"] for combo in selected), fmt_atr),
                sorted_counter_text((combo["risk"] for combo in selected), fmt_risk),
            ]
        )
    return table_rows, within_95


def numeric_values(combos: list[dict[str, Any]], key: str) -> list[float]:
    values = sorted({float(combo[key]) for combo in combos if combo[key] is not None and not math.isnan(float(combo[key]))})
    return values


def next_numeric_values(values: list[float], direction: str, count: int = 5) -> list[float]:
    if len(values) < 2:
        return values
    step = min(abs(b - a) for a, b in zip(values, values[1:]) if abs(b - a) > 1e-12)
    if direction == "lower":
        start = values[0] - step * 3
        proposed = [start + step * idx for idx in range(count)]
    else:
        start = values[-1] - step
        proposed = [start + step * idx for idx in range(count)]
    return [round(value, 6) for value in proposed if value > 0]


def recommendation_lines(combos: list[dict[str, Any]], axis_rows: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    atr_best = axis_rows["atr"][0]["atr"]
    risk_best = axis_rows["risk"][0]["risk"]
    atr_values = numeric_values(combos, "atr")
    risk_values = numeric_values(combos, "risk")
    boundary_notes = []
    if math.isclose(float(atr_best), min(atr_values)):
        boundary_notes.append(f"`ATR={fmt_atr(atr_best)}` 仍在最低边界")
    if math.isclose(float(risk_best), max(risk_values)):
        boundary_notes.append(f"`risk={fmt_risk(risk_best)}` 仍在最高边界")
    if boundary_notes:
        lines.append("- 主方向：继续做边界确认，" + "，".join(boundary_notes) + "，尚未证明已经到顶。")

    momentum_keep = [row["momentum"] for row in axis_rows["momentum"][:3]]
    weak_momentum = axis_rows["momentum"][-1]["momentum"]
    lines.append(
        "- `momentum`：优先保留 "
        + ", ".join(f"`{value}`" for value in momentum_keep)
        + f"；`{weak_momentum}` 本轮边际较弱，可删除或降权。"
    )

    daily_keep = [row["daily"] for row in axis_rows["daily"][:2]]
    total_keep = [row["total"] for row in axis_rows["total"][:3]]
    total_values = numeric_values(combos, "total")
    total_probe = int(max(total_values) + 1) if total_values else None
    lines.append(
        "- `daily_cap`：保留 "
        + ", ".join(f"`{int(value)}`" for value in daily_keep)
        + "，其中第一位作为主扫，另一位保留作稳健性对照。"
    )
    total_text = ", ".join(f"`{int(value)}`" for value in total_keep)
    if total_probe is not None:
        total_text += f"，并加 `{total_probe}` 判断容量上边界"
    lines.append(f"- `total_cap`：保留 {total_text}。")

    proposed_atr = next_numeric_values(atr_values, "lower")
    proposed_risk = next_numeric_values(risk_values, "higher")
    lines.append(
        "- 建议下一轮主 mesh："
        + f"`momentum = {', '.join(str(value) for value in momentum_keep)}`; "
        + f"`daily = {', '.join(str(int(value)) for value in daily_keep)}`; "
        + f"`total = {', '.join(str(int(value)) for value in total_keep + ([total_probe] if total_probe else []))}`; "
        + f"`ATR = {', '.join(fmt_atr(value) for value in proposed_atr)}`; "
        + f"`risk = {', '.join(f'{value:.4f}' for value in proposed_risk)}`。"
    )
    lines.append("- 风险停止条件：若 `worst_mdd` 明显越过 18%-20%，或 2026 return/胜率同步回落，应停止继续增大 risk 或降低 ATR。")
    return lines


def render_report(
    combos: list[dict[str, Any]],
    output_root: Path,
    output_path: Path,
    title: str,
    source_summary: str | None,
    expected_count: int | None,
    previous_champion_mean_return: float | None,
    previous_label: str,
) -> str:
    now = datetime.now().replace(microsecond=0)
    sorted_overall = top_rows(combos, "mean_ret", len(combos))
    champion = sorted_overall[0]
    sorted_2026 = top_rows(combos, "ret_2026", len(combos))
    top_2026 = sorted_2026[0]
    sorted_2526 = top_rows(combos, "ret_25_26", len(combos))
    top_2526 = sorted_2526[0]
    axis_rows = {spec.key: axis_summary(combos, spec) for spec in AXES}
    risk_atr = sorted(aggregate(combos, ["risk", "atr"]), key=lambda row: row["mean_ret"], reverse=True)
    cap_pairs = sorted(aggregate(combos, ["daily", "total"]), key=lambda row: row["mean_ret"], reverse=True)
    plateau_table_rows, within_95 = plateau_rows(combos)

    lines: list[str] = []
    lines.extend(
        [
            "---",
            "summary_version: 1",
            f"generated_at: {now.isoformat()}",
            "mode: mesh-deep-dive",
            f'source_summary: "{source_summary or ""}"',
            f'source_output_root: "{output_root}"',
            f"source_output_count: {len(combos)}",
            "win_rate_source: win_rate_pct",
            "---",
            "",
            f"# {title}",
            "",
            "## Scope",
            "",
            f"- 输入：`{output_root}` 下 {len(combos)} 个 annual evaluate 输出。"
            + (f"已有 summary：`{Path(source_summary).name}`。" if source_summary else ""),
            "- 解析：每个输出读取 `evaluation_batch_job_*.json`, `*_raw_*.csv`, `*_prs_train_rank_*.csv`。",
            "- 主口径：2022-2026 年度 `return_pct` 简单平均；辅助看 2025/2026、2026 单年、alpha、最大回撤、Sharpe、交易数、胜率。",
            "- 胜率口径：直接使用 raw CSV 的 `win_rate_pct`；`avg_win` 是年度胜率简单平均，`win_2026` 是 2026 单年胜率。",
            "- 注意：当 `prs_train_score` 近似常量时，排序以 raw CSV 的收益/风险字段为主。",
        ]
    )
    if expected_count is not None and expected_count != len(combos):
        lines.append(f"- 警告：期望 {expected_count} 个输出，实际解析 {len(combos)} 个。")

    lines.extend(["", "## Parameter Grid Check", ""])
    grid_rows = []
    for spec in AXES:
        grid_rows.append([spec.label, axis_counter_text(combos, spec)])
    lines.append(markdown_table(["axis", "values / counts"], grid_rows))

    lines.extend(["", "## Executive Summary", ""])
    lines.append(
        "- 全体冠军："
        f"`{champion['worker']}`，mom={champion['momentum']}, daily={champion['daily']}, "
        f"total={champion['total']}, atr={fmt_atr(champion['atr'])}, risk={fmt_risk(champion['risk'])}，"
        f"mean_return={fmt_num(champion['mean_ret'])}%，2026_return={fmt_num(champion.get('ret_2026'))}%，"
        f"avg_win={fmt_pct(champion['avg_win'])}%，win_2026={fmt_pct(champion.get('win_2026'))}%，"
        f"avg_mdd={fmt_num(champion['avg_mdd'])}%，worst_mdd={fmt_num(champion['worst_mdd'])}%。"
    )
    lines.append(
        "- 2026 单年冠军："
        f"`{top_2026['worker']}`，mom={top_2026['momentum']}, daily={top_2026['daily']}, "
        f"total={top_2026['total']}, atr={fmt_atr(top_2026['atr'])}, risk={fmt_risk(top_2026['risk'])}，"
        f"2026_return={fmt_num(top_2026.get('ret_2026'))}%，win_2026={fmt_pct(top_2026.get('win_2026'))}%，"
        f"mean_return={fmt_num(top_2026['mean_ret'])}%。"
    )
    lines.append(
        "- 2025/2026 均值冠军："
        f"`{top_2526['worker']}`，ret_25_26={fmt_num(top_2526.get('ret_25_26'))}%，"
        f"win_25_26={fmt_pct(top_2526.get('win_25_26'))}%，mean_return={fmt_num(top_2526['mean_ret'])}%。"
    )
    if previous_champion_mean_return is not None:
        delta = champion["mean_ret"] - previous_champion_mean_return
        lines.append(
            f"- 相比 {previous_label} 冠军 mean_return={fmt_num(previous_champion_mean_return)}%，"
            f"本轮冠军为 {fmt_num(champion['mean_ret'])}%，差值 {fmt_num(delta)}%。"
        )
    for recommendation in recommendation_lines(combos, axis_rows)[:3]:
        lines.append(recommendation)

    lines.extend(["", "## Top 30 Overall", ""])
    lines.append(
        markdown_table(
            [
                "rank",
                "worker",
                "mom",
                "daily",
                "total",
                "atr",
                "risk",
                "mean_ret",
                "ret_2026",
                "ret_25_26",
                "avg_win",
                "win_2026",
                "avg_mdd",
                "worst_mdd",
                "avg_sharpe",
            ],
            combo_table_rows(sorted_overall[:30], include_2526=True),
        )
    )

    lines.extend(["", "## Top 15 by 2026 Return", ""])
    lines.append(
        markdown_table(
            [
                "rank",
                "worker",
                "mom",
                "daily",
                "total",
                "atr",
                "risk",
                "mean_ret",
                "ret_2026",
                "ret_25_26",
                "avg_win",
                "win_2026",
                "avg_mdd",
                "worst_mdd",
                "avg_sharpe",
            ],
            combo_table_rows(sorted_2026[:15], include_2526=True),
        )
    )

    lines.extend(["", "## 1. 单条件边际倾向", ""])
    lines.append("`slice_wins` 表示其他参数完全相同的切片内该 level 取得 mean_return 第一的次数；并列按比例分摊。`avg_rank` 越小越好。")
    for spec in AXES:
        lines.extend(["", f"### {spec.label}", "", axis_table(spec, axis_rows[spec.key])])
        delta_table = paired_delta_table(spec, combos)
        if delta_table:
            lines.extend(["", "Paired deltas:", "", delta_table])

    lines.extend(["", "## 2. 2026 / 2025+2026 Confirmation", ""])
    lines.append("### 2026-only Top 10")
    lines.append("")
    lines.append(
        markdown_table(
            [
                "rank",
                "worker",
                "mom",
                "daily",
                "total",
                "atr",
                "risk",
                "ret_2026",
                "win_2026",
                "mean_ret",
                "avg_win",
                "ret_2025",
                "mdd_2026",
                "sharpe_2026",
            ],
            [
                [
                    idx,
                    combo["worker"],
                    combo["momentum"],
                    combo["daily"],
                    combo["total"],
                    fmt_atr(combo["atr"]),
                    fmt_risk(combo["risk"]),
                    fmt_num(combo.get("ret_2026")),
                    fmt_pct(combo.get("win_2026")),
                    fmt_num(combo["mean_ret"]),
                    fmt_pct(combo["avg_win"]),
                    fmt_num(combo.get("ret_2025")),
                    fmt_num(combo.get("mdd_2026")),
                    fmt_num(combo.get("sharpe_2026")),
                ]
                for idx, combo in enumerate(sorted_2026[:10], start=1)
            ],
        )
    )
    lines.extend(["", "### 2025/2026 Mean Top 10", ""])
    lines.append(
        markdown_table(
            [
                "rank",
                "worker",
                "mom",
                "daily",
                "total",
                "atr",
                "risk",
                "ret_25_26",
                "win_25_26",
                "ret_2025",
                "ret_2026",
                "mean_ret",
                "avg_win",
                "mdd_25_26",
            ],
            [
                [
                    idx,
                    combo["worker"],
                    combo["momentum"],
                    combo["daily"],
                    combo["total"],
                    fmt_atr(combo["atr"]),
                    fmt_risk(combo["risk"]),
                    fmt_num(combo.get("ret_25_26")),
                    fmt_pct(combo.get("win_25_26")),
                    fmt_num(combo.get("ret_2025")),
                    fmt_num(combo.get("ret_2026")),
                    fmt_num(combo["mean_ret"]),
                    fmt_pct(combo["avg_win"]),
                    fmt_num(combo.get("mdd_25_26")),
                ]
                for idx, combo in enumerate(sorted_2526[:10], start=1)
            ],
        )
    )

    lines.extend(["", "## 3. Risk x ATR Surface", ""])
    lines.append(
        markdown_table(
            [
                "risk",
                "atr",
                "n",
                "mean_ret",
                "ret_2026",
                "ret_25_26",
                "avg_win",
                "win_2026",
                "avg_mdd",
                "best_worker",
                "best_ret",
            ],
            [
                [
                    fmt_risk(row["risk"]),
                    fmt_atr(row["atr"]),
                    row["n"],
                    fmt_num(row["mean_ret"]),
                    fmt_num(row["ret_2026"]),
                    fmt_num(row["ret_25_26"]),
                    fmt_pct(row["avg_win"]),
                    fmt_pct(row["win_2026"]),
                    fmt_num(row["avg_mdd"]),
                    row["best_worker"],
                    fmt_num(row["best_ret"]),
                ]
                for row in risk_atr
            ],
        )
    )

    lines.extend(["", "## 4. Daily x Total Cap Surface", ""])
    lines.append(
        markdown_table(
            [
                "daily",
                "total",
                "n",
                "mean_ret",
                "ret_2026",
                "ret_25_26",
                "avg_win",
                "win_2026",
                "avg_mdd",
                "best_worker",
                "best_ret",
            ],
            [
                [
                    row["daily"],
                    row["total"],
                    row["n"],
                    fmt_num(row["mean_ret"]),
                    fmt_num(row["ret_2026"]),
                    fmt_num(row["ret_25_26"]),
                    fmt_pct(row["avg_win"]),
                    fmt_pct(row["win_2026"]),
                    fmt_num(row["avg_mdd"]),
                    row["best_worker"],
                    fmt_num(row["best_ret"]),
                ]
                for row in cap_pairs
            ],
        )
    )

    lines.extend(["", "## 5. Plateau / 高台", ""])
    lines.append(
        markdown_table(
            ["band", "count", "cutoff", "avg_win", "momentum_mix", "cap_mix", "atr_mix", "risk_mix"],
            plateau_table_rows,
        )
    )
    lines.extend(["", "### Combos within 95% of Overall Top", ""])
    lines.append(
        markdown_table(
            [
                "rank",
                "worker",
                "mom",
                "daily",
                "total",
                "atr",
                "risk",
                "mean_ret",
                "ret_2026",
                "avg_win",
                "win_2026",
                "avg_mdd",
                "worst_mdd",
            ],
            [
                [
                    idx,
                    combo["worker"],
                    combo["momentum"],
                    combo["daily"],
                    combo["total"],
                    fmt_atr(combo["atr"]),
                    fmt_risk(combo["risk"]),
                    fmt_num(combo["mean_ret"]),
                    fmt_num(combo.get("ret_2026")),
                    fmt_pct(combo["avg_win"]),
                    fmt_pct(combo.get("win_2026")),
                    fmt_num(combo["avg_mdd"]),
                    fmt_num(combo["worst_mdd"]),
                ]
                for idx, combo in enumerate(within_95, start=1)
            ],
        )
    )

    lines.extend(["", "## Next Mesh Recommendation", ""])
    lines.extend(recommendation_lines(combos, axis_rows))

    lines.extend(["", "## Provenance", ""])
    if source_summary:
        lines.append(f"- Existing summary: `{source_summary}`")
    lines.append(f"- Raw outputs: `{output_root}`")
    lines.append(f"- Generated file: `{output_path}`")
    lines.append("- Script: `.agents/skills/evaluation-result-summary/references/mesh_deep_dive_report.py`")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root)
    output_path = Path(args.output)
    combos = load_combos(output_root)
    report = render_report(
        combos=combos,
        output_root=output_root,
        output_path=output_path,
        title=args.title,
        source_summary=args.source_summary,
        expected_count=args.expected_count,
        previous_champion_mean_return=args.previous_champion_mean_return,
        previous_label=args.previous_label,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8", newline="\n")
    champion = max(combos, key=lambda item: item["mean_ret"])
    top_2026 = max(combos, key=lambda item: item.get("ret_2026", math.nan))
    print(str(output_path))
    print(f"parsed {len(combos)}")
    print(
        "champion "
        f"{champion['worker']} mean_return={fmt_num(champion['mean_ret'])} "
        f"avg_win={fmt_pct(champion['avg_win'])} win_2026={fmt_pct(champion.get('win_2026'))}"
    )
    print(
        "top2026 "
        f"{top_2026['worker']} ret_2026={fmt_num(top_2026.get('ret_2026'))} "
        f"win_2026={fmt_pct(top_2026.get('win_2026'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
