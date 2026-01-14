"""
J-Stock-Analyzer - 统一CLI入口
提供3个核心功能：数据抓取、策略信号生成、回测分析
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime


def load_config() -> dict:
    """加载配置文件"""
    config_path = Path('config.json')
    if not config_path.exists():
        print("❌ 错误: config.json 不存在")
        sys.exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_monitor_list(config: dict) -> list:
    """从monitor_list.txt加载股票代码列表"""
    list_file = Path(config['data']['monitor_list_file'])
    
    if not list_file.exists():
        print(f"❌ 错误: 监视列表文件不存在 {list_file}")
        sys.exit(1)
    
    tickers = []
    with open(list_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # 跳过空行和注释
            if line and not line.startswith('#'):
                tickers.append(line)
    
    return tickers


def cmd_fetch(args):
    """数据抓取命令"""
    from src.data_fetch_manager import main as fetch_main, load_monitor_list as fetch_load_list
    
    config = load_config()
    
    if args.all:
        print("📥 抓取监视列表中的所有股票数据...")
        fetch_main()
    elif args.tickers:
        print(f"📥 抓取指定股票数据: {', '.join(args.tickers)}")
        # 临时覆盖monitor list
        import os
        from src.data.pipeline import StockETLPipeline
        from src.data.benchmark_manager import update_benchmarks
        from src.client.jquants_client import JQuantsV2Client
        from dotenv import load_dotenv
        
        load_dotenv()
        api_key = os.getenv('JQUANTS_API_KEY')
        
        if not api_key:
            print("❌ 错误: 未找到 JQUANTS_API_KEY")
            return
        
        # 更新TOPIX基准
        client = JQuantsV2Client(api_key)
        benchmark_result = update_benchmarks(client)
        
        if benchmark_result['success']:
            print(f"✅ TOPIX已更新: {benchmark_result['topix_records']} 条记录")
        
        # 抓取指定股票
        pipeline = StockETLPipeline(api_key)
        summary = pipeline.run_batch(args.tickers, fetch_aux_data=True)
        
        print(f"\n✅ 数据抓取完成: {summary['successful']}/{summary['total']} 只股票成功")
    else:
        print("❌ 错误: 请指定 --all 或 --tickers")


def cmd_signal(args):
    """策略信号生成命令"""
    from src.signal_generator import generate_trading_signal
    
    config = load_config()
    
    # 使用指定日期或今天
    target_date = args.date if args.date else datetime.now().strftime('%Y-%m-%d')
    
    entry_strategy = args.entry or config['default_strategies']['entry']
    exit_strategy = args.exit or config['default_strategies']['exit']
    
    print(f"\n🎯 生成交易信号")
    print(f"   股票代码: {args.ticker}")
    print(f"   日期: {target_date}")
    print(f"   入场策略: {entry_strategy}")
    print(f"   出场策略: {exit_strategy}")
    print("="*60)
    
    signal = generate_trading_signal(
        ticker=args.ticker,
        date=target_date,
        entry_strategy=entry_strategy,
        exit_strategy=exit_strategy
    )
    
    if signal:
        print(f"\n✅ 信号生成成功")
        print(f"   动作: {signal['action']}")
        print(f"   置信度: {signal.get('confidence', 'N/A')}")
        if signal.get('reason'):
            print(f"   原因: {signal['reason']}")
    else:
        print(f"\n⚠️ 无交易信号")


def cmd_backtest(args):
    """单股票回测命令"""
    config = load_config()
    
    entry_strategy = args.entry or config['default_strategies']['entry']
    exit_strategy = args.exit or config['default_strategies']['exit']
    start_date = args.start or config['backtest']['start_date']
    end_date = args.end or config['backtest']['end_date']
    capital = args.capital or config['backtest']['starting_capital_jpy']
    
    print(f"\n📊 单股票回测")
    print(f"   股票代码: {args.ticker}")
    print(f"   时间范围: {start_date} → {end_date}")
    print(f"   起始资金: ¥{capital:,}")
    print(f"   入场策略: {entry_strategy}")
    print(f"   出场策略: {exit_strategy}")
    print("="*60)
    
    from src.backtest.engine import BacktestEngine, backtest_strategy
    from src.data.stock_data_manager import StockDataManager
    
    # 加载数据
    data_manager = StockDataManager()
    stock_data = data_manager.load_stock_features(args.ticker)
    
    if stock_data is None or stock_data.empty:
        print(f"❌ 错误: 无法加载股票数据 {args.ticker}")
        return
    
    # 过滤日期范围
    stock_data = stock_data[
        (stock_data['date'] >= start_date) & 
        (stock_data['date'] <= end_date)
    ]
    
    if stock_data.empty:
        print(f"❌ 错误: 指定日期范围内无数据")
        return
    
    # 执行回测
    result = backtest_strategy(
        ticker=args.ticker,
        stock_data=stock_data,
        entry_strategy_name=entry_strategy,
        exit_strategy_name=exit_strategy,
        starting_capital=capital
    )
    
    # 显示结果
    print(f"\n📈 回测结果")
    print(f"   最终资金: ¥{result.final_capital:,.0f}")
    print(f"   总收益率: {result.total_return_pct:.2f}%")
    print(f"   交易次数: {result.total_trades}")
    print(f"   胜率: {result.win_rate*100:.1f}%")
    print(f"   最大回撤: {result.max_drawdown*100:.2f}%")
    if result.sharpe_ratio:
        print(f"   夏普比率: {result.sharpe_ratio:.2f}")
    
    print(f"\n   买入持有收益: {result.buy_hold_return_pct:.2f}%")
    print(f"   择时Alpha: {result.timing_alpha:.2f}%")
    
    if result.benchmark_return_pct:
        print(f"   TOPIX收益: {result.benchmark_return_pct:.2f}%")
        print(f"   选股Alpha: {result.stock_selection_alpha:.2f}%")


def cmd_portfolio(args):
    """组合投资回测命令"""
    config = load_config()
    
    # 确定要回测的股票列表
    if args.all:
        tickers = load_monitor_list(config)
        print(f"📊 组合投资回测 - 监视列表所有股票 ({len(tickers)}只)")
    elif args.tickers:
        tickers = args.tickers
        print(f"📊 组合投资回测 - 指定股票 ({len(tickers)}只)")
    else:
        print("❌ 错误: 请指定 --all 或 --tickers")
        return
    
    entry_strategy = args.entry or config['default_strategies']['entry']
    exit_strategy = args.exit or config['default_strategies']['exit']
    start_date = args.start or config['backtest']['start_date']
    end_date = args.end or config['backtest']['end_date']
    capital = args.capital or config['backtest']['starting_capital_jpy']
    
    print(f"   股票代码: {', '.join(tickers[:5])}{'...' if len(tickers) > 5 else ''}")
    print(f"   时间范围: {start_date} → {end_date}")
    print(f"   起始资金: ¥{capital:,}")
    print(f"   最大持仓: {config['portfolio']['max_positions']}只")
    print(f"   入场策略: {entry_strategy}")
    print(f"   出场策略: {exit_strategy}")
    print("="*60)
    
    from src.backtest.portfolio_engine import PortfolioBacktestEngine
    from src.data.stock_data_manager import StockDataManager
    
    # 加载所有股票数据
    data_manager = StockDataManager()
    all_data = {}
    
    for ticker in tickers:
        stock_data = data_manager.load_stock_features(ticker)
        if stock_data is not None and not stock_data.empty:
            # 过滤日期
            stock_data = stock_data[
                (stock_data['date'] >= start_date) & 
                (stock_data['date'] <= end_date)
            ]
            if not stock_data.empty:
                all_data[ticker] = stock_data
    
    print(f"\n✅ 成功加载 {len(all_data)}/{len(tickers)} 只股票数据")
    
    if len(all_data) == 0:
        print("❌ 错误: 无可用数据")
        return
    
    # 执行组合回测
    engine = PortfolioBacktestEngine(
        starting_capital=capital,
        max_positions=config['portfolio']['max_positions'],
        lot_sizes=config['lot_sizes']
    )
    
    result = engine.run(
        all_stock_data=all_data,
        entry_strategy_name=entry_strategy,
        exit_strategy_name=exit_strategy
    )
    
    # 显示结果
    print(f"\n📈 组合回测结果")
    print(f"   最终资金: ¥{result.final_capital:,.0f}")
    print(f"   总收益率: {result.total_return_pct:.2f}%")
    print(f"   交易次数: {result.total_trades}")
    print(f"   胜率: {result.win_rate*100:.1f}%")
    print(f"   最大回撤: {result.max_drawdown*100:.2f}%")
    if result.sharpe_ratio:
        print(f"   夏普比率: {result.sharpe_ratio:.2f}")
    
    if result.benchmark_return_pct:
        print(f"\n   TOPIX收益: {result.benchmark_return_pct:.2f}%")
        print(f"   超额收益: {result.total_return_pct - result.benchmark_return_pct:.2f}%")


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(
        description='J-Stock-Analyzer - 日本股票量化分析工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 数据抓取
  python main.py fetch --all                    # 抓取监视列表所有股票
  python main.py fetch --tickers 7974 8035      # 抓取指定股票
  
  # 生成交易信号
  python main.py signal 7974                    # 生成今日信号
  python main.py signal 7974 --date 2026-01-10  # 指定日期
  
  # 单股票回测
  python main.py backtest 7974                  # 使用默认参数
  python main.py backtest 7974 --entry EnhancedScorerStrategy --exit LayeredExitStrategy
  
  # 组合投资回测
  python main.py portfolio --all                # 回测监视列表所有股票
  python main.py portfolio --tickers 7974 8035 6501
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # ========== 数据抓取命令 ==========
    fetch_parser = subparsers.add_parser('fetch', help='抓取股票数据')
    fetch_group = fetch_parser.add_mutually_exclusive_group(required=True)
    fetch_group.add_argument('--all', action='store_true', help='抓取监视列表中的所有股票')
    fetch_group.add_argument('--tickers', nargs='+', help='指定股票代码列表')
    
    # ========== 策略信号命令 ==========
    signal_parser = subparsers.add_parser('signal', help='生成交易信号')
    signal_parser.add_argument('ticker', help='股票代码')
    signal_parser.add_argument('--date', help='指定日期 (格式: YYYY-MM-DD, 默认今天)')
    signal_parser.add_argument('--entry', help='入场策略 (默认: SimpleScorerStrategy)')
    signal_parser.add_argument('--exit', help='出场策略 (默认: ATRExitStrategy)')
    
    # ========== 单股票回测命令 ==========
    backtest_parser = subparsers.add_parser('backtest', help='单股票回测')
    backtest_parser.add_argument('ticker', help='股票代码')
    backtest_parser.add_argument('--entry', help='入场策略 (默认: SimpleScorerStrategy)')
    backtest_parser.add_argument('--exit', help='出场策略 (默认: ATRExitStrategy)')
    backtest_parser.add_argument('--start', help='开始日期 (默认: 2021-01-01)')
    backtest_parser.add_argument('--end', help='结束日期 (默认: 2026-01-08)')
    backtest_parser.add_argument('--capital', type=int, help='起始资金 (默认: 5000000)')
    
    # ========== 组合投资回测命令 ==========
    portfolio_parser = subparsers.add_parser('portfolio', help='组合投资回测')
    portfolio_group = portfolio_parser.add_mutually_exclusive_group(required=True)
    portfolio_group.add_argument('--all', action='store_true', help='使用监视列表所有股票')
    portfolio_group.add_argument('--tickers', nargs='+', help='指定股票代码列表')
    portfolio_parser.add_argument('--entry', help='入场策略 (默认: SimpleScorerStrategy)')
    portfolio_parser.add_argument('--exit', help='出场策略 (默认: ATRExitStrategy)')
    portfolio_parser.add_argument('--start', help='开始日期 (默认: 2021-01-01)')
    portfolio_parser.add_argument('--end', help='结束日期 (默认: 2026-01-08)')
    portfolio_parser.add_argument('--capital', type=int, help='起始资金 (默认: 5000000)')
    
    # 解析参数
    args = parser.parse_args()
    
    # 执行对应命令
    if args.command == 'fetch':
        cmd_fetch(args)
    elif args.command == 'signal':
        cmd_signal(args)
    elif args.command == 'backtest':
        cmd_backtest(args)
    elif args.command == 'portfolio':
        cmd_portfolio(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
