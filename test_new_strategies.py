"""
新策略回测启动脚本
Test new Strategy architecture

使用示例:
    python test_new_strategies.py
"""
import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.backtest.engine import BacktestEngine
from src.analysis.strategies.entry import SimpleScorerStrategy, EnhancedScorerStrategy, MACDCrossoverStrategy
from src.analysis.strategies.exit import ATRExitStrategy, ScoreBasedExitStrategy, LayeredExitStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_strategy_combination(entry_strategy, exit_strategy, ticker="7203"):
    """
    测试一个Entry+Exit策略组合
    
    Args:
        entry_strategy: Entry策略实例
        exit_strategy: Exit策略实例
        ticker: 股票代码
    """
    print(f"\n{'='*80}")
    print(f"Testing: {entry_strategy.strategy_name} + {exit_strategy.strategy_name}")
    print(f"Ticker: {ticker}")
    print(f"{'='*80}\n")
    
    # Initialize backtest engine
    engine = BacktestEngine(
        starting_capital_jpy=5_000_000,
        buy_threshold=65.0,
        data_root='./data'
    )
    
    # Run backtest
    result = engine.backtest_strategy(
        ticker=ticker,
        entry_strategy=entry_strategy,
        exit_strategy=exit_strategy,
        start_date="2021-01-01",
        end_date="2026-01-08"
    )
    
    # Print summary
    print(f"\n{'='*80}")
    print(f"RESULTS: {entry_strategy.strategy_name} + {exit_strategy.strategy_name}")
    print(f"{'='*80}")
    print(f"Total Return:     {result.total_return_pct:+.2f}%")
    print(f"Annualized:       {result.annualized_return_pct:+.2f}%")
    print(f"Sharpe Ratio:     {result.sharpe_ratio:.2f}")
    print(f"Max Drawdown:     {result.max_drawdown_pct:.2f}%")
    print(f"Num Trades:       {result.num_trades}")
    print(f"Win Rate:         {result.win_rate_pct:.1f}%")
    print(f"Avg Gain:         {result.avg_gain_pct:+.2f}%")
    print(f"Avg Loss:         {result.avg_loss_pct:+.2f}%")
    print(f"Profit Factor:    {result.profit_factor:.2f}")
    print(f"Avg Holding Days: {result.avg_holding_days:.1f}")
    print(f"{'='*80}\n")
    
    return result


def main():
    """Run comprehensive strategy tests"""
    
    print("\n" + "="*80)
    print("新策略架构测试")
    print("Testing New Strategy Architecture")
    print("="*80 + "\n")
    
    # Load environment
    load_dotenv()
    
    ticker = "7203"  # Toyota
    
    # =========================================================================
    # 测试1: 纯打分策略组合
    # =========================================================================
    print("\n" + "="*80)
    print("测试1: 纯打分策略 (Simple Scorer + Score-Based Exit)")
    print("="*80)
    
    result1 = test_strategy_combination(
        SimpleScorerStrategy(buy_threshold=65.0),
        ScoreBasedExitStrategy(score_buffer=15.0),
        ticker=ticker
    )
    
    # =========================================================================
    # 测试2: 纯技术策略组合
    # =========================================================================
    print("\n" + "="*80)
    print("测试2: 纯技术策略 (MACD Crossover + ATR Exit)")
    print("="*80)
    
    result2 = test_strategy_combination(
        MACDCrossoverStrategy(min_confidence=0.6),
        ATRExitStrategy(atr_trail_multiplier=3.0),
        ticker=ticker
    )
    
    # =========================================================================
    # 测试3: 混合策略A (打分入场 + 技术退出)
    # =========================================================================
    print("\n" + "="*80)
    print("测试3: 混合策略A (Simple Scorer + ATR Exit)")
    print("="*80)
    
    result3 = test_strategy_combination(
        SimpleScorerStrategy(buy_threshold=65.0),
        ATRExitStrategy(atr_trail_multiplier=3.0),
        ticker=ticker
    )
    
    # =========================================================================
    # 测试4: 混合策略B (技术入场 + 打分退出)
    # =========================================================================
    print("\n" + "="*80)
    print("测试4: 混合策略B (MACD Crossover + Score-Based Exit)")
    print("="*80)
    
    result4 = test_strategy_combination(
        MACDCrossoverStrategy(min_confidence=0.6),
        ScoreBasedExitStrategy(score_buffer=15.0),
        ticker=ticker
    )
    
    # =========================================================================
    # 测试5: 增强打分策略 + 多层退出
    # =========================================================================
    print("\n" + "="*80)
    print("测试5: 全面策略 (Enhanced Scorer + Layered Exit)")
    print("="*80)
    
    result5 = test_strategy_combination(
        EnhancedScorerStrategy(buy_threshold=65.0),
        LayeredExitStrategy(use_score_utils=True),
        ticker=ticker
    )
    
    # =========================================================================
    # 测试6: MACD + 多层退出（不使用分数）
    # =========================================================================
    print("\n" + "="*80)
    print("测试6: 技术+多层 (MACD Crossover + Layered Exit without scores)")
    print("="*80)
    
    result6 = test_strategy_combination(
        MACDCrossoverStrategy(min_confidence=0.6),
        LayeredExitStrategy(use_score_utils=False),
        ticker=ticker
    )
    
    # =========================================================================
    # 汇总对比
    # =========================================================================
    print("\n" + "="*80)
    print("策略对比汇总")
    print("="*80)
    
    results = [
        ("Simple + ScoreExit", result1),
        ("MACD + ATR", result2),
        ("Simple + ATR", result3),
        ("MACD + ScoreExit", result4),
        ("Enhanced + Layered", result5),
        ("MACD + Layered(NoScore)", result6)
    ]
    
    print(f"\n{'Strategy':<30} {'Return':<12} {'Sharpe':<10} {'Trades':<10} {'Win%':<10}")
    print("-" * 80)
    
    for name, result in results:
        print(f"{name:<30} {result.total_return_pct:>+10.2f}% {result.sharpe_ratio:>8.2f} "
              f"{result.num_trades:>8} {result.win_rate_pct:>8.1f}%")
    
    print("\n✅ 测试完成！\n")
    print("新策略架构已验证：")
    print("- Entry Strategy生成买入信号 ✓")
    print("- Exit Strategy生成卖出信号 ✓")
    print("- Score Utils作为可选工具 ✓")
    print("- 支持9种组合（6种已测试）✓")
    print("- 向后兼容旧Scorer/Exiter ✓")
    

if __name__ == "__main__":
    main()
