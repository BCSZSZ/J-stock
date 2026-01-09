"""
快速回测工具 - 无需修改配置文件
Quick backtest without editing config files.

使用方法 / Usage:
    # 单个策略组合
    python quick_backtest.py simple atr
    
    # 多个策略组合
    python quick_backtest.py simple atr macd atr enhanced layered
    
    # 指定股票和日期
    python quick_backtest.py simple atr --ticker 7203 --start 2023-01-01
    
    # 查看所有可用策略
    python quick_backtest.py --list

可用策略简称 / Available shortcuts:
    Entry:  simple, enhanced, macd
    Exit:   atr, score, layered
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.backtest.engine import backtest_strategies
from src.backtest.report import print_summary_report

# 策略名称映射
ENTRY_MAP = {
    'simple': 'SimpleScorerStrategy',
    'enhanced': 'EnhancedScorerStrategy', 
    'macd': 'MACDCrossoverStrategy'
}

EXIT_MAP = {
    'atr': 'ATRExitStrategy',
    'score': 'ScoreBasedExitStrategy',
    'layered': 'LayeredExitStrategy'
}

def list_strategies():
    """显示所有可用策略"""
    print("\n" + "="*70)
    print("可用策略 / Available Strategies")
    print("="*70)
    print("\n📥 Entry Strategies:")
    for short, full in ENTRY_MAP.items():
        print(f"  {short:10} → {full}")
    
    print("\n📤 Exit Strategies:")
    for short, full in EXIT_MAP.items():
        print(f"  {short:10} → {full}")
    
    print("\n💡 Usage Examples:")
    print("  python quick_backtest.py simple atr")
    print("  python quick_backtest.py enhanced layered --ticker 6501")
    print("  python quick_backtest.py simple atr macd layered")
    print("="*70 + "\n")

def parse_strategies(args):
    """解析策略参数"""
    strategies = []
    i = 0
    while i < len(args):
        if args[i].startswith('--'):
            break
        
        if i + 1 >= len(args) or args[i+1].startswith('--'):
            print(f"❌ 错误: {args[i]} 后需要指定exit策略")
            sys.exit(1)
        
        entry_short = args[i].lower()
        exit_short = args[i+1].lower()
        
        if entry_short not in ENTRY_MAP:
            print(f"❌ 未知entry策略: {entry_short}")
            print(f"   可用: {', '.join(ENTRY_MAP.keys())}")
            sys.exit(1)
        
        if exit_short not in EXIT_MAP:
            print(f"❌ 未知exit策略: {exit_short}")
            print(f"   可用: {', '.join(EXIT_MAP.keys())}")
            sys.exit(1)
        
        strategies.append({
            'entry': ENTRY_MAP[entry_short],
            'exit': EXIT_MAP[exit_short]
        })
        
        i += 2
    
    return strategies

def main():
    parser = argparse.ArgumentParser(
        description='快速回测工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('strategies', nargs='*', help='策略组合 (entry exit [entry exit ...])')
    parser.add_argument('--list', '-l', action='store_true', help='列出所有可用策略')
    parser.add_argument('--ticker', '-t', default='7203', help='股票代码 (默认: 7203)')
    parser.add_argument('--start', '-s', default='2021-01-01', help='开始日期 (默认: 2021-01-01)')
    parser.add_argument('--end', '-e', default='2026-01-08', help='结束日期 (默认: 2026-01-08)')
    parser.add_argument('--capital', '-c', type=int, default=5000000, help='初始资金 (默认: 5000000)')
    
    args = parser.parse_args()
    
    if args.list:
        list_strategies()
        return
    
    if not args.strategies:
        print("❌ 请指定策略组合，或使用 --list 查看可用策略")
        print("示例: python quick_backtest.py simple atr")
        sys.exit(1)
    
    strategies = parse_strategies(args.strategies)
    
    print("\n" + "="*70)
    print("快速回测")
    print("="*70)
    print(f"股票代码: {args.ticker}")
    print(f"回测期间: {args.start} 至 {args.end}")
    print(f"起始资金: ¥{args.capital:,}")
    print(f"策略组合: {len(strategies)} 个")
    for i, s in enumerate(strategies, 1):
        print(f"  {i}. {s['entry'].replace('Strategy', '')} + {s['exit'].replace('Strategy', '')}")
    print("="*70 + "\n")
    
    # 构建配置
    config = {
        'backtest_config': {
            'tickers': [args.ticker],
            'start_date': args.start,
            'end_date': args.end,
            'starting_capital_jpy': args.capital,
            'include_benchmark': True,
            'strategies': strategies
        }
    }
    
    # 运行回测
    from start_backtest import run_backtest_from_config
    run_backtest_from_config(config)

if __name__ == "__main__":
    main()
