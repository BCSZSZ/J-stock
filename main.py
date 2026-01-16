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
    """从monitor_list.json或monitor_list.txt加载股票代码列表"""
    # Try JSON first (new format)
    json_file = Path("data/monitor_list.json")
    if json_file.exists():
        import json
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [stock['code'] for stock in data['tickers']]
    
    # Fallback to TXT (old format)
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
    from src.utils.strategy_loader import (
        get_all_strategy_combinations,
        get_strategy_combinations_from_lists,
        load_entry_strategy,
        load_exit_strategy,
        ENTRY_STRATEGIES,
        EXIT_STRATEGIES
    )
    from src.backtest.engine import backtest_strategy
    from src.backtest.lot_size_manager import LotSizeManager
    from src.data.stock_data_manager import StockDataManager
    from src.utils.output_logger import create_logger
    import pandas as pd
    
    # 加载lot sizes配置
    if 'lot_sizes' in config:
        LotSizeManager.load_from_config(config['lot_sizes'])
    
    # 启动日志输出
    logger = create_logger('backtest', ticker=args.ticker)
    with logger:
        # 确定要测试的策略组合
        if args.all_strategies:
            # 模式1：全部策略组合
            strategy_combinations = get_all_strategy_combinations()
            print(f"\n📊 单股票回测 - 所有策略组合")
            print(f"   股票代码: {args.ticker}")
            print(f"   策略组合数: {len(strategy_combinations)}")
        elif args.entry or args.exit:
            # 模式2：指定策略（支持列表）
            # 如果未指定则使用默认值，如果指定则转为列表
            if args.entry:
                entry_names = args.entry if isinstance(args.entry, list) else [args.entry]
            else:
                entry_names = [config['default_strategies']['entry']]
            
            if args.exit:
                exit_names = args.exit if isinstance(args.exit, list) else [args.exit]
            else:
                exit_names = [config['default_strategies']['exit']]
            
            strategy_combinations = get_strategy_combinations_from_lists(entry_names, exit_names)
            
            if len(strategy_combinations) > 1:
                print(f"\n📊 单股票回测 - 多策略组合")
                print(f"   股票代码: {args.ticker}")
                print(f"   入场策略: {', '.join(entry_names)}")
                print(f"   出场策略: {', '.join(exit_names)}")
                print(f"   策略组合数: {len(strategy_combinations)}")
            else:
                print(f"\n📊 单股票回测")
                print(f"   股票代码: {args.ticker}")
                print(f"   入场策略: {entry_names[0]}")
                print(f"   出场策略: {exit_names[0]}")
        else:
            # 模式3：使用默认策略
            entry_name = config['default_strategies']['entry']
            exit_name = config['default_strategies']['exit']
            strategy_combinations = [(entry_name, exit_name)]
            print(f"\n📊 单股票回测")
            print(f"   股票代码: {args.ticker}")
            print(f"   入场策略: {entry_name}")
            print(f"   出场策略: {exit_name}")
    
        capital = args.capital or config['backtest']['starting_capital_jpy']
        
        # 处理时间范围：优先级 --years > --start/--end > config默认值
        if args.years:
            # 使用最近x年的数据
            end_date = args.end or config['backtest']['end_date']
            from datetime import datetime
            from dateutil.relativedelta import relativedelta
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            start_dt = end_dt - relativedelta(years=args.years)
            start_date = start_dt.strftime('%Y-%m-%d')
            print(f"   时间范围: 最近{args.years}年 ({start_date} → {end_date})")
        else:
            start_date = args.start or config['backtest']['start_date']
            end_date = args.end or config['backtest']['end_date']
            print(f"   时间范围: {start_date} → {end_date}")
        
        print(f"   起始资金: ¥{capital:,}")
        print("="*60)
        
        # 加载数据（只读模式）
        data_manager = StockDataManager()
        stock_data = data_manager.load_stock_features(args.ticker)
        
        if stock_data.empty:
            print(f"❌ 错误: 无法找到股票 {args.ticker} 的数据文件")
            print(f"   请先运行: python main.py fetch --tickers {args.ticker}")
            return
        
        # 执行回测
        results = []
        for i, (entry_name, exit_name) in enumerate(strategy_combinations, 1):
            if len(strategy_combinations) > 1:
                print(f"\n[{i}/{len(strategy_combinations)}] {entry_name} × {exit_name}")
            
            # 创建策略实例
            entry_strategy = load_entry_strategy(entry_name)
            exit_strategy = load_exit_strategy(exit_name)
            
            # 执行回测
            result = backtest_strategy(
                ticker=args.ticker,
                scorer=entry_strategy,
                exiter=exit_strategy,
                start_date=start_date,
                end_date=end_date,
                starting_capital_jpy=capital
            )
            
            results.append({
                'entry': entry_name,
                'exit': exit_name,
                'result': result
            })
            
            # 显示结果
            if len(strategy_combinations) == 1:
                print(f"\n📈 回测结果")
                print(f"   最终资金: ¥{result.final_capital_jpy:,.0f}")
                print(f"   总收益率: {result.total_return_pct:.2f}%")
                print(f"   交易次数: {result.num_trades}")
                print(f"   胜率: {result.win_rate_pct:.1f}%")
                print(f"   最大回撤: {result.max_drawdown_pct:.2f}%")
                if result.sharpe_ratio:
                    print(f"   夏普比率: {result.sharpe_ratio:.2f}")
                print(f"\n   买入持有收益: {result.buy_hold_return_pct:.2f}%")
                print(f"   择时Alpha: {result.timing_alpha:.2f}%")
                if result.benchmark_return_pct:
                    print(f"   TOPIX收益: {result.benchmark_return_pct:.2f}%")
                    print(f"   选股Alpha: {result.stock_selection_alpha:.2f}%")
            else:
                # 简要显示
                print(f"   收益率: {result.total_return_pct:6.2f}% | 夏普: {result.sharpe_ratio:5.2f} | 回撤: {result.max_drawdown_pct:5.2f}% | 交易: {result.num_trades:3d}次")
        
        # 如果是多策略，显示排名
        if len(results) > 1:
            print(f"\n\n{'='*80}")
            print("策略排名 (按收益率)")
            print(f"{'='*80}")
            sorted_results = sorted(results, key=lambda x: x['result'].total_return_pct, reverse=True)
            
            print(f"{'排名':<4} {'入场策略':<25} {'出场策略':<25} {'收益率':>10} {'夏普':>8} {'胜率':>8}")
            print("-" * 80)
            for i, item in enumerate(sorted_results, 1):
                r = item['result']
                print(f"{i:<4} {item['entry']:<25} {item['exit']:<25} {r.total_return_pct:>9.2f}% {r.sharpe_ratio:>7.2f} {r.win_rate_pct:>7.1f}%")


