"""
Analyze exit trigger distribution and P&L for D/B parameter grid.
Focus on T1_TimeStop (D parameter) and P_BiasOverheat (B parameter).
"""

from pathlib import Path

import pandas as pd

# Load trade data
trade_file = Path("strategy_evaluation/custom_db_3x3_trades_20260222_024413.csv")
df = pd.read_csv(trade_file)

print("=" * 80)
print("出场触发器统计分析 - D/B参数影响")
print("=" * 80)
print()

# Overall trigger distribution
print("### 全部交易出场触发器分布")
print(f"总交易数: {len(df)}")
print()
trigger_counts = df["exit_urgency"].value_counts()
for trigger, count in trigger_counts.items():
    pct = count / len(df) * 100
    print(f"  {trigger:20s}: {count:4d} ({pct:5.2f}%)")
print()

# ============================================================================
# D Parameter Analysis (T1_TimeStop)
# ============================================================================
print("=" * 80)
print("D参数分析 - T1_TimeStop (时间止损) 触发统计")
print("=" * 80)
print()

time_stop_df = df[df["exit_urgency"] == "T1_TimeStop"].copy()

print("### D值影响 (time_stop_days)")
print()

for d in sorted(df["D"].unique()):
    d_all = df[df["D"] == d]
    d_time_stop = time_stop_df[time_stop_df["D"] == d]

    total_trades = len(d_all)
    time_stop_count = len(d_time_stop)
    time_stop_pct = time_stop_count / total_trades * 100 if total_trades > 0 else 0

    # P&L stats for time stop triggered trades
    if len(d_time_stop) > 0:
        avg_return = d_time_stop["return_pct"].mean()
        win_count = (d_time_stop["return_pct"] > 0).sum()
        loss_count = (d_time_stop["return_pct"] <= 0).sum()
        win_rate = win_count / len(d_time_stop) * 100

        win_trades = d_time_stop[d_time_stop["return_pct"] > 0]
        loss_trades = d_time_stop[d_time_stop["return_pct"] <= 0]

        avg_win = win_trades["return_pct"].mean() if len(win_trades) > 0 else 0
        avg_loss = loss_trades["return_pct"].mean() if len(loss_trades) > 0 else 0

        print(f"D={d}天:")
        print(f"  总交易数: {total_trades}")
        print(f"  T1_TimeStop触发: {time_stop_count} ({time_stop_pct:.2f}%)")
        print(f"  平均收益: {avg_return:+.2f}%")
        print(f"  胜率: {win_rate:.2f}% ({win_count}胜/{loss_count}负)")
        print(f"  盈利平均: +{avg_win:.2f}%")
        print(f"  亏损平均: {avg_loss:.2f}%")
    else:
        print(f"D={d}天:")
        print(f"  总交易数: {total_trades}")
        print(f"  T1_TimeStop触发: {time_stop_count} ({time_stop_pct:.2f}%)")
        print("  无触发数据")
    print()

# D parameter cross-tab with B
print("### D参数触发次数交叉分析 (按B值细分)")
print()
time_stop_pivot = time_stop_df.groupby(["D", "B"]).size().unstack(fill_value=0)
print(time_stop_pivot)
print()

# Average return for time stop by D and B
print("### T1_TimeStop触发交易的平均收益率 (D × B)")
print()
time_stop_returns = time_stop_df.groupby(["D", "B"])["return_pct"].mean().unstack()
print(time_stop_returns.round(2))
print()

# ============================================================================
# B Parameter Analysis (P_BiasOverheat)
# ============================================================================
print("=" * 80)
print("B参数分析 - P_BiasOverheat (乖离率超热) 触发统计")
print("=" * 80)
print()

bias_df = df[df["exit_urgency"] == "P_BiasOverheat"].copy()

print("### B值影响 (bias_exit_threshold)")
print()

