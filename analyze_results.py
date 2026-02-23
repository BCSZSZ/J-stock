#!/usr/bin/env python3
"""分析45个回测结果，提取标准出场策略的结果进行对比"""

import pandas as pd

# 读取回测数据
csv_path = r"G:\My Drive\AI-Stock-Sync\strategy_evaluation\strategy_evaluation_raw_20260223_180437.csv"
df = pd.read_csv(csv_path)

print("=" * 100)
print("方案A 5年回测结果分析 (45个结果)")
print("=" * 100)
print(f"\n总回测数: {len(df)}")
print(f"入场策略数: {df['entry_strategy'].nunique()}")
print(f"出场策略数: {df['exit_strategy'].nunique()}")
print(f"年份数: {df['period'].nunique()}")

# 统计
print(f"\n入场策略: {sorted(df['entry_strategy'].unique())}")
print(f"出场策略: {sorted(df['exit_strategy'].unique())}")
print(f"年份: {sorted(df['period'].unique())}")

# 提取标准出场策略的结果（15个）
standard_exit = "MVX_N9_R3p4_T1p6_D18_B20p0"
df_standard = df[df["exit_strategy"] == standard_exit].copy()

print("\n\n" + "=" * 100)
print(f"标准退场策略结果分析 ({standard_exit})")
print("=" * 100)

# 按入场策略和年份创建对比表
pivot_table = df_standard.pivot_table(
    values="return_pct", index="entry_strategy", columns="period", aggfunc="first"
)

print("\n【年度收益率对比 (%)】\n")
print(pivot_table.round(2))

# 计算平均收益
print("\n【平均收益率】\n")
for strategy in sorted(df_standard["entry_strategy"].unique()):
    returns = df_standard[df_standard["entry_strategy"] == strategy][
        "return_pct"
    ].values
    avg = returns.mean()
    print(f"{strategy:35s}: {avg:7.2f}%")

# 年份对比
print("\n【各年份收益排名】\n")
for year in sorted(df_standard["period"].unique()):
    print(f"\n{year}年:")
    year_data = df_standard[df_standard["period"] == year][
        ["entry_strategy", "return_pct"]
    ].sort_values("return_pct", ascending=False)
    for idx, row in year_data.iterrows():
        print(f"  {row['entry_strategy']:35s}: {row['return_pct']:7.2f}%")

# 性能对比矩阵
print("\n【性能对比：A2 vs 基准MACD 的差异 (%)】\n")
base_strategy = "MACDCrossoverStrategy"
enhanced_strategies = ["MACDCrossoverEnhancedA2"]

comparison_data = []
for year in sorted(df_standard["period"].unique()):
    year_subset = df_standard[df_standard["period"] == year]
    base_return = year_subset[year_subset["entry_strategy"] == base_strategy][
        "return_pct"
    ].values[0]

    for strat in enhanced_strategies:
        enhanced_return = year_subset[year_subset["entry_strategy"] == strat][
            "return_pct"
        ].values[0]
        diff = enhanced_return - base_return
        diff_pct = (diff / base_return * 100) if base_return != 0 else 0
        comparison_data.append(
            {
                "Year": year,
                "Strategy": strat,
                "Base": base_return,
                "Enhanced": enhanced_return,
                "Diff": diff,
                "Diff%": diff_pct,
            }
        )

comp_df = pd.DataFrame(comparison_data)
for strat in enhanced_strategies:
    print(f"\n{strat}:")
    strat_data = comp_df[comp_df["Strategy"] == strat]
    for _, row in strat_data.iterrows():
        status = "✓" if row["Diff"] >= 0 else "✗"
        print(
            f"  {row['Year']}年: {row['Enhanced']:7.2f}% vs {row['Base']:7.2f}% → {row['Diff']:+7.2f}% ({row['Diff%']:+6.1f}%) {status}"
        )

    avg_diff = strat_data["Diff"].mean()
    avg_diff_pct = strat_data["Diff%"].mean()
    print(f"  平均: {avg_diff:+7.2f}% ({avg_diff_pct:+6.1f}%)\n")
