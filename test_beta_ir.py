"""Test Beta and Information Ratio implementation."""

from src.backtest.engine import backtest_strategies
from src.analysis.scorers.simple_scorer import SimpleScorer
from src.analysis.exiters.atr_exiter import ATRExiter

if __name__ == "__main__":
    print("Testing Beta & Information Ratio Implementation...")
    print("=" * 70)
    
    # Run backtest with benchmark enabled
    results = backtest_strategies(
        tickers=['7203'],  # Toyota
        strategies=[(SimpleScorer(), ATRExiter())],
        start_date='2023-01-01',
        end_date='2025-12-31',
        include_benchmark=True  # Enable TOPIX comparison
    )
    
    print("\n回测结果:")
    print(results.to_string())
    
    # Check if Beta/IR metrics are present
    print("\n\n详细指标检查:")
    print("-" * 70)
    for col in ['beta', 'tracking_error', 'information_ratio']:
        if col in results.columns:
            value = results.iloc[0][col]
            print(f"✅ {col}: {value}")
        else:
            print(f"❌ {col}: MISSING")
