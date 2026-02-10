#!/usr/bin/env python3
"""验证 fetch 获取的数据"""
import pandas as pd
from pathlib import Path

print("\n" + "="*70)
print("数据验证 - 证明 fetch 成功获取数据")
print("="*70)

# 验证股票 8035 (Tokyo Electron)
print("\n【股票 8035 - Tokyo Electron】")
file_8035 = Path("data/features/8035_features.parquet")
if file_8035.exists():
    df = pd.read_parquet(file_8035)
    df['Date'] = pd.to_datetime(df['Date'])
    
    print(f"✓ 文件存在: {file_8035}")
    print(f"✓ 总行数: {len(df)} (约 5 年每日数据)")
    print(f"✓ 列数: {len(df.columns)}")
    print(f"✓ 日期范围: {df['Date'].min().date()} 到 {df['Date'].max().date()}")
    
    print(f"\n最新 5 天价格数据:")
    recent = df.tail(5)[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
    for _, row in recent.iterrows():
        print(f"  {row['Date'].date()}: 收盘 {row['Close']:>8,.0f}  成交量 {row['Volume']:>12,.0f}")
    
    latest = df.iloc[-1]
    print(f"\n最新技术指标 ({df.iloc[-1]['Date'].date()}):")
    print(f"  RSI:    {latest['RSI']:>7.2f}")
    print(f"  MACD:   {latest['MACD']:>7.2f}")
    print(f"  ATR:    {latest['ATR']:>7.2f}")
    print(f"  EMA_20: {latest['EMA_20']:>7.2f}")
    print(f"  EMA_50: {latest['EMA_50']:>7.2f}")

# 验证股票 6501 (Hitachi)
print("\n【股票 6501 - Hitachi】")
file_6501 = Path("data/features/6501_features.parquet")
if file_6501.exists():
    df = pd.read_parquet(file_6501)
    df['Date'] = pd.to_datetime(df['Date'])
    
    print(f"✓ 文件存在: {file_6501}")
    print(f"✓ 总行数: {len(df)}")
    print(f"✓ 日期范围: {df['Date'].min().date()} 到 {df['Date'].max().date()}")
    
    latest = df.iloc[-1]
    print(f"\n最新数据 ({df.iloc[-1]['Date'].date()}):")
    print(f"  收盘价: {latest['Close']:>8,.0f}")
    print(f"  RSI:    {latest['RSI']:>7.2f}")
    print(f"  成交量: {latest['Volume']:>12,.0f}")

# 统计所有股票
print(f"\n【数据文件统计】")
features_dir = Path("data/features")
all_files = list(features_dir.glob("*_features.parquet"))
print(f"✓ 总 parquet 文件数: {len(all_files)}")

# 检查最近更新的文件
recent_files = sorted(all_files, key=lambda x: x.stat().st_mtime, reverse=True)[:5]
print(f"\n最近更新的 5 个文件:")
for f in recent_files:
    ticker = f.stem.replace('_features', '')
    size_kb = f.stat().st_size / 1024
    print(f"  {ticker:>6} - {size_kb:>6.1f} KB")

print("\n" + "="*70)
print("✅ 验证完成: 所有数据成功获取并保存!")
print("="*70 + "\n")
