"""
Data Lake Schema Reference Generator
Generates comprehensive column documentation for all data layers.
"""
import pandas as pd
import json
from pathlib import Path

print("=" * 80)
print("DATA LAKE SCHEMA REFERENCE - J-Stock-Analyzer")
print("=" * 80)

# 1. RAW PRICES
print("\n🟢 1. RAW_PRICES (Daily OHLCV)")
print("-" * 80)
df_prices = pd.read_parquet('data/raw_prices/8035.parquet')
print(f"Total Columns: {len(df_prices.columns)}")
print(f"Total Rows: {len(df_prices)}")
print(f"\nColumns: {list(df_prices.columns)}")
print("\nData Types:")
print(df_prices.dtypes)
print("\nSample Data (first row):")
print(df_prices.head(1))

# 2. FEATURES
print("\n" + "=" * 80)
print("🟣 2. FEATURES (Daily with Technical Indicators)")
print("-" * 80)
df_features = pd.read_parquet('data/features/8035_features.parquet')
print(f"Total Columns: {len(df_features.columns)}")
print(f"Total Rows: {len(df_features)}")
print(f"\nAll Columns:")
for i, col in enumerate(df_features.columns, 1):
    print(f"  {i:2d}. {col}")

print("\n📊 Column Groups:")
print("  OHLCV Base:  Date, Open, High, Low, Close, Volume")
print("  Trend:       EMA_20, EMA_50, EMA_200")
print("  Momentum:    RSI, MACD, MACD_Signal, MACD_Hist")
print("  Volatility:  ATR")
print("  Volume:      Volume_SMA_20")

print("\nLatest Values:")
latest = df_features.tail(1)
print(f"  Date:        {latest['Date'].values[0]}")
print(f"  Close:       ¥{latest['Close'].values[0]:,.0f}")
print(f"  EMA_20:      ¥{latest['EMA_20'].values[0]:,.2f}")
print(f"  RSI:         {latest['RSI'].values[0]:.2f}")
print(f"  MACD:        {latest['MACD'].values[0]:,.2f}")

# 3. RAW TRADES
print("\n" + "=" * 80)
print("🔵 3. RAW_TRADES (Weekly Investor Flows)")
print("-" * 80)
df_trades = pd.read_parquet('data/raw_trades/8035_trades.parquet')
print(f"Total Columns: {len(df_trades.columns)}")
print(f"Total Rows: {len(df_trades)}")
print(f"\nAll {len(df_trades.columns)} Columns:")
for i, col in enumerate(df_trades.columns, 1):
    print(f"  {i:2d}. {col}")

print("\n📊 Key Column Groups:")
print("  📅 Dates:")
print("     - PubDate:   Publication date")
print("     - StDate:    Week start date")
print("     - EnDate:    Week end date")
print("\n  🏢 Proprietary Trading (Banks/Securities):")
print("     - PropBuy, PropSell, PropTot, PropBal")
print("\n  🌍 Foreign Investors (THE WHALES):")
print("     - ForBuy, ForSell, ForTot, ForBal")
print("\n  👤 Individual/Retail Investors:")
print("     - IndBuy, IndSell, IndTot, IndBal")
print("\n  🏭 Other Corporations:")
print("     - OthCorBuy, OthCorSell, OthCorTot, OthCorBal")
print("\n  💼 Other Financial Institutions:")
print("     - OthFinBuy, OthFinSell, OthFinTot, OthFinBal")

# 4. RAW FINANCIALS
print("\n" + "=" * 80)
print("🟡 4. RAW_FINANCIALS (Quarterly Earnings)")
print("-" * 80)
df_fin = pd.read_parquet('data/raw_financials/8035_financials.parquet')
print(f"Total Columns: {len(df_fin.columns)}")
print(f"Total Rows: {len(df_fin)}")
print(f"\nAll {len(df_fin.columns)} Columns:")
for i, col in enumerate(df_fin.columns, 1):
    print(f"  {i:2d}. {col}")

print("\n📊 Key Column Groups:")
print("  📅 Metadata:")
print("     - DiscDate, DiscTime, Code, DiscNo")
print("\n  💰 Core Financials:")
print("     - Sales, OperatingProfit, OrdinaryProfit, Profit")
print("     - TotalAssets, NetAssets, CashFlows")
print("\n  📈 Per-Share Metrics:")
print("     - EPS (Earnings Per Share)")
print("     - BPS (Book Value Per Share)")
print("     - DPS (Dividend Per Share)")
print("\n  🔮 Forecasts (Next Quarter):")
print("     - NxFNCSales, NxFNCOP, NxFNCNP, NxFNCEPS")

# 5. METADATA
print("\n" + "=" * 80)
print("📋 5. METADATA (Event Calendar & Reports)")
print("-" * 80)
meta_path = Path('data/metadata/8035_metadata.json')
with open(meta_path, 'r', encoding='utf-8') as f:
    metadata = json.load(f)

print(f"File: {meta_path.name}")
print(f"\nStructure:")
print(json.dumps(metadata, indent=2, ensure_ascii=False)[:500] + "...")

print("\n" + "=" * 80)
print("QUICK REFERENCE SUMMARY")
print("=" * 80)
print(f"""
📊 Data Frequency:
  - raw_prices:      DAILY    (~1,222 rows per stock)
  - features:        DAILY    (~1,222 rows per stock)
  - raw_trades:      WEEKLY   (~48 rows per stock)
  - raw_financials:  QUARTERLY (~20 rows per stock)
  - metadata:        EVENT-BASED (JSON)

🔍 Research Tips:
  1. Use raw_prices for price action analysis
  2. Use features for technical trading signals
  3. Use raw_trades to track "smart money" (foreign investors)
  4. Use raw_financials for fundamental analysis
  5. Use metadata for earnings date risk management

📚 Column Naming Convention:
  - Buy/Sell/Tot/Bal = Buy Volume / Sell Volume / Total / Balance
  - For/Prop/Ind/OthCor/OthFin = Foreign / Proprietary / Individual / Corporate / Financial
  - NxFNC* = Next Forecast (company guidance)
  - EPS/BPS/DPS = Earnings/Book/Dividend Per Share
""")

print("=" * 80)
print("Schema generation complete! Save this output for reference.")
print("=" * 80)
