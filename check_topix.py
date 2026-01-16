import pandas as pd
df = pd.read_parquet('data/benchmarks/topix_daily.parquet')
print(f'Total records: {len(df)}')
print(f'Date range: {df["Date"].min()} to {df["Date"].max()}')
print(f'2024-01 data:', len(df[(df['Date'] >= '2024-01-01') & (df['Date'] <= '2024-01-31')]), 'records')
print(f'2021-01 data:', len(df[(df['Date'] >= '2021-01-01') & (df['Date'] <= '2021-01-31')]), 'records')
