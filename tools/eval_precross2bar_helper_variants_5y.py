"""Run a fixed-exit five-year comparison for PreCross2Bar helper variants."""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.portfolio_engine import PortfolioBacktestEngine
from src.evaluation.strategy_evaluator import StrategyEvaluator
from src.utils.strategy_loader import load_entry_strategy, load_exit_strategy

PERIOD_START = "2021-01-01"
PERIOD_END = "2025-12-31"
FIXED_EXIT_STRATEGY = "MVX_N3_R3p25_T1p6_D21_B20p0"
ENTRY_VARIANTS = [
    {
        "label": "Baseline",
        "strategy_name": "MACDCrossoverStrategy",
        "params": {},
        "rule_summary": "Original MACD golden-cross entry.",
    },
    {
        "label": "PreCross2Bar",
        "strategy_name": "MACDPreCrossMomentumEntry",
        "params": {
            "hist_rise_days": 2,
            "price_rise_days": 2,
        },
        "rule_summary": "Two-bar strict-rise pre-cross entry.",
    },
    {
        "label": "2BarHist0010",
        "strategy_name": "MACDPreCrossMomentumEntry",
        "params": {
            "hist_rise_days": 2,
            "price_rise_days": 2,
            "max_hist_abs_norm": 0.010,
        },
        "rule_summary": "PreCross2Bar plus abs(MACD_Hist) / Close <= 0.010.",
    },
    {
        "label": "2BarADX10",
        "strategy_name": "MACDPreCrossMomentumEntry",
        "params": {
            "hist_rise_days": 2,
            "price_rise_days": 2,
            "min_adx_14": 10.0,
        },
        "rule_summary": "PreCross2Bar plus ADX_14 >= 10.",
    },
    {
        "label": "2BarRet5d008",
        "strategy_name": "MACDPreCrossMomentumEntry",
        "params": {
            "hist_rise_days": 2,
            "price_rise_days": 2,
            "max_return_5d": 0.08,
        },
        "rule_summary": "PreCross2Bar plus Return_5d <= 0.08.",
    },
    {
        "label": "2BarLiteCombo",
        "strategy_name": "MACDPreCrossMomentumEntry",
        "params": {
            "hist_rise_days": 2,
            "price_rise_days": 2,
            "max_hist_abs_norm": 0.010,
            "min_adx_14": 10.0,
            "max_return_5d": 0.08,
        },
        "rule_summary": "PreCross2Bar plus hist_abs_norm <= 0.010, ADX_14 >= 10, Return_5d <= 0.08.",
    },
]


def _json_default(value):
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _classify_stage(trade_row):
    exit_urgency = str(trade_row.get("exit_urgency") or "")
    return_pct = float(trade_row.get("return_pct") or 0.0)
    is_r = exit_urgency.startswith("R")
    if is_r and return_pct > 0:
        return "good_r", "good_r"
    if is_r:
        return "bad_r", "bad_r"
    if return_pct > 0:
        return "non_r", "positive_non_r"
    return "non_r", "negative_non_r"


def _build_trade_rows(strategy_label, strategy_name, strategy_params, result):
    rows = []
    for trade in result.trades:
        entry_key = f"{trade.ticker}|{trade.entry_date}"
        stage1_group, stage2_group = _classify_stage(
            {
                "exit_urgency": trade.exit_urgency,
                "return_pct": trade.return_pct,
            }
        )
        rows.append(
            {
                "strategy_label": strategy_label,
                "entry_strategy": strategy_name,
                "entry_params_json": json.dumps(strategy_params, ensure_ascii=True, sort_keys=True),
                "exit_strategy": FIXED_EXIT_STRATEGY,
                "entry_key": entry_key,
                "ticker": trade.ticker,
                "entry_date": trade.entry_date,
                "entry_price": trade.entry_price,
                "entry_confidence": trade.entry_confidence,
                "entry_metadata_json": json.dumps(
                    trade.entry_metadata or {},
                    ensure_ascii=True,
                    sort_keys=True,
                    default=_json_default,
                ),
                "exit_date": trade.exit_date,
                "exit_price": trade.exit_price,
                "exit_reason": trade.exit_reason,
                "exit_urgency": trade.exit_urgency,
                "holding_days": trade.holding_days,
                "shares": trade.shares,
                "return_pct": trade.return_pct,
                "return_jpy": trade.return_jpy,
                "stage1_group": stage1_group,
                "stage2_group": stage2_group,
                "exit_is_full_exit": trade.exit_is_full_exit,
                "exit_sell_percentage": trade.exit_sell_percentage,
            }
        )
    return rows