for b in sorted(df["B"].unique()):
    b_all = df[df["B"] == b]
    b_bias = bias_df[bias_df["B"] == b]

    total_trades = len(b_all)
    bias_count = len(b_bias)
    bias_pct = bias_count / total_trades * 100 if total_trades > 0 else 0

    # P&L stats for bias triggered trades
    if len(b_bias) > 0:
        avg_return = b_bias["return_pct"].mean()
        win_count = (b_bias["return_pct"] > 0).sum()
        loss_count = (b_bias["return_pct"] <= 0).sum()
        win_rate = win_count / len(b_bias) * 100

        win_trades = b_bias[b_bias["return_pct"] > 0]
        loss_trades = b_bias[b_bias["return_pct"] <= 0]

        avg_win = win_trades["return_pct"].mean() if len(win_trades) > 0 else 0
        avg_loss = loss_trades["return_pct"].mean() if len(loss_trades) > 0 else 0

        print(f"B={b}%:")
        print(f"  总交易数: {total_trades}")
        print(f"  P_BiasOverheat触发: {bias_count} ({bias_pct:.2f}%)")
        print(f"  平均收益: {avg_return:+.2f}%")
        print(f"  胜率: {win_rate:.2f}% ({win_count}胜/{loss_count}负)")
        print(f"  盈利平均: +{avg_win:.2f}%")
        print(f"  亏损平均: {avg_loss:.2f}%")
    else:
        print(f"B={b}%:")
        print(f"  总交易数: {total_trades}")
        print(f"  P_BiasOverheat触发: {bias_count} ({bias_pct:.2f}%)")
        print("  无触发数据")
    print()

# B parameter cross-tab with D
print("### B参数触发次数交叉分析 (按D值细分)")
print()
bias_pivot = bias_df.groupby(["B", "D"]).size().unstack(fill_value=0)
print(bias_pivot)
print()

# Average return for bias overheat by B and D
print("### P_BiasOverheat触发交易的平均收益率 (B × D)")
print()
bias_returns = bias_df.groupby(["B", "D"])["return_pct"].mean().unstack()
print(bias_returns.round(2))
print()

# ============================================================================
# Combined Analysis
# ============================================================================
print("=" * 80)
print("综合分析 - 各参数组合的触发分布")
print("=" * 80)
print()

print("### 各参数组合的出场触发器分布")
print()
for (d, b), group in df.groupby(["D", "B"]):
    print(f"D={d}, B={b}:")
    trigger_dist = group["exit_urgency"].value_counts()
    for trigger, count in trigger_dist.items():
        pct = count / len(group) * 100
        avg_ret = group[group["exit_urgency"] == trigger]["return_pct"].mean()
        print(f"  {trigger:20s}: {count:3d} ({pct:5.2f}%) - 平均收益: {avg_ret:+6.2f}%")
    print()

# ============================================================================
# Key Insights Summary
# ============================================================================
print("=" * 80)
print("核心洞察")
print("=" * 80)
print()

# Compare D15 vs D20 vs D25 for TimeStop
print("### D参数对比 - TimeStop触发率")
for d in sorted(df["D"].unique()):
    d_df = df[df["D"] == d]
    ts_count = len(time_stop_df[time_stop_df["D"] == d])
    ts_rate = ts_count / len(d_df) * 100
    print(f"  D={d}天: {ts_rate:.2f}% ({ts_count}/{len(d_df)})")
print()

# Compare B10 vs B15 vs B20 for BiasOverheat
print("### B参数对比 - BiasOverheat触发率")
for b in sorted(df["B"].unique()):
    b_df = df[df["B"] == b]
    bo_count = len(bias_df[bias_df["B"] == b])
    bo_rate = bo_count / len(b_df) * 100
    print(f"  B={b}%: {bo_rate:.2f}% ({bo_count}/{len(b_df)})")
print()

# Best combination analysis
print("### 最佳组合 D20_B20 的触发分布")
d20b20 = df[(df["D"] == 20) & (df["B"] == 20)]
print(f"  总交易数: {len(d20b20)}")
trigger_dist = d20b20["exit_urgency"].value_counts()
for trigger, count in trigger_dist.items():
    pct = count / len(d20b20) * 100
    avg_ret = d20b20[d20b20["exit_urgency"] == trigger]["return_pct"].mean()
    print(f"  {trigger:20s}: {count:3d} ({pct:5.2f}%) - 平均收益: {avg_ret:+6.2f}%")
print()

print("=" * 80)
print("分析完成")
print("=" * 80)