def cmd_backtest_old(args):
    """原始单股票回测命令（兼容旧代码）"""
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
    from pathlib import Path
    import pandas as pd
    
    # 直接从parquet文件加载数据
    features_path = Path('data/features') / f"{args.ticker}_features.parquet"
    
    if not features_path.exists():
        print(f"❌ 错误: 无法找到股票 {args.ticker} 的数据文件")
        print(f"   请先运行: python main.py fetch --tickers {args.ticker}")
        return
    
    stock_data = pd.read_parquet(features_path)
    stock_data = pd.read_parquet(features_path)
    
    if stock_data.empty:
        print(f"❌ 错误: 股票 {args.ticker} 的数据为空")
        return
    
    # 标准化日期列
    if 'Date' in stock_data.columns:
        stock_data = stock_data.rename(columns={'Date': 'date'})
    stock_data['date'] = pd.to_datetime(stock_data['date']).dt.strftime('%Y-%m-%d')
    
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
    print(f"   最终资金: ¥{result.final_capital_jpy:,.0f}")
    print(f"   总收益率: {result.total_return_pct:.2f}%")
    print(f"   交易次数: {result.num_trades}")
    print(f"   胜率: {result.win_rate_pct:.1f}%")
    print(f"   最大回撤: {result.max_drawdown_pct:.2f}%")
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
    from src.utils.strategy_loader import (
        get_all_strategy_combinations,
        get_strategy_combinations_from_lists,
        load_entry_strategy,
        load_exit_strategy
    )
    from src.backtest.portfolio_engine import PortfolioBacktestEngine
    from src.backtest.lot_size_manager import LotSizeManager
    from src.data.stock_data_manager import StockDataManager
    from src.utils.output_logger import create_logger
    import pandas as pd
    
    # 加载lot sizes配置
    if 'lot_sizes' in config:
        LotSizeManager.load_from_config(config['lot_sizes'])
    
    # 启动日志输出
    logger = create_logger('portfolio')
    with logger:
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
        
        # 确定要测试的策略组合
        if args.all_strategies:
            # 模式1：全部策略组合
            strategy_combinations = get_all_strategy_combinations()
            print(f"   策略组合数: {len(strategy_combinations)}")
        elif args.entry or args.exit:
            # 模式2：指定策略（支持列表）
            if args.entry:
                entry_names = args.entry if isinstance(args.entry, list) else [args.entry]
            else:
                entry_names = [config['default_strategies']['entry']]
            
            if args.exit:
                exit_names = args.exit if isinstance(args.exit, list) else [args.exit]
            else:
                exit_names = [config['default_strategies']['exit']]
            
            strategy_combinations = get_strategy_combinations_from_lists(entry_names, exit_names)
            
            if len(strategy_combinations) > 1:
                print(f"   入场策略: {', '.join(entry_names)}")
                print(f"   出场策略: {', '.join(exit_names)}")
                print(f"   策略组合数: {len(strategy_combinations)}")
            else:
                print(f"   入场策略: {entry_names[0]}")
                print(f"   出场策略: {exit_names[0]}")
        else:
            # 模式3：使用默认策略
            entry_name = config['default_strategies']['entry']
            exit_name = config['default_strategies']['exit']
            strategy_combinations = [(entry_name, exit_name)]
            print(f"   入场策略: {entry_name}")
            print(f"   出场策略: {exit_name}")
        
        capital = args.capital or config['backtest']['starting_capital_jpy']
        
        # 处理时间范围：优先级 --years > --start/--end > config默认值
        if args.years:
            # 使用最近x年的数据
            end_date = args.end or config['backtest']['end_date']
            from datetime import datetime
            from dateutil.relativedelta import relativedelta
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            start_dt = end_dt - relativedelta(years=args.years)
            start_date = start_dt.strftime('%Y-%m-%d')
            print(f"   时间范围: 最近{args.years}年 ({start_date} → {end_date})")
        else:
            start_date = args.start or config['backtest']['start_date']
            end_date = args.end or config['backtest']['end_date']
            print(f"   时间范围: {start_date} → {end_date}")
        
        print(f"   股票代码: {', '.join(tickers[:5])}{'...' if len(tickers) > 5 else ''}")
        print(f"   起始资金: ¥{capital:,}")
        print(f"   最大持仓: {config['portfolio']['max_positions']}只")
        print("="*60)
        
        # 加载所有股票数据（只读模式）
        data_manager = StockDataManager()
        all_data = {}
        
        for ticker in tickers:
            stock_data = data_manager.load_stock_features(ticker)
            
            if stock_data.empty:
                print(f"⚠️ 跳过 {ticker}: 数据文件不存在")
                continue
            
            # 标准化日期列
            if 'Date' in stock_data.columns:
                stock_data = stock_data.rename(columns={'Date': 'date'})
            stock_data['date'] = pd.to_datetime(stock_data['date']).dt.strftime('%Y-%m-%d')
            
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
        results = []
        for i, (entry_name, exit_name) in enumerate(strategy_combinations, 1):
            if len(strategy_combinations) > 1:
                print(f"\n[{i}/{len(strategy_combinations)}] {entry_name} × {exit_name}")
            
            # 创建策略实例
            entry_strategy = load_entry_strategy(entry_name)
            exit_strategy = load_exit_strategy(exit_name)
            
            # 执行组合回测
            engine = PortfolioBacktestEngine(
                starting_capital=capital,
                max_positions=config['portfolio']['max_positions']
            )
            
            result = engine.backtest_portfolio_strategy(
                tickers=tickers,
                entry_strategy=entry_strategy,
                exit_strategy=exit_strategy,
                start_date=start_date,
                end_date=end_date
            )
            
            results.append({
                'entry': entry_name,
                'exit': exit_name,
                'result': result
            })
            
            # 显示结果
            if len(strategy_combinations) == 1:
                print(f"\n📈 组合回测结果")
                print(f"   最终资金: ¥{result.final_capital_jpy:,.0f}")
                print(f"   总收益率: {result.total_return_pct:.2f}%")
                print(f"   交易次数: {result.num_trades}")
                print(f"   胜率: {result.win_rate_pct:.1f}%")
                print(f"   最大回撤: {result.max_drawdown_pct:.2f}%")
                if result.sharpe_ratio:
                    print(f"   夏普比率: {result.sharpe_ratio:.2f}")
                if result.benchmark_return_pct:
                    print(f"\n   TOPIX收益: {result.benchmark_return_pct:.2f}%")
                    print(f"   超额收益: {result.total_return_pct - result.benchmark_return_pct:.2f}%")
            else:
                # 简要显示
                print(f"   收益率: {result.total_return_pct:6.2f}% | 夏普: {result.sharpe_ratio:5.2f} | 回撤: {result.max_drawdown_pct:5.2f}% | 交易: {result.num_trades:3d}次")
        
        # 如果是多策略，显示排名
        if len(results) > 1:
            print(f"\n\n{'='*100}")
            print("策略排名 (按收益率)")
            print(f"{'='*100}")
            sorted_results = sorted(results, key=lambda x: x['result'].total_return_pct, reverse=True)
            
            # 检查是否有benchmark数据
            has_benchmark = any(r['result'].benchmark_return_pct is not None for r in sorted_results)
            
            if has_benchmark:
                print(f"{'排名':<4} {'入场策略':<22} {'出场策略':<22} {'收益率':>10} {'夏普':>8} {'胜率':>8} {'TOPIX%':>9} {'超额%':>9}")
                print("-" * 100)
                for i, item in enumerate(sorted_results, 1):
                    r = item['result']
                    topix_str = f"{r.benchmark_return_pct:>8.2f}%" if r.benchmark_return_pct is not None else "    N/A  "
                    alpha_str = f"{r.alpha:>8.2f}%" if r.alpha is not None else "    N/A  "
                    print(f"{i:<4} {item['entry']:<22} {item['exit']:<22} {r.total_return_pct:>9.2f}% {r.sharpe_ratio:>7.2f} {r.win_rate_pct:>7.1f}% {topix_str} {alpha_str}")
            else:
                print(f"{'排名':<4} {'入场策略':<25} {'出场策略':<25} {'收益率':>10} {'夏普':>8} {'胜率':>8}")
                print("-" * 100)
                for i, item in enumerate(sorted_results, 1):
                    r = item['result']
                    print(f"{i:<4} {item['entry']:<25} {item['exit']:<25} {r.total_return_pct:>9.2f}% {r.sharpe_ratio:>7.2f} {r.win_rate_pct:>7.1f}%")


