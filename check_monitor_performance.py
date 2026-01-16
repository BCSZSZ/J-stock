"""Check existing monitor list performance in global ranking"""
import pandas as pd
import json

# Load top 50 selection
with open('data/universe/top50_selection_20260116_131231.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

df_top50 = pd.DataFrame(data['tickers'])

# Monitor list codes
monitor_codes = ['8035','8306','7974','7011','6861','8058','6501','4063','7203','4568','6098','1321']

# Check which monitor stocks made it into top 50
monitor_in_top50 = df_top50[df_top50['code'].isin(monitor_codes)]

print('=== 你的Monitor List (12支)在Top50中的表现 ===\n')

if len(monitor_in_top50) > 0:
    print(monitor_in_top50[['rank','code','name','total_score','rank_vol','rank_liq','rank_trend','rank_momentum','rank_volsurge']].to_string(index=False))
    print(f'\n✅ Top50命中率: {len(monitor_in_top50)}/12 ({len(monitor_in_top50)/12*100:.1f}%)')
else:
    print('❌ 没有一支进入Top50')

# Load ALL scores to see full rankings
print('\n=== 尝试从全局数据中查找所有12支的排名 ===')
all_scores = pd.read_parquet('data/universe/scores_all_20260116_131137.parquet')

# Check columns
print(f'可用列: {list(all_scores.columns)}')