def _summarize_strategy(strategy_label, strategy_name, strategy_params, result, trades_df, topix_return_pct):
    trade_rows = trades_df[trades_df["strategy_label"] == strategy_label].copy()
    total_trade_rows = len(trade_rows)
    unique_entries = trade_rows["entry_key"].nunique()

    def count_rows(group_name, column="stage2_group"):
        return int((trade_rows[column] == group_name).sum())

    def share_rows(group_name, column="stage2_group"):
        if total_trade_rows == 0:
            return 0.0
        return count_rows(group_name, column) / total_trade_rows

    bad_r_rows = count_rows("bad_r")
    good_r_rows = count_rows("good_r")
    positive_non_r_rows = count_rows("positive_non_r")
    negative_non_r_rows = count_rows("negative_non_r")

    return {
        "strategy_label": strategy_label,
        "entry_strategy": strategy_name,
        "entry_params_json": json.dumps(strategy_params, ensure_ascii=True, sort_keys=True),
        "exit_strategy": FIXED_EXIT_STRATEGY,
        "topix_return_pct": topix_return_pct,
        "alpha_vs_topix_pct": None if topix_return_pct is None else result.total_return_pct - topix_return_pct,
        "final_capital_jpy": result.final_capital_jpy,
        "total_return_pct": result.total_return_pct,
        "annualized_return_pct": result.annualized_return_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "trade_rows": total_trade_rows,
        "entry_count": unique_entries,
        "win_rate_pct": result.win_rate_pct,
        "avg_gain_pct": result.avg_gain_pct,
        "avg_loss_pct": result.avg_loss_pct,
        "avg_holding_days": result.avg_holding_days,
        "profit_factor": result.profit_factor,
        "bad_r_rows": bad_r_rows,
        "bad_r_share": share_rows("bad_r"),
        "good_r_rows": good_r_rows,
        "good_r_share": share_rows("good_r"),
        "negative_non_r_rows": negative_non_r_rows,
        "negative_non_r_share": share_rows("negative_non_r"),
        "positive_non_r_rows": positive_non_r_rows,
        "positive_non_r_share": share_rows("positive_non_r"),
        "trade_return_jpy_sum": trade_rows["return_jpy"].sum(),
    }


def _build_stage_summary(trades_df):
    summary = (
        trades_df.groupby(["strategy_label", "stage2_group"], dropna=False)
        .agg(
            trade_rows=("entry_key", "size"),
            entry_count=("entry_key", "nunique"),
            avg_return_pct=("return_pct", "mean"),
            avg_holding_days=("holding_days", "mean"),
            total_return_jpy=("return_jpy", "sum"),
        )
        .reset_index()
    )
    totals = summary.groupby("strategy_label")["trade_rows"].transform("sum")
    summary["trade_share"] = summary["trade_rows"] / totals
    return summary.sort_values(["strategy_label", "stage2_group"])


