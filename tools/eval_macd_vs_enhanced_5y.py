"""
5年回测对比：MACDCrossover（基线MVX）vs MACDEnhancedFundamental（新策略）

MACDCrossover: 简单金叉策略（仅MACD）- 当前MVX默认
MACDEnhancedFundamental: 增强版（RS + Bias）- 新优化策略

都使用 MultiViewCompositeExit（MVX默认）出场策略：
- hist_shrink_n=9
- r_mult=3.5
- trail_mult=1.6
- time_stop_days=20
- bias_exit_threshold_pct=15.0
"""

import contextlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.strategies.exit.multiview_grid_exit import MultiViewCompositeExit
from src.backtest.portfolio_engine import PortfolioBacktestEngine
from src.evaluation.strategy_evaluator import StrategyEvaluator
from src.utils.strategy_loader import load_entry_strategy


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def _build_trade_row(
    tr, period, entry_strategy, rs_threshold=None, bias_threshold=None
):
    md = tr.entry_metadata or {}
    rs_score = md.get("rs_score")
    bias_score = md.get("bias_score")
    rs_pass = None
    bias_pass = None
    combo_signal = None

    if rs_score is not None and rs_threshold is not None:
        rs_pass = rs_score > rs_threshold
    if bias_score is not None and bias_threshold is not None:
        bias_pass = bias_score > bias_threshold

    if rs_pass is not None or bias_pass is not None:
        if rs_pass and bias_pass:
            combo_signal = "RS+Bias"
        elif rs_pass:
            combo_signal = "RS"
        elif bias_pass:
            combo_signal = "Bias"
        else:
            combo_signal = "None"

    return {
        "period": period,
        "entry_strategy": entry_strategy,
        "ticker": tr.ticker,
        "entry_date": tr.entry_date,
        "entry_price": tr.entry_price,
        "entry_score": tr.entry_score,
        "entry_confidence": tr.entry_confidence,
        "entry_rs_score": rs_score,
        "entry_bias_score": bias_score,
        "entry_rs_pass": rs_pass,
        "entry_bias_pass": bias_pass,
        "entry_combo_signal": combo_signal,
        "entry_base_confidence": md.get("base_confidence"),
        "entry_rs_contribution": md.get("rs_contribution"),
        "entry_bias_contribution": md.get("bias_contribution"),
        "entry_metadata_json": json.dumps(md, ensure_ascii=True, sort_keys=True),
        "exit_date": tr.exit_date,
        "exit_price": tr.exit_price,
        "exit_reason": tr.exit_reason,
        "exit_urgency": tr.exit_urgency,
        "holding_days": tr.holding_days,
        "shares": tr.shares,
        "return_pct": tr.return_pct,
        "return_jpy": tr.return_jpy,
        "peak_price": tr.peak_price,
    }


def _build_entry_diff_report(base_trades, enhanced_trades):
    base_cols = [
        "entry_key",
        "ticker",
        "entry_date",
        "return_pct",
        "exit_reason",
        "entry_confidence",
        "entry_score",
    ]
    enh_cols = [
        "entry_key",
        "ticker",
        "entry_date",
        "return_pct",
        "exit_reason",
        "entry_confidence",
        "entry_score",
        "entry_rs_score",
        "entry_bias_score",
        "entry_rs_pass",
        "entry_bias_pass",
        "entry_combo_signal",
    ]

    base_view = base_trades[base_cols].rename(
        columns={
            "ticker": "ticker_baseline",
            "entry_date": "entry_date_baseline",
            "return_pct": "return_pct_baseline",
            "exit_reason": "exit_reason_baseline",
            "entry_confidence": "entry_confidence_baseline",
            "entry_score": "entry_score_baseline",
        }
    )
    enh_view = enhanced_trades[enh_cols].rename(
        columns={
            "ticker": "ticker_enhanced",
            "entry_date": "entry_date_enhanced",
            "return_pct": "return_pct_enhanced",
            "exit_reason": "exit_reason_enhanced",
            "entry_confidence": "entry_confidence_enhanced",
            "entry_score": "entry_score_enhanced",
        }
    )

    merged = base_view.merge(enh_view, on="entry_key", how="outer", indicator=True)
    merged["ticker"] = merged["ticker_baseline"].combine_first(
        merged["ticker_enhanced"]
    )
    merged["entry_date"] = merged["entry_date_baseline"].combine_first(
        merged["entry_date_enhanced"]
    )
    merged["presence"] = merged["_merge"].map(
        {"left_only": "baseline_only", "right_only": "enhanced_only", "both": "both"}
    )
    merged = merged.drop(columns=["_merge"])
    return merged


def _build_loss_overlap_report(base_losses, enhanced_losses):
    base_keys = set(base_losses["entry_key"])
    enhanced_keys = set(enhanced_losses["entry_key"])

    both_keys = base_keys & enhanced_keys
    only_base_keys = base_keys - enhanced_keys
    only_enh_keys = enhanced_keys - base_keys

    loss_both = base_losses[base_losses["entry_key"].isin(both_keys)].merge(
        enhanced_losses[enhanced_losses["entry_key"].isin(both_keys)],
        on="entry_key",
        suffixes=("_baseline", "_enhanced"),
    )
    loss_both["overlap_type"] = "both"

    loss_only_base = base_losses[base_losses["entry_key"].isin(only_base_keys)].copy()
    loss_only_base["overlap_type"] = "baseline_only"

    loss_only_enh = enhanced_losses[
        enhanced_losses["entry_key"].isin(only_enh_keys)
    ].copy()
    loss_only_enh["overlap_type"] = "enhanced_only"

    overlap = pd.concat(
        [loss_both, loss_only_base, loss_only_enh], ignore_index=True, sort=False
    )
    return overlap


def _run(out_dir, ts, log_path):
    print("=" * 70)
    print("5年回测对比：MVX基线 vs 增强版MACD策略")
    print("=" * 70)

    # 定义5年周期
    periods = [
        ("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025", "2025-01-01", "2025-12-31"),
    ]

    # 加载监控股票列表
    evaluator = StrategyEvaluator(
        data_root="data", output_dir="strategy_evaluation", verbose=False
    )
    tickers = evaluator._load_monitor_list()
    print(f"\n📊 监控股票数：{len(tickers)}")

    # 入场策略
    entry_baseline = load_entry_strategy("MACDCrossoverStrategy")
    entry_enhanced = load_entry_strategy("MACDEnhancedFundamental")

    # MVX默认出场参数
    exit_strategy = MultiViewCompositeExit(
        hist_shrink_n=9,
        r_mult=3.5,
        trail_mult=1.6,
        time_stop_days=20,
        bias_exit_threshold_pct=15.0,
        tp1_r=1.0,
        tp2_r=2.0,
    )
    exit_strategy.strategy_name = "MVX_Default"

    rows = []
    trade_rows = []

    print(f"\n🔄 开始回测（{len(periods)} 年，2 种入场策略）...\n")

    for i, (period, start_date, end_date) in enumerate(periods, 1):
        print(f"[{i}/{len(periods)}] {period}: {start_date} → {end_date}")

        # 回测1：基线 MACDCrossover
        engine_baseline = PortfolioBacktestEngine(
            data_root="data",
            starting_capital=5_000_000,
            max_positions=5,
        )
        result_baseline = engine_baseline.backtest_portfolio_strategy(
            tickers=tickers,
            entry_strategy=entry_baseline,
            exit_strategy=exit_strategy,
            start_date=start_date,
            end_date=end_date,
            show_signal_ranking=False,
        )

        # 回测2：增强版 MACDEnhancedFundamental
        engine_enhanced = PortfolioBacktestEngine(
            data_root="data",
            starting_capital=5_000_000,
            max_positions=5,
        )
        result_enhanced = engine_enhanced.backtest_portfolio_strategy(
            tickers=tickers,
            entry_strategy=entry_enhanced,
            exit_strategy=exit_strategy,
            start_date=start_date,
            end_date=end_date,
            show_signal_ranking=False,
        )

        # 获取TOPIX基准
        topix = evaluator._get_topix_return(start_date, end_date)

        # 记录基线结果
        rows.append(
            {
                "period": period,
                "entry_strategy": "MACDCrossover (Baseline)",
                "start_date": start_date,
                "end_date": end_date,
                "return_pct": result_baseline.total_return_pct,
                "topix_return_pct": topix,
                "alpha": None
                if topix is None
                else result_baseline.total_return_pct - topix,
                "sharpe_ratio": result_baseline.sharpe_ratio,
                "max_drawdown_pct": result_baseline.max_drawdown_pct,
                "num_trades": result_baseline.num_trades,
                "win_rate_pct": result_baseline.win_rate_pct,
                "avg_gain_pct": result_baseline.avg_gain_pct,
                "avg_loss_pct": result_baseline.avg_loss_pct,
            }
        )

        # 记录增强版结果
        rows.append(
            {
                "period": period,
                "entry_strategy": "MACDEnhancedFundamental (Enhanced)",
                "start_date": start_date,
                "end_date": end_date,
                "return_pct": result_enhanced.total_return_pct,
                "topix_return_pct": topix,
                "alpha": None
                if topix is None
                else result_enhanced.total_return_pct - topix,
                "sharpe_ratio": result_enhanced.sharpe_ratio,
                "max_drawdown_pct": result_enhanced.max_drawdown_pct,
                "num_trades": result_enhanced.num_trades,
                "win_rate_pct": result_enhanced.win_rate_pct,
                "avg_gain_pct": result_enhanced.avg_gain_pct,
                "avg_loss_pct": result_enhanced.avg_loss_pct,
            }
        )

        # 记录交易详情
        for tr in result_baseline.trades:
            trade_rows.append(
                _build_trade_row(
                    tr,
                    period,
                    "MACDCrossover",
                )
            )

        for tr in result_enhanced.trades:
            trade_rows.append(
                _build_trade_row(
                    tr,
                    period,
                    "MACDEnhancedFundamental",
                    rs_threshold=entry_enhanced.rs_threshold,
                    bias_threshold=entry_enhanced.bias_threshold,
                )
            )

        print(
            f"  ✓ MACDCrossover:           {result_baseline.total_return_pct:>7.2f}% | Max DD: {result_baseline.max_drawdown_pct:>6.2f}% | Trades: {result_baseline.num_trades:>3} | Win Rate: {result_baseline.win_rate_pct:>6.2f}%"
        )
        print(
            f"  ✓ MACDEnhancedFundamental: {result_enhanced.total_return_pct:>7.2f}% | Max DD: {result_enhanced.max_drawdown_pct:>6.2f}% | Trades: {result_enhanced.num_trades:>3} | Win Rate: {result_enhanced.win_rate_pct:>6.2f}%"
        )
        if topix is not None:
            print(f"  ✓ TOPIX Benchmark:         {topix:>7.2f}%")
        print()

    # 创建DataFrame
    df = pd.DataFrame(rows)
    tdf = pd.DataFrame(trade_rows)

    # 按年份展示对比
    print("\n" + "=" * 70)
    print("📊 年度收益率对比 (%)")
    print("=" * 70)
    pivot_return = df.pivot(
        index="period", columns="entry_strategy", values="return_pct"
    )
    pivot_return["优胜"] = ""
    for idx in pivot_return.index:
        val_baseline = pivot_return.loc[idx, "MACDCrossover (Baseline)"]
        val_enhanced = pivot_return.loc[idx, "MACDEnhancedFundamental (Enhanced)"]
        if val_enhanced > val_baseline:
            pivot_return.loc[idx, "优胜"] = (
                f"增强版 (+{val_enhanced - val_baseline:.2f}%)"
            )
        else:
            pivot_return.loc[idx, "优胜"] = (
                f"基线 (+{val_baseline - val_enhanced:.2f}%)"
            )

    print(pivot_return.round(2).to_string())

    # 汇总统计
    print("\n" + "=" * 70)
    print("📈 5年汇总统计")
    print("=" * 70)

    summary = (
        df.groupby("entry_strategy", as_index=False)
        .agg(
            {
                "return_pct": ["mean", "sum", "std", "min", "max"],
                "alpha": ["mean", "sum"],
                "sharpe_ratio": "mean",
                "max_drawdown_pct": "mean",
                "num_trades": "sum",
                "win_rate_pct": "mean",
                "avg_gain_pct": "mean",
                "avg_loss_pct": "mean",
            }
        )
        .round(2)
    )

    baseline_data = df[df["entry_strategy"] == "MACDCrossover (Baseline)"]
    enhanced_data = df[df["entry_strategy"] == "MACDEnhancedFundamental (Enhanced)"]

    baseline_return = baseline_data["return_pct"].sum()
    enhanced_return = enhanced_data["return_pct"].sum()
    return_diff = enhanced_return - baseline_return

    baseline_sharpe = baseline_data["sharpe_ratio"].mean()
    enhanced_sharpe = enhanced_data["sharpe_ratio"].mean()
    sharpe_diff = enhanced_sharpe - baseline_sharpe

    baseline_trades = baseline_data["num_trades"].sum()
    enhanced_trades = enhanced_data["num_trades"].sum()

    print(
        f"\n{'指标':<25} {'基线(MACDCrossover)':<25} {'增强版(Enhanced)':<25} {'差异':<15}"
    )
    print("-" * 95)
    print(
        f"{'5年累计收益':<25} {baseline_return:>7.2f}%{'':<17} {enhanced_return:>7.2f}%{'':<17} {return_diff:>+7.2f}%"
    )
    print(
        f"{'平均年化收益':<25} {baseline_data['return_pct'].mean():>7.2f}%{'':<17} {enhanced_data['return_pct'].mean():>7.2f}%{'':<17} {enhanced_data['return_pct'].mean() - baseline_data['return_pct'].mean():>+7.2f}%"
    )
    print(
        f"{'平均年化Sharpe':<25} {baseline_sharpe:>7.2f}{'':<20} {enhanced_sharpe:>7.2f}{'':<20} {sharpe_diff:>+7.2f}"
    )
    print(
        f"{'平均最大回撤':<25} {baseline_data['max_drawdown_pct'].mean():>7.2f}%{'':<17} {enhanced_data['max_drawdown_pct'].mean():>7.2f}%"
    )
    print(
        f"{'总交易数':<25} {baseline_trades:>7.0f}{'':<20} {enhanced_trades:>7.0f}{'':<20}"
    )
    print(
        f"{'平均胜率':<25} {baseline_data['win_rate_pct'].mean():>7.2f}%{'':<17} {enhanced_data['win_rate_pct'].mean():>7.2f}%"
    )

    # 交易统计
    if not tdf.empty:
        print("\n" + "=" * 70)
        print("📋 交易统计（平均单笔）")
        print("=" * 70)

        trade_summary = (
            tdf.groupby("entry_strategy", as_index=False)
            .agg(
                {
                    "holding_days": ["mean", "median"],
                    "return_pct": ["mean", "std"],
                }
            )
            .round(2)
        )

        print(trade_summary.to_string(index=False))

        print("\n胜率详情：")
        for strategy in ["MACDCrossover", "MACDEnhancedFundamental"]:
            strategy_trades = tdf[tdf["entry_strategy"] == strategy]
            if not strategy_trades.empty:
                wins = (strategy_trades["return_pct"] > 0).sum()
                total = len(strategy_trades)
                avg_win = (
                    strategy_trades[strategy_trades["return_pct"] > 0][
                        "return_pct"
                    ].mean()
                    if wins > 0
                    else 0
                )
                avg_loss = (
                    strategy_trades[strategy_trades["return_pct"] <= 0][
                        "return_pct"
                    ].mean()
                    if total - wins > 0
                    else 0
                )
                print(
                    f"  {strategy:<30} 胜率: {wins}/{total} ({100 * wins / total:.1f}%), 平均赢: {avg_win:+.2f}%, 平均亏: {avg_loss:+.2f}%"
                )

    if not tdf.empty:
        tdf["entry_key"] = (
            tdf["ticker"].astype(str) + "|" + tdf["entry_date"].astype(str)
        )
        base_trades = tdf[tdf["entry_strategy"] == "MACDCrossover"].copy()
        enhanced_trades = tdf[tdf["entry_strategy"] == "MACDEnhancedFundamental"].copy()

        entry_diff = _build_entry_diff_report(base_trades, enhanced_trades)

        loss_base = base_trades[base_trades["return_pct"] < 0].copy()
        loss_enh = enhanced_trades[enhanced_trades["return_pct"] < 0].copy()
        loss_overlap = _build_loss_overlap_report(loss_base, loss_enh)

        base_counts = base_trades.groupby("ticker").size().rename("baseline_trades")
        enh_counts = enhanced_trades.groupby("ticker").size().rename("enhanced_trades")
        ticker_diff = (
            pd.concat([base_counts, enh_counts], axis=1)
            .fillna(0)
            .reset_index()
            .rename(columns={"index": "ticker"})
        )
        ticker_diff["baseline_trades"] = ticker_diff["baseline_trades"].astype(int)
        ticker_diff["enhanced_trades"] = ticker_diff["enhanced_trades"].astype(int)
        ticker_diff["in_baseline"] = ticker_diff["baseline_trades"] > 0
        ticker_diff["in_enhanced"] = ticker_diff["enhanced_trades"] > 0

        print("\n📌 入场股票对比:")
        print(f"  基线入场股票数: {ticker_diff['in_baseline'].sum()}")
        print(f"  增强入场股票数: {ticker_diff['in_enhanced'].sum()}")
        print(
            f"  交集股票数: {(ticker_diff['in_baseline'] & ticker_diff['in_enhanced']).sum()}"
        )
        print(
            f"  仅基线股票数: {(ticker_diff['in_baseline'] & ~ticker_diff['in_enhanced']).sum()}"
        )
        print(
            f"  仅增强股票数: {(~ticker_diff['in_baseline'] & ticker_diff['in_enhanced']).sum()}"
        )

    # 保存结果
    raw_path = out_dir / f"macd_vs_enhanced_5y_raw_{ts}.csv"
    trade_path = out_dir / f"macd_vs_enhanced_5y_trades_{ts}.csv"
    trade_detail_path = out_dir / f"macd_vs_enhanced_5y_trades_enriched_{ts}.csv"
    entry_diff_path = out_dir / f"macd_vs_enhanced_5y_entry_diff_{ts}.csv"
    loss_overlap_path = out_dir / f"macd_vs_enhanced_5y_loss_overlap_{ts}.csv"
    ticker_diff_path = out_dir / f"macd_vs_enhanced_5y_ticker_diff_{ts}.csv"

    df.to_csv(raw_path, index=False)
    tdf.to_csv(trade_path, index=False)
    if not tdf.empty:
        tdf.to_csv(trade_detail_path, index=False)
        entry_diff.to_csv(entry_diff_path, index=False)
        loss_overlap.to_csv(loss_overlap_path, index=False)
        ticker_diff.to_csv(ticker_diff_path, index=False)

    print("\n✅ 保存结果：")
    print(f"   {raw_path}")
    print(f"   {trade_path}")
    if not tdf.empty:
        print(f"   {trade_detail_path}")
        print(f"   {entry_diff_path}")
        print(f"   {loss_overlap_path}")
        print(f"   {ticker_diff_path}")
    print(f"   {log_path}")


def main():
    out_dir = Path("strategy_evaluation")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = out_dir / f"macd_vs_enhanced_5y_log_{ts}.txt"

    with open(log_path, "w", encoding="utf-8") as log_file:
        with contextlib.redirect_stdout(Tee(sys.stdout, log_file)):
            _run(out_dir, ts, log_path)


if __name__ == "__main__":
    main()
