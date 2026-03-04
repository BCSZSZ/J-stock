import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


def parse_strategy_parts(combo_id: str):
    strategy, profile, overlay_part = combo_id.split("|")
    overlay = overlay_part.replace("ovl=", "")
    parts = strategy.split("_")
    r_part = [p for p in parts if p.startswith("R")][0].replace("R", "").replace("p", ".")
    t_part = [p for p in parts if p.startswith("T")][0].replace("T", "").replace("p", ".")
    return strategy, profile, overlay, float(r_part), float(t_part)


def to_md_table(df: pd.DataFrame, cols):
    subset = df[cols].copy()
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = []
    for _, row in subset.iterrows():
        vals = []
        for col in cols:
            v = row[col]
            if pd.isna(v):
                vals.append("")
            elif isinstance(v, float):
                vals.append(f"{v:.6f}".rstrip("0").rstrip("."))
            else:
                vals.append(str(v))
        rows.append("| " + " | ".join(vals) + " |")
    return "\n".join([header, sep] + rows)


def main():
    parser = argparse.ArgumentParser(description="Build markdown report for 1x9x4x2 matrix results")
    parser.add_argument("--raw-csv", required=True)
    parser.add_argument("--rank-csv", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    raw = pd.read_csv(args.raw_csv)
    rank = pd.read_csv(args.rank_csv)

    required_raw = {"combo_id", "period", "return_pct", "alpha", "max_drawdown_pct", "sharpe_ratio", "win_rate_pct", "num_trades", "avg_gain_pct", "avg_loss_pct"}
    missing_raw = required_raw - set(raw.columns)
    if missing_raw:
        raise ValueError(f"Missing columns in raw csv: {sorted(missing_raw)}")

    rank = rank.copy()
    parsed = rank["strategy"].apply(parse_strategy_parts)
    rank[["exit_strategy", "position_profile", "overlay_mode", "r_value", "t_value"]] = pd.DataFrame(parsed.tolist(), index=rank.index)

    # summary per combo from raw (keeps original raw aggregates visible)
    combo_summary = (
        raw.groupby("combo_id", as_index=False)
        .agg(
            avg_return=("return_pct", "mean"),
            avg_alpha=("alpha", "mean"),
            avg_mdd=("max_drawdown_pct", "mean"),
            avg_sharpe=("sharpe_ratio", "mean"),
            avg_win_rate=("win_rate_pct", "mean"),
            worst_year_return=("return_pct", "min"),
            best_year_return=("return_pct", "max"),
            avg_trades=("num_trades", "mean"),
        )
    )

    combo_summary = combo_summary.merge(
        rank[["strategy", "rank", "final_score", "position_profile", "overlay_mode", "r_value", "t_value"]],
        left_on="combo_id",
        right_on="strategy",
        how="left",
    ).drop(columns=["strategy"])

    combo_summary = combo_summary.sort_values("rank")

    top5 = combo_summary.head(5).copy()
    top5_ids = top5["combo_id"].tolist()

    top5_yearly = raw[raw["combo_id"].isin(top5_ids)].copy()
    top5_yearly = top5_yearly.sort_values(["combo_id", "period"])

    # full yearly raw table for all combos
    yearly_all = raw.copy().sort_values(["combo_id", "period"])

    # overlay and position diagnostics
    overlay_diag = raw.groupby("overlay_mode", as_index=False).agg(
        avg_return=("return_pct", "mean"),
        avg_alpha=("alpha", "mean"),
        avg_mdd=("max_drawdown_pct", "mean"),
        avg_sharpe=("sharpe_ratio", "mean"),
    )
    position_diag = raw.groupby("position_profile", as_index=False).agg(
        avg_return=("return_pct", "mean"),
        avg_alpha=("alpha", "mean"),
        avg_mdd=("max_drawdown_pct", "mean"),
        avg_sharpe=("sharpe_ratio", "mean"),
    )

    # top5 commentary
    comments = []
    for _, row in top5.iterrows():
        cid = row["combo_id"]
        r = row["r_value"]
        t = row["t_value"]
        ovl = row["overlay_mode"]
        pos = row["position_profile"]
        yrs = top5_yearly[top5_yearly["combo_id"] == cid]
        positive_years = int((yrs["alpha"] > 0).sum())
        worst = yrs.loc[yrs["return_pct"].idxmin()]
        best = yrs.loc[yrs["return_pct"].idxmax()]
        comments.append(
            f"### {int(row['rank'])}. {cid}\n"
            f"- 量化指标：Final Score={row['final_score']:.4f}，Avg Return={row['avg_return']:.2f}%，Avg Alpha={row['avg_alpha']:.2f}%，Avg MDD={row['avg_mdd']:.2f}%\n"
            f"- 参数特征：R={r:.1f}，T={t:.1f}，仓位={pos}，overlay={ovl}\n"
            f"- 跨年稳健性：5年中正Alpha年份={positive_years}/5，最差年份={worst['period']}({worst['return_pct']:.2f}%)，最好年份={best['period']}({best['return_pct']:.2f}%)\n"
            f"- 推测：{'较高R和较高T组合更偏向持有趋势、减少过早止盈' if (r >= 3.5 and t >= 1.6) else '较低R或较低T提升了风控灵敏度，改善回撤但可能压缩趋势利润'}；"
            f"{'overlay on 在该组合上提供了择时增益' if ovl == 'on' else 'overlay off 说明基础出场已具备较强稳健性'}。\n"
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# 1x9x4x2 回测综合报告（5年）\n\n")
        f.write(f"生成时间: {now}\n\n")
        f.write("## 一、样本说明\n\n")
        f.write(f"- 总记录数: {len(raw)}（72组合 × 5年份）\n")
        f.write(f"- 组合数: {raw['combo_id'].nunique()}\n")
        f.write("- 评分模型: risk60_profit40_v2（风险60% + 收益40%）\n")
        f.write("- 默认初始资金: 8,000,000 JPY\n\n")

        f.write("## 二、总排名（前20）\n\n")
        f.write(to_md_table(combo_summary.head(20), [
            "rank", "combo_id", "final_score", "avg_return", "avg_alpha", "avg_mdd", "avg_sharpe", "worst_year_return", "position_profile", "overlay_mode", "r_value", "t_value"
        ]))
        f.write("\n\n")

        f.write("## 三、全量组合原始汇总（72组合）\n\n")
        f.write(to_md_table(combo_summary, [
            "rank", "combo_id", "final_score", "avg_return", "avg_alpha", "avg_mdd", "avg_sharpe", "avg_win_rate", "worst_year_return", "best_year_return", "avg_trades"
        ]))
        f.write("\n\n")

        f.write("## 四、每个组合逐年原始数据（收益/回撤/Sharpe/胜率/交易数）\n\n")
        f.write(to_md_table(yearly_all, [
            "combo_id", "period", "return_pct", "alpha", "max_drawdown_pct", "sharpe_ratio", "win_rate_pct", "num_trades", "avg_gain_pct", "avg_loss_pct"
        ]))
        f.write("\n\n")

        f.write("## 五、前5名量化评价（按市场常用标准）\n\n")
        f.write("评价维度：收益能力（Return/Alpha）、风险控制（MDD）、风险收益效率（Sharpe）、跨年一致性（正Alpha年份占比）。\n\n")
        for text in comments:
            f.write(text + "\n")

        f.write("## 六、前5名五年逐年展开\n\n")
        f.write(to_md_table(top5_yearly, [
            "combo_id", "period", "return_pct", "alpha", "max_drawdown_pct", "sharpe_ratio", "win_rate_pct", "num_trades", "avg_gain_pct", "avg_loss_pct"
        ]))
        f.write("\n\n")

        f.write("## 七、维度归因（overlay / 仓位）\n\n")
        f.write("### 7.1 Overlay On/Off 均值对比\n\n")
        f.write(to_md_table(overlay_diag, ["overlay_mode", "avg_return", "avg_alpha", "avg_mdd", "avg_sharpe"]))
        f.write("\n\n")
        f.write("### 7.2 仓位策略均值对比\n\n")
        f.write(to_md_table(position_diag, ["position_profile", "avg_return", "avg_alpha", "avg_mdd", "avg_sharpe"]))
        f.write("\n\n")

        f.write("## 八、结论（当前样本）\n\n")
        best = combo_summary.iloc[0]
        f.write(f"- 综合最优组合：{best['combo_id']}（Score={best['final_score']:.4f}）。\n")
        f.write("- 参数上，Top组普遍集中在更高R/更高T，表明在该5年样本中，适度放宽止盈与尾随阈值更有利于趋势利润释放。\n")
        f.write("- overlay维度在均值上提升了Return/Alpha，但并未显著降低MDD，说明它更偏向收益增强而非纯防守。\n")
        f.write("- 仓位维度上，7x0.18 在收益和Alpha上更占优，10x0.10 风险更低但机会成本更高。\n")


if __name__ == "__main__":
    main()