def _df_to_markdown(df: pd.DataFrame) -> str:
    table = df.fillna("N/A").astype(str)
    headers = list(table.columns)
    rows = table.values.tolist()
    separator = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _build_report(summary_df, stage_df, output_dir, topix_return_pct):
    summary_view = summary_df[[
        "strategy_label",
        "total_return_pct",
        "entry_count",
        "trade_rows",
        "bad_r_rows",
        "bad_r_share",
        "negative_non_r_rows",
        "negative_non_r_share",
        "max_drawdown_pct",
        "sharpe_ratio",
    ]].copy()
    summary_view["total_return_pct"] = summary_view["total_return_pct"].map(lambda v: f"{v:.2f}%")
    summary_view["bad_r_share"] = summary_view["bad_r_share"].map(lambda v: f"{v:.1%}")
    summary_view["negative_non_r_share"] = summary_view["negative_non_r_share"].map(lambda v: f"{v:.1%}")
    summary_view["max_drawdown_pct"] = summary_view["max_drawdown_pct"].map(lambda v: f"{v:.2f}%")
    summary_view["sharpe_ratio"] = summary_view["sharpe_ratio"].map(lambda v: f"{v:.2f}")

    lines = [
        "# PreCross2Bar Helper Variant Comparison",
        "",
        f"- Period: {PERIOD_START} to {PERIOD_END}",
        f"- Fixed exit: {FIXED_EXIT_STRATEGY}",
        f"- TOPIX return: {'N/A' if topix_return_pct is None else f'{topix_return_pct:.2f}%'}",
        "",
        "## Entry rules",
        "",
    ]
    for variant in ENTRY_VARIANTS:
        lines.append(f"- {variant['label']} ({variant['strategy_name']}): {variant['rule_summary']}")

    lines.extend([
        "",
        "## Strategy summary",
        "",
        _df_to_markdown(summary_view),
        "",
        "## Stage classification",
        "",
        _df_to_markdown(stage_df[[
            "strategy_label",
            "stage2_group",
            "trade_rows",
            "entry_count",
            "trade_share",
            "avg_return_pct",
            "total_return_jpy",
        ]].assign(
            trade_share=lambda df_: df_["trade_share"].map(lambda v: f"{v:.1%}"),
            avg_return_pct=lambda df_: df_["avg_return_pct"].map(lambda v: f"{v:.2f}%"),
            total_return_jpy=lambda df_: df_["total_return_jpy"].map(lambda v: f"{v:,.0f}"),
        )),
    ])

    report_path = output_dir / "precross2bar_helper_variants_5y_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / "strategy_evaluation" / f"precross2bar_helper_variants_5y_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)

    evaluator = StrategyEvaluator(data_root="data", output_dir=str(output_dir), verbose=False)
    tickers = evaluator._load_monitor_list()
    topix_return_pct = evaluator._get_topix_return(PERIOD_START, PERIOD_END)
    starting_capital = evaluator._get_starting_capital()
    max_positions, max_position_pct = evaluator._get_portfolio_limits()

    print(f"Running {len(ENTRY_VARIANTS)}x1 comparison on {len(tickers)} tickers")
    print(f"Period: {PERIOD_START} -> {PERIOD_END}")
    print(f"Fixed exit: {FIXED_EXIT_STRATEGY}")

    exit_strategy = load_exit_strategy(FIXED_EXIT_STRATEGY)
    summary_rows = []
    trade_rows = []

    for variant in ENTRY_VARIANTS:
        print(f"\n[{variant['label']}] {variant['strategy_name']} {variant['params']}")
        entry_strategy = load_entry_strategy(variant["strategy_name"], variant["params"])
        engine = PortfolioBacktestEngine(
            data_root="data",
            starting_capital=starting_capital,
            max_positions=max_positions,
            max_position_pct=max_position_pct,
        )
        result = engine.backtest_portfolio_strategy(
            tickers=tickers,
            entry_strategy=entry_strategy,
            exit_strategy=exit_strategy,
            start_date=PERIOD_START,
            end_date=PERIOD_END,
            show_daily_status=False,
            show_signal_ranking=False,
            show_signal_details=False,
            compute_benchmark=False,
        )
        trade_rows.extend(
            _build_trade_rows(
                strategy_label=variant["label"],
                strategy_name=variant["strategy_name"],
                strategy_params=variant["params"],
                result=result,
            )
        )
        print(
            f"Return {result.total_return_pct:+.2f}% | trades {result.num_trades} | "
            f"win rate {result.win_rate_pct:.1f}% | max DD {result.max_drawdown_pct:.2f}%"
        )
        summary_rows.append(
            {
                "strategy_label": variant["label"],
                "entry_strategy": variant["strategy_name"],
                "entry_params": variant["params"],
                "result": result,
            }
        )

    trades_df = pd.DataFrame(trade_rows)
    final_summary_rows = []
    for row in summary_rows:
        final_summary_rows.append(
            _summarize_strategy(
                strategy_label=row["strategy_label"],
                strategy_name=row["entry_strategy"],
                strategy_params=row["entry_params"],
                result=row["result"],
                trades_df=trades_df,
                topix_return_pct=topix_return_pct,
            )
        )

    summary_df = pd.DataFrame(final_summary_rows).sort_values("total_return_pct", ascending=False)
    stage_df = _build_stage_summary(trades_df)
    report_path = _build_report(summary_df, stage_df, output_dir, topix_return_pct)
    summary_df.to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    trades_df.to_csv(output_dir / "trades.csv", index=False, encoding="utf-8-sig")
    stage_df.to_csv(output_dir / "stage_summary.csv", index=False, encoding="utf-8-sig")

    print("\nSaved outputs:")
    print(output_dir)
    print(report_path)


if __name__ == "__main__":
    main()