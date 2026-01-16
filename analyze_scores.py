"""Quick script to analyze universe selection scores"""
import pandas as pd
import json
import sys

# Get filename from command line or use default
filename = sys.argv[1] if len(sys.argv) > 1 else 'data/universe/top50_selection_20260116_131231.json'

with open(filename, 'r', encoding='utf-8') as f:
    data = json.load(f)

df = pd.DataFrame(data['tickers'])

print('=== Score Distribution ===')
print(df['total_score'].describe())

print('\n=== Score Value Counts ===')
print(df['total_score'].value_counts().sort_index(ascending=False).head(15))

print('\n=== Top 20 by Rank ===')
cols = ['rank', 'code', 'total_score', 'rank_vol', 'rank_liq', 'rank_trend']
if 'rank_momentum' in df.columns:
    cols.append('rank_momentum')
if 'rank_volsurge' in df.columns:
    cols.append('rank_volsurge')
print(df[cols].head(20).to_string(index=False))

print('\n=== Stocks with Score = 1.0 ===')
print(f"Count: {(df['total_score'] == 1.0).sum()}")

print('\n=== Stocks with Score > 0.98 ===')
print(f"Count: {(df['total_score'] > 0.98).sum()}")

print('\n=== Stocks with Score > 0.95 ===')
print(f"Count: {(df['total_score'] > 0.95).sum()}")

print('\n=== Component Rank Distribution ===')
print(f"Rank_Vol = 1.0: {(df['rank_vol'] == 1.0).sum()}")
print(f"Rank_Liq = 1.0: {(df['rank_liq'] == 1.0).sum()}")
print(f"Rank_Trend = 1.0: {(df['rank_trend'] == 1.0).sum()}")
if 'rank_momentum' in df.columns:
    print(f"Rank_Momentum = 1.0: {(df['rank_momentum'] == 1.0).sum()}")
if 'rank_volsurge' in df.columns:
    print(f"Rank_VolSurge = 1.0: {(df['rank_volsurge'] == 1.0).sum()}")