def cmd_portfolio_old(args):
    """原始组合投资回测命令（兼容旧代码）"""
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
    import pandas as pd
    
    # 加载所有股票数据（只读模式）
    data_manager = StockDataManager()  # 不需要API key
    all_data = {}
    
    for ticker in tickers:
        stock_data = data_manager.load_stock_features(ticker)
        
        if stock_data.empty:
            print(f"⚠️ 跳过 {ticker}: 数据文件不存在")
            continue
        
        # 标准化日期列
        if 'Date' in stock_data.columns:
            stock_data = stock_data.rename(columns={'Date': 'date'})
        stock_data['date'] = pd.to_datetime(stock_data['date']).dt.strftime('%Y-%m-%d')
        
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
    print(f"   最终资金: ¥{result.final_capital_jpy:,.0f}")
    print(f"   总收益率: {result.total_return_pct:.2f}%")
    print(f"   交易次数: {result.num_trades}")
    print(f"   胜率: {result.win_rate_pct:.1f}%")
    print(f"   最大回撤: {result.max_drawdown_pct:.2f}%")
    if result.sharpe_ratio:
        print(f"   夏普比率: {result.sharpe_ratio:.2f}")
    
    if result.benchmark_return_pct:
        print(f"\n   TOPIX收益: {result.benchmark_return_pct:.2f}%")
        print(f"   超额收益: {result.total_return_pct - result.benchmark_return_pct:.2f}%")


