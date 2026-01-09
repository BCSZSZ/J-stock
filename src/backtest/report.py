"""
Backtest Reporting
Utilities for comparing strategies and generating reports.
"""
import pandas as pd
from typing import List
from src.backtest.models import BacktestResult


def create_comparison_table(results: List[BacktestResult]) -> pd.DataFrame:
    """
    Create formatted comparison table from backtest results.
    
    Args:
        results: List of BacktestResult objects
        
    Returns:
        DataFrame with formatted comparison
    """
    data = []
    
    for r in results:
        row = {
            'Ticker': r.ticker,
            'Name': r.ticker_name[:20],  # Truncate long names
            'Strategy': f"{r.scorer_name}+{r.exiter_name}",
            'Return%': f"{r.total_return_pct:+.2f}",
            'Annual%': f"{r.annualized_return_pct:+.2f}",
            'Sharpe': f"{r.sharpe_ratio:.2f}",
            'MaxDD%': f"{r.max_drawdown_pct:.2f}",
            'Trades': r.num_trades,
            'WinRate%': f"{r.win_rate_pct:.1f}",
            'AvgGain%': f"{r.avg_gain_pct:+.2f}",
            'AvgLoss%': f"{r.avg_loss_pct:+.2f}",
            'ProfitFactor': f"{r.profit_factor:.2f}",
        }
        
        if r.benchmark_return_pct is not None:
            row['TOPIX%'] = f"{r.benchmark_return_pct:+.2f}"
            row['Alpha%'] = f"{r.alpha:+.2f}"
            row['Beat?'] = '✅' if r.beat_benchmark else '❌'
        
        data.append(row)
    
    return pd.DataFrame(data)


def find_best_strategy(results: List[BacktestResult], metric: str = 'sharpe_ratio') -> BacktestResult:
    """
    Find best performing strategy by specified metric.
    
    Args:
        results: List of BacktestResult objects
        metric: Metric to optimize ('sharpe_ratio', 'total_return_pct', 'alpha', etc.)
        
    Returns:
        Best BacktestResult
    """
    return max(results, key=lambda r: getattr(r, metric, 0))


def aggregate_by_strategy(results: List[BacktestResult]) -> pd.DataFrame:
    """
    Aggregate results by strategy across all tickers.
    
    Args:
        results: List of BacktestResult objects
        
    Returns:
        DataFrame with strategy-level aggregates
    """
    df = pd.DataFrame([r.to_dict() for r in results])
    
    # Group by strategy
    df['strategy_key'] = df['scorer_name'] + ' + ' + df['exiter_name']
    
    agg_functions = {
        'total_return_pct': 'mean',
        'annualized_return_pct': 'mean',
        'sharpe_ratio': 'mean',
        'max_drawdown_pct': 'mean',
        'num_trades': 'sum',
        'win_rate_pct': 'mean',
        'profit_factor': 'mean'
    }
    
    if 'alpha' in df.columns:
        agg_functions['alpha'] = 'mean'
        agg_functions['beat_benchmark'] = lambda x: f"{sum(x)}/{len(x)}"
    
    aggregated = df.groupby('strategy_key').agg(agg_functions).round(2)
    
    # Sort by Sharpe ratio
    aggregated = aggregated.sort_values('sharpe_ratio', ascending=False)
    
    return aggregated


def print_summary_report(results: List[BacktestResult]) -> None:
    """
    Print comprehensive summary report.
    
    Args:
        results: List of BacktestResult objects
    """
    print("\n" + "="*80)
    print("BACKTEST SUMMARY REPORT")
    print("="*80)
    
    # Overall statistics
    print(f"\nTotal backtests run: {len(results)}")
    print(f"Date range: {results[0].start_date} to {results[0].end_date}")
    print(f"Starting capital: ¥{results[0].starting_capital_jpy:,.0f}")
    
    # Best performers
    print("\n" + "-"*80)
    print("TOP PERFORMERS")
    print("-"*80)
    
    best_return = find_best_strategy(results, 'total_return_pct')
    print(f"\n🏆 Best Return: {best_return.ticker} × {best_return.scorer_name}+{best_return.exiter_name}")
    print(f"   Return: {best_return.total_return_pct:+.2f}% | Sharpe: {best_return.sharpe_ratio:.2f}")
    
    best_sharpe = find_best_strategy(results, 'sharpe_ratio')
    print(f"\n📈 Best Sharpe: {best_sharpe.ticker} × {best_sharpe.scorer_name}+{best_sharpe.exiter_name}")
    print(f"   Sharpe: {best_sharpe.sharpe_ratio:.2f} | Return: {best_sharpe.total_return_pct:+.2f}%")
    
    if results[0].alpha is not None:
        best_alpha = find_best_strategy(results, 'alpha')
        print(f"\n🎯 Best Alpha: {best_alpha.ticker} × {best_alpha.scorer_name}+{best_alpha.exiter_name}")
        print(f"   Alpha: {best_alpha.alpha:+.2f}% | Return: {best_alpha.total_return_pct:+.2f}%")
    
    # Strategy aggregates
    print("\n" + "-"*80)
    print("STRATEGY AGGREGATES (averaged across all tickers)")
    print("-"*80)
    print(aggregate_by_strategy(results).to_string())
    
    # Detailed comparison table
    print("\n" + "-"*80)
    print("DETAILED RESULTS")
    print("-"*80)
    print(create_comparison_table(results).to_string(index=False))
    
    print("\n" + "="*80 + "\n")
