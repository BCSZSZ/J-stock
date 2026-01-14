"""
检查特定股票在回测期间的得分情况
"""
import pandas as pd
from pathlib import Path
from datetime import datetime

# 配置
ticker = "1231"  # 检查的股票代码
start_date = "2021-01-01"
check_threshold = 65.0  # 买入阈值

# 加载数据
features_path = Path("data/features") / f"{ticker}_features.parquet"
if not features_path.exists():
    print(f"❌ 找不到数据文件: {features_path}")
    exit(1)

df = pd.read_parquet(features_path)
df['Date'] = pd.to_datetime(df['Date'])
df = df[df['Date'] >= start_date].copy()

print(f"\n{'='*80}")
print(f"检查 {ticker} 从 {start_date} 开始的得分情况")
print(f"{'='*80}\n")

# 检查是否有composite_score列
if 'composite_score' in df.columns:
    print("✅ 发现 composite_score 列")
    
    # 统计信息
    total_days = len(df)
    above_threshold = df[df['composite_score'] >= check_threshold]
    
    print(f"\n总交易日数: {total_days}")
    print(f"平均得分: {df['composite_score'].mean():.1f}")
    print(f"最高得分: {df['composite_score'].max():.1f} (日期: {df.loc[df['composite_score'].idxmax(), 'Date'].strftime('%Y-%m-%d')})")
    print(f"最低得分: {df['composite_score'].min():.1f} (日期: {df.loc[df['composite_score'].idxmin(), 'Date'].strftime('%Y-%m-%d')})")
    print(f"\n得分 >= {check_threshold} 的天数: {len(above_threshold)} ({len(above_threshold)/total_days*100:.1f}%)")
    
    if len(above_threshold) > 0:
        print(f"\n首次达到阈值: {above_threshold.iloc[0]['Date'].strftime('%Y-%m-%d')} (得分: {above_threshold.iloc[0]['composite_score']:.1f})")
        print(f"最近达到阈值: {above_threshold.iloc[-1]['Date'].strftime('%Y-%m-%d')} (得分: {above_threshold.iloc[-1]['composite_score']:.1f})")
        
        # 显示前10次达到阈值的日期
        print(f"\n前10次达到买入阈值的日期:")
        print("-" * 80)
        for idx, row in above_threshold.head(10).iterrows():
            print(f"  {row['Date'].strftime('%Y-%m-%d')}: 得分 {row['composite_score']:.1f}, "
                  f"收盘价 ¥{row['Close']:.2f}")
    else:
        print(f"\n⚠️  在整个回测期间从未达到 {check_threshold} 分的买入阈值！")
        
        # 显示最接近阈值的日期
        print(f"\n最接近阈值的10个交易日:")
        print("-" * 80)
        top_scores = df.nlargest(10, 'composite_score')
        for idx, row in top_scores.iterrows():
            print(f"  {row['Date'].strftime('%Y-%m-%d')}: 得分 {row['composite_score']:.1f}, "
                  f"收盘价 ¥{row['Close']:.2f}")
        
else:
    print("❌ 没有找到 composite_score 列")
    print("\n可用的列:")
    print(df.columns.tolist())
    print("\n提示: 可能需要先运行特征工程生成综合得分")

print(f"\n{'='*80}\n")