def cmd_universe(args):
    """股票宇宙选股（正式版命令，支持分批与断点续传）"""
    import os
    import json
    from dotenv import load_dotenv
    from src.data.stock_data_manager import StockDataManager
    from src.universe.stock_selector import UniverseSelector
    import pandas as pd
    from pathlib import Path
    from datetime import datetime

    # ========== 环境与组件 ==========
    load_dotenv()
    api_key = os.getenv('JQUANTS_API_KEY')
    if not api_key:
        print("❌ 错误: 未找到 JQUANTS_API_KEY")
        return

    print("\n" + "="*80)
    print("J-Stock Universe Selector - CLI (Batch + Resume)")
    if args.no_fetch:
        print("⚡ NO-FETCH模式: 跳过数据抓取，使用现有本地数据")
    print("="*80 + "\n")
    manager = StockDataManager(api_key=api_key)
    selector = UniverseSelector(manager)

    # ========== 加载CSV宇宙（不做过滤，保留ETF等） ==========
    csv_path = Path(args.csv_file) if args.csv_file else Path('data/jpx_final_list.csv')
    if not csv_path.exists():
        print(f"❌ 错误: 未找到CSV文件 {csv_path}")
        return
    df = pd.read_csv(csv_path, encoding='utf-8')
    if 'Code' not in df.columns:
        print("❌ 错误: CSV缺少Code列")
        return
    full_codes = df['Code'].astype(str).str.strip().tolist()
    if args.limit:
        full_codes = full_codes[:args.limit]
        print(f"🧪 限制模式: 仅处理前 {args.limit} 支股票")

    # ========== Checkpoint IO ==========
    checkpoints_dir = Path('data/universe/checkpoints')
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    checkpoint_path = Path(args.checkpoint) if args.checkpoint else checkpoints_dir / f'universe_run_{run_id}.json'

    def load_checkpoint(path: Path) -> dict:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_checkpoint(state: dict) -> None:
        state['updated_at'] = datetime.now().isoformat()
        with open(checkpoint_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    # Initialize or resume
    processed_codes = set()
    failed_codes = set()
    last_index = 0
    batch_size = args.batch_size or 100

    consolidated_scores_path = Path('data/universe') / f'scores_all_{run_id}.parquet'

    if args.resume:
        state = load_checkpoint(checkpoint_path)
        if state:
            print(f"🔁 断点续传: {checkpoint_path}")
            run_id = state.get('run_id', run_id)
            processed_codes = set(state.get('processed_codes', []))
            failed_codes = set(state.get('failed_codes', []))
            last_index = int(state.get('last_index', 0))
            consolidated_scores_path = Path(state.get('scores_path', consolidated_scores_path))
        else:
            print("⚠️ 未找到有效的checkpoint，按新任务启动")

    # Persist initial state
    save_checkpoint({
        'run_id': run_id,
        'csv_file': str(csv_path),
        'top_n': args.top_n,
        'batch_size': batch_size,
        'processed_codes': list(processed_codes),
        'failed_codes': list(failed_codes),
        'last_index': last_index,
        'scores_path': str(consolidated_scores_path),
        'created_at': datetime.now().isoformat()
    })

    print(f"🚀 开始选股 (Top {args.top_n})，股票数: {len(full_codes)}，批大小: {batch_size}")

    # ========== Batch Loop ==========
    total = len(full_codes)
    start_idx = last_index
    while start_idx < total:
        end_idx = min(start_idx + batch_size, total)
        batch_codes = full_codes[start_idx:end_idx]

        # Skip codes already processed
        batch_codes = [c for c in batch_codes if c not in processed_codes]
        if not batch_codes:
            start_idx = end_idx
            continue

        print(f"\n[Batch {start_idx}-{end_idx}] 处理 {len(batch_codes)} 支股票")
        try:
            df_top, df_scored = selector.run_selection(
                top_n=args.top_n,
                test_mode=False,
                test_limit=10,
                ticker_list=batch_codes,
                apply_filters=False,
                return_full=True,
                no_fetch=args.no_fetch
            )
        except Exception as e:
            print(f"❌ 批次失败: {e}")
            # 标记整批失败的codes为失败（保留继续能力）
            for c in batch_codes:
                failed_codes.add(c)
            # 更新checkpoint并继续下批
            save_checkpoint({
                'run_id': run_id,
                'csv_file': str(csv_path),
                'top_n': args.top_n,
                'batch_size': batch_size,
                'processed_codes': list(processed_codes),
                'failed_codes': list(failed_codes),
                'last_index': end_idx,
                'scores_path': str(consolidated_scores_path),
                'created_at': datetime.now().isoformat()
            })
            start_idx = end_idx
            continue

        # Append consolidated scores
        try:
            if consolidated_scores_path.exists():
                # Append by concatenation
                existing = pd.read_parquet(consolidated_scores_path)
                combined = pd.concat([existing, df_scored], ignore_index=True)
                # Deduplicate by Code + DataDate
                subset_cols = [c for c in ['Code', 'DataDate'] if c in combined.columns]
                if subset_cols:
                    combined = combined.drop_duplicates(subset=subset_cols, keep='last')
                combined.to_parquet(consolidated_scores_path, index=False)
            else:
                df_scored.to_parquet(consolidated_scores_path, index=False)
        except Exception as e:
            print(f"⚠️ 无法追加合并分数: {e}")

        # Update processed set
        for c in batch_codes:
            processed_codes.add(c)

        # Update checkpoint
        save_checkpoint({
            'run_id': run_id,
            'csv_file': str(csv_path),
            'top_n': args.top_n,
            'batch_size': batch_size,
            'processed_codes': list(processed_codes),
            'failed_codes': list(failed_codes),
            'last_index': end_idx,
            'scores_path': str(consolidated_scores_path),
            'created_at': datetime.now().isoformat()
        })

        start_idx = end_idx

    # ========== Finalize ==========
    if consolidated_scores_path.exists():
        all_scores = pd.read_parquet(consolidated_scores_path)
        
        # ========== GLOBAL NORMALIZATION (5 dimensions) ==========
        print(f"\n📊 全局归一化 ({len(all_scores)} 支股票)")
        
        # Percentile ranking across all stocks
        all_scores['Rank_Vol'] = all_scores['ATR_Ratio'].rank(pct=True, ascending=True)
        all_scores['Rank_Liq'] = all_scores['MedianTurnover'].rank(pct=True, ascending=True)
        all_scores['Rank_Trend'] = all_scores['TrendStrength'].rank(pct=True, ascending=True)
        all_scores['Rank_Momentum'] = all_scores['Momentum_20d'].rank(pct=True, ascending=True)
        all_scores['Rank_VolSurge'] = all_scores['Volume_Surge'].rank(pct=True, ascending=True)
        
        # Weighted scoring (5 dimensions)
        WEIGHT_VOL = 0.25
        WEIGHT_LIQ = 0.25
        WEIGHT_TREND = 0.20
        WEIGHT_MOMENTUM = 0.20
        WEIGHT_VOLSURGE = 0.10
        
        all_scores['TotalScore'] = (
            WEIGHT_VOL * all_scores['Rank_Vol'] +
            WEIGHT_LIQ * all_scores['Rank_Liq'] +
            WEIGHT_TREND * all_scores['Rank_Trend'] +
            WEIGHT_MOMENTUM * all_scores['Rank_Momentum'] +
            WEIGHT_VOLSURGE * all_scores['Rank_VolSurge']
        )
        
        print(f"   权重分配: Vol={WEIGHT_VOL}, Liq={WEIGHT_LIQ}, Trend={WEIGHT_TREND}, Momentum={WEIGHT_MOMENTUM}, VolSurge={WEIGHT_VOLSURGE}")
        print(f"   分数范围: {all_scores['TotalScore'].min():.3f} - {all_scores['TotalScore'].max():.3f}")
        
        # Compute global top-N
        df_top_final = all_scores.nlargest(args.top_n, 'TotalScore').copy()
        df_top_final['Rank'] = range(1, len(df_top_final) + 1)

        # Summary print
        selector.print_summary(df_top_final, n=min(10, len(df_top_final)))

        # Save outputs
        json_path, csv_path = selector.save_selection_results(df_top_final, format='both')
        txt_path = selector.save_scores_txt(all_scores, df_top_final, top_n=args.top_n)

        print(f"\n✅ 全量选股完成")
        if json_path:
            print(f"📄 JSON: {json_path}")
        if csv_path:
            print(f"📊 CSV:  {csv_path}")
        if txt_path:
            print(f"🧾 TXT:  {txt_path}")

    else:
        print("⚠️ 未生成合并分数文件，无法输出最终结果")

    def cmd_evaluate(args):
        """策略综合评价命令"""
        import json
        from src.evaluation import (
            StrategyEvaluator,
            create_annual_periods,
            create_monthly_periods,
            create_quarterly_periods
        )
    
        print("\n" + "="*80)
        print("🔬 策略综合评价系统")
        print("="*80 + "\n")
    
        # 构造时间段列表
        periods = []
    
        if args.mode == 'annual':
            # 整年评估
            if not args.years:
                print("❌ 错误: annual模式需要指定--years参数")
                return
            periods = create_annual_periods(args.years)
            print(f"📅 评估模式: 整年")
            print(f"   年份: {', '.join(map(str, args.years))}")
        
        elif args.mode == 'quarterly':
            # 季度评估
            if not args.years:
                print("❌ 错误: quarterly模式需要指定--years参数")
                return
            periods = create_quarterly_periods(args.years)
            print(f"📅 评估模式: 季度")
            print(f"   年份: {', '.join(map(str, args.years))}")
        
        elif args.mode == 'monthly':
            # 月度评估
            if not args.years:
                print("❌ 错误: monthly模式需要指定--years参数")
                return
        
            months = args.months if args.months else list(range(1, 13))
            for year in args.years:
                periods.extend(create_monthly_periods(year, months))
        
            print(f"📅 评估模式: 月度")
            print(f"   年份: {', '.join(map(str, args.years))}")
            print(f"   月份: {', '.join(map(str, months))}")
        
        elif args.mode == 'custom':
            # 自定义时间段
            if not args.custom_periods:
                print("❌ 错误: custom模式需要指定--custom-periods参数")
                print('   格式: [["标签","开始日期","结束日期"], ...]')
                print('   示例: [["2021-Q1","2021-01-01","2021-03-31"], ["2021-Q2","2021-04-01","2021-06-30"]]')
                return
        
            try:
                periods = json.loads(args.custom_periods)
                print(f"📅 评估模式: 自定义")
                print(f"   时间段数: {len(periods)}")
            except json.JSONDecodeError as e:
                print(f"❌ 错误: custom_periods JSON解析失败: {e}")
                return
    
        if not periods:
            print("❌ 错误: 没有有效的时间段")
            return
    
        print(f"\n📊 时间段列表:")
        for label, start, end in periods[:5]:  # 只显示前5个
            print(f"   {label}: {start} ~ {end}")
        if len(periods) > 5:
            print(f"   ... 共 {len(periods)} 个时间段")
    
        # 创建评价器
        evaluator = StrategyEvaluator(
            data_root='data',
            output_dir=args.output_dir
        )
    
        # 运行评估
        print(f"\n🚀 开始策略评估...")
        df_results = evaluator.run_evaluation(
            periods=periods,
            entry_strategies=args.entry_strategies,
            exit_strategies=args.exit_strategies
        )
    
        if df_results.empty:
            print("❌ 评估失败: 没有生成任何结果")
            return
    
        # 保存结果
        print(f"\n💾 保存结果...")
        files = evaluator.save_results(prefix='strategy_evaluation')
    
        print(f"\n{'='*80}")
        print(f"✅ 策略评价完成！")
        print(f"{'='*80}")
        print(f"📄 原始结果: {files['raw']}")
        print(f"📊 市场环境分析: {files['regime']}")
        print(f"📝 综合报告: {files['report']}")
        print(f"{'='*80}\n")

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
    backtest_parser.add_argument('--entry', nargs='+', help='入场策略列表 (默认: SimpleScorerStrategy，支持多个)')
    backtest_parser.add_argument('--exit', nargs='+', help='出场策略列表 (默认: ATRExitStrategy，支持多个)')
    backtest_parser.add_argument('--all-strategies', action='store_true', help='测试所有策略组合 (9种)')
    backtest_parser.add_argument('--years', type=int, help='仅回测最近x年 (优先于--start，默认: 全量)')
    backtest_parser.add_argument('--start', help='开始日期 (默认: 2021-01-01)')
    backtest_parser.add_argument('--end', help='结束日期 (默认: 2026-01-08)')
    backtest_parser.add_argument('--capital', type=int, help='起始资金 (默认: 5000000)')
    
    # ========== 组合投资回测命令 ==========
    portfolio_parser = subparsers.add_parser('portfolio', help='组合投资回测')
    portfolio_group = portfolio_parser.add_mutually_exclusive_group(required=True)
    portfolio_group.add_argument('--all', action='store_true', help='使用监视列表所有股票')
    portfolio_group.add_argument('--tickers', nargs='+', help='指定股票代码列表')
    portfolio_parser.add_argument('--entry', nargs='+', help='入场策略列表 (默认: SimpleScorerStrategy，支持多个)')
    portfolio_parser.add_argument('--exit', nargs='+', help='出场策略列表 (默认: ATRExitStrategy，支持多个)')
    portfolio_parser.add_argument('--all-strategies', action='store_true', help='测试所有策略组合 (9种)')
    portfolio_parser.add_argument('--years', type=int, help='仅回测最近x年 (优先于--start，默认: 全量)')
    portfolio_parser.add_argument('--start', help='开始日期 (默认: 2021-01-01)')
    portfolio_parser.add_argument('--end', help='结束日期 (默认: 2026-01-08)')
    portfolio_parser.add_argument('--capital', type=int, help='起始资金 (默认: 5000000)')

    # ========== 宇宙选股命令（正式版） ==========
    universe_parser = subparsers.add_parser('universe', help='宇宙选股（从CSV加载）')
    universe_parser.add_argument('--csv-file', type=str, help='CSV文件路径 (默认: data/jpx_final_list.csv)')
    universe_parser.add_argument('--top-n', type=int, default=50, help='选出Top N股票 (默认: 50)')
    universe_parser.add_argument('--limit', type=int, help='仅处理前N支股票（调试用）')
    universe_parser.add_argument('--batch-size', type=int, help='批次大小（默认100）')
    universe_parser.add_argument('--resume', action='store_true', help='从checkpoint断点续传')
    universe_parser.add_argument('--checkpoint', type=str, help='指定checkpoint路径（默认自动生成）')
    universe_parser.add_argument('--no-fetch', action='store_true', help='跳过数据抓取，直接用现有features做归一化（快速重新评分）')
    
    # ========== 策略评价命令 ==========
    evaluate_parser = subparsers.add_parser('evaluate', help='策略综合评价（按年度/市场环境）')
    evaluate_parser.add_argument('--years', nargs='+', type=int, help='年份列表 (例如: 2021 2022 2023)')
    evaluate_parser.add_argument('--mode', choices=['annual', 'quarterly', 'monthly', 'custom'], default='annual', 
                                help='评估模式: annual=整年, quarterly=季度, monthly=按月, custom=自定义')
    evaluate_parser.add_argument('--months', nargs='+', type=int, help='月份列表（monthly模式，例如: 1 2 3）')
    evaluate_parser.add_argument('--custom-periods', type=str, help='自定义时间段（JSON格式）: [["2021-Q1","2021-01-01","2021-03-31"], ...]')
    evaluate_parser.add_argument('--entry-strategies', nargs='+', help='指定入场策略（默认全部）')
    evaluate_parser.add_argument('--exit-strategies', nargs='+', help='指定出场策略（默认全部）')
    evaluate_parser.add_argument('--output-dir', default='strategy_evaluation', help='输出目录（默认: strategy_evaluation）')
    
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
    elif args.command == 'universe':
        cmd_universe(args)
    elif args.command == 'evaluate':
        cmd_evaluate(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
