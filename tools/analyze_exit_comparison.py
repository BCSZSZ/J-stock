"""Summarize production vs champion exit conditions (continuous mode, all regimes)."""
import pandas as pd
import os

def load_and_aggregate(csv_path, exit_strategy, period):
    df = pd.read_csv(csv_path)
    sub = df[
        (df['exit_strategy'] == exit_strategy)
        & (df['trade_scope'] == 'all_trades')
        & (df['period'] == period)
    ].copy()

    if sub.empty:
        raise ValueError(f"No data for {exit_strategy} period={period} in {os.path.basename(csv_path)}")

    agg = []
    for urgency, g in sub.groupby('exit_urgency'):
        tc = g['trade_count'].sum()
        total_jpy = g['total_return_jpy'].sum()
        w_avg_ret = (g['avg_return_pct'] * g['trade_count']).sum() / tc
        w_avg_hold = (g['avg_holding_days'] * g['trade_count']).sum() / tc
        w_win = (g['win_rate_pct'] * g['trade_count']).sum() / tc
        agg.append({
            'trigger': urgency,
            'count': int(tc),
            'total_jpy': total_jpy,
            'avg_ret_pct': w_avg_ret,
            'avg_hold': w_avg_hold,
            'win_rate': w_win,
        })
    result = pd.DataFrame(agg)
    total = result['count'].sum()
    result['ratio'] = result['count'] / total
    result['contribution_pct'] = result['total_jpy'] / result['total_jpy'].sum() * 100
    result = result.sort_values('count', ascending=False)
    return result, total


def print_table(title, result, total):
    print(f"\n{'='*100}")
    print(f"  {title}")
    print(f"{'='*100}")
    print(f"{'Trigger':22s} {'Count':>6s} {'Ratio':>7s} {'AvgRet%':>9s} {'WinRate':>8s} {'HoldDay':>8s} {'Contrib%':>9s} {'TotalJPY':>15s}")
    print('-'*100)
    for _, r in result.iterrows():
        print(f"{r['trigger']:22s} {r['count']:6d} {r['ratio']:6.1%} {r['avg_ret_pct']:+8.2f}% {r['win_rate']:7.1f}% {r['avg_hold']:7.1f}d {r['contribution_pct']:+8.1f}% {r['total_jpy']:+15,.0f}")
    total_jpy = result['total_jpy'].sum()
    w_avg_ret = (result['avg_ret_pct'] * result['count']).sum() / total
    w_win = (result['win_rate'] * result['count']).sum() / total
    w_hold = (result['avg_hold'] * result['count']).sum() / total
    print('-'*100)
    print(f"{'TOTAL':22s} {total:6d} {1.0:6.1%} {w_avg_ret:+8.2f}% {w_win:7.1f}% {w_hold:7.1f}d {'100.0%':>9s} {total_jpy:+15,.0f}")


# ── Data sources (continuous mode, all regimes aggregated) ──
base = r"G:\My Drive\AI-Stock-Sync\strategy_evaluation"

prod_strategy = "MVX_N3_R3p25_T1p6_D21_B20p0"
champ_strategy = "MVXW_N5_R3p35_T1p6_D21_B20p0"

prod_csv = os.path.join(base, "mvx_d21_cli_20260409", "production_reference",
                        "strategy_evaluation_continuous_exit_trigger_summary_20260409_135227.csv")
champ_csv = os.path.join(base, "mvxw_d21_cli_20260410", "twobar_champion_sweep",
                         "strategy_evaluation_continuous_exit_trigger_summary_20260410_150539.csv")

print(f"Production: {os.path.basename(os.path.dirname(prod_csv))}/{os.path.basename(prod_csv)}")
print(f"Champion:   {os.path.basename(os.path.dirname(champ_csv))}/{os.path.basename(champ_csv)}")

# ── Part 1: Production exit triggers ──
prod_result, prod_total = load_and_aggregate(prod_csv, prod_strategy, "2021-2025_continuous")
print_table(f"PRODUCTION: {prod_strategy}  entry=MACDCrossoverStrategy  (continuous 2021-2025)", prod_result, prod_total)

# ── Part 2: Champion exit triggers ──
champ_result, champ_total = load_and_aggregate(champ_csv, champ_strategy, "2021-2025_continuous")
print_table(f"CHAMPION: {champ_strategy}  entry=MACDPreCross2BarEntry  (continuous 2021-2025)", champ_result, champ_total)

# ── Part 3: Side-by-side comparison ──
print(f"\n{'='*110}")
print(f"  COMPARISON: Production vs Champion (continuous 2021-2025)")
print(f"  NOTE: Different entry strategies — MACDCrossover (prod) vs MACDPreCross2Bar (champ)")
print(f"{'='*110}")
print(f"{'Trigger':22s} | {'P.Count':>7s} {'P.Ratio':>7s} {'P.AvgRet':>9s} {'P.Win%':>7s} | {'C.Count':>7s} {'C.Ratio':>7s} {'C.AvgRet':>9s} {'C.Win%':>7s} | {'dRet':>8s}")
print('-'*110)

all_triggers = sorted(set(prod_result['trigger'].tolist() + champ_result['trigger'].tolist()))

for t in all_triggers:
    p = prod_result[prod_result['trigger'] == t]
    c = champ_result[champ_result['trigger'] == t]
    pc = int(p['count'].values[0]) if len(p) else 0
    pr = p['ratio'].values[0] if len(p) else 0
    pret = p['avg_ret_pct'].values[0] if len(p) else 0
    pwin = p['win_rate'].values[0] if len(p) else 0
    cc = int(c['count'].values[0]) if len(c) else 0
    cr = c['ratio'].values[0] if len(c) else 0
    cret = c['avg_ret_pct'].values[0] if len(c) else 0
    cwin = c['win_rate'].values[0] if len(c) else 0
    diff = cret - pret if (len(p) and len(c)) else float('nan')
    d = f"{diff:+7.2f}%" if not pd.isna(diff) else "    N/A"
    pp = f"{pr:6.1%}" if pc else "    - "
    cp = f"{cr:6.1%}" if cc else "    - "
    pr_s = f"{pret:+8.2f}%" if pc else "      -  "
    cr_s = f"{cret:+8.2f}%" if cc else "      -  "
    pw_s = f"{pwin:6.1f}%" if pc else "     - "
    cw_s = f"{cwin:6.1f}%" if cc else "     - "
    print(f"{t:22s} | {pc:7d} {pp} {pr_s} {pw_s} | {cc:7d} {cp} {cr_s} {cw_s} | {d}")

# Totals
p_total_jpy = prod_result['total_jpy'].sum()
c_total_jpy = champ_result['total_jpy'].sum()
p_avg = (prod_result['avg_ret_pct'] * prod_result['count']).sum() / prod_total
c_avg = (champ_result['avg_ret_pct'] * champ_result['count']).sum() / champ_total
p_win = (prod_result['win_rate'] * prod_result['count']).sum() / prod_total
c_win = (champ_result['win_rate'] * champ_result['count']).sum() / champ_total
print('-'*110)
print(f"{'TOTAL':22s} | {prod_total:7d}  100% {p_avg:+8.2f}% {p_win:6.1f}% | {champ_total:7d}  100% {c_avg:+8.2f}% {c_win:6.1f}% | {c_avg-p_avg:+7.2f}%")
print(f"{'Total Return JPY':22s} | {p_total_jpy:+15,.0f}              | {c_total_jpy:+15,.0f}")
print()
pct_improve = (c_total_jpy - p_total_jpy) / abs(p_total_jpy) * 100 if p_total_jpy != 0 else float('inf')
print(f"Champion total return advantage: {c_total_jpy - p_total_jpy:+,.0f} JPY ({pct_improve:+.1f}%)")
