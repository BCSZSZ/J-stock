"""
统一回测启动入口
Run comprehensive backtest based on backtest_config.json configuration.

使用方法:
    python start_backtest.py

配置文件: backtest_config.json
"""
import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.backtest.engine import backtest_strategies
from src.backtest.report import print_summary_report, create_comparison_table

# New strategy architecture
from src.analysis.strategies.entry.scorer_strategy import SimpleScorerStrategy, EnhancedScorerStrategy
from src.analysis.strategies.entry.macd_crossover import MACDCrossoverStrategy
from src.analysis.strategies.exit.atr_exit import ATRExitStrategy
from src.analysis.strategies.exit.score_based_exit import ScoreBasedExitStrategy
from src.analysis.strategies.exit.layered_exit import LayeredExitStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class OutputRedirector:
    """重定向print输出到文件和控制台"""
    def __init__(self, filepath):
        self.terminal = sys.stdout
        self.log = open(filepath, 'w', encoding='utf-8')
    
    def write(self, message):
        # 安全地写入终端，处理编码问题
        try:
            self.terminal.write(message)
        except UnicodeEncodeError:
            # 如果终端不支持UTF-8，使用ASCII替代
            self.terminal.write(message.encode('ascii', 'replace').decode('ascii'))
        self.log.write(message)
    
    def flush(self):
        self.terminal.flush()
        self.log.flush()
    
    def close(self):
        self.log.close()


def load_config(config_path: str = "backtest_config.json") -> dict:
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config


def parse_strategies(strategy_configs: list) -> list:
    """
    解析策略配置
    格式: {"entry": "SimpleScorerStrategy", "exit": "ATRExitStrategy", "entry_params": {}, "exit_params": {}}
    """
    # Strategy mapping
    entry_map = {
        'SimpleScorerStrategy': SimpleScorerStrategy,
        'EnhancedScorerStrategy': EnhancedScorerStrategy,
        'MACDCrossoverStrategy': MACDCrossoverStrategy
    }
    
    exit_map = {
        'ATRExitStrategy': ATRExitStrategy,
        'ScoreBasedExitStrategy': ScoreBasedExitStrategy,
        'LayeredExitStrategy': LayeredExitStrategy
    }
    
    strategies = []
    for config in strategy_configs:
        if 'entry' not in config or 'exit' not in config:
            logger.warning(f"Invalid strategy config (missing entry/exit): {config}")
            continue
        
        entry_class = entry_map.get(config['entry'])
        exit_class = exit_map.get(config['exit'])
        
        if not entry_class or not exit_class:
            logger.warning(f"Unknown strategy: {config.get('entry')} + {config.get('exit')}")
            continue
        
        # Get parameters if provided
        entry_params = config.get('entry_params', {})
        exit_params = config.get('exit_params', {})
        
        strategies.append((entry_class(**entry_params), exit_class(**exit_params)))
    
    return strategies


def main():
    """Run backtest based on config file."""
    # Load environment
    load_dotenv()
    api_key = os.getenv('JQUANTS_API_KEY')
    
    if not api_key:
        logger.error("JQUANTS_API_KEY not found in environment")
        return
    
    # Load configuration
    try:
        config = load_config("backtest_config.json")
    except FileNotFoundError:
        logger.error("backtest_config.json not found! Creating default config...")
        # Create default config with new strategy architecture
        default_config = {
            "backtest_config": {
                "tickers": ["7203", "6501", "8035"],
                "start_date": "2021-01-01",
                "end_date": "2026-01-08",
                "starting_capital_jpy": 5000000,
                "include_benchmark": True,
                "strategies": [
                    # Entry Strategies: SimpleScorerStrategy, EnhancedScorerStrategy, MACDCrossoverStrategy
                    # Exit Strategies: ATRExitStrategy, ScoreBasedExitStrategy, LayeredExitStrategy
                    {"entry": "SimpleScorerStrategy", "exit": "ATRExitStrategy"},
                    {"entry": "EnhancedScorerStrategy", "exit": "ATRExitStrategy"},
                    {"entry": "MACDCrossoverStrategy", "exit": "ATRExitStrategy"},
                    {"entry": "SimpleScorerStrategy", "exit": "ScoreBasedExitStrategy"},
                    {"entry": "EnhancedScorerStrategy", "exit": "LayeredExitStrategy", 
                     "exit_params": {"use_score_utils": True}}
                ]
            },
            "output_config": {
                "save_to_file": True,
                "output_dir": "backtest_results",
                "include_timestamp": True
            }
        }
        with open("backtest_config.json", 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        config = default_config
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in backtest_config.json: {e}")
        return
    
    # Run backtest
    run_backtest_from_config(config)


def run_backtest_from_config(config: dict):
    """
    从配置字典运行回测 (可被其他脚本调用)
    
    Args:
        config: 配置字典，包含 backtest_config 和 output_config
    """
    # Parse config
    backtest_cfg = config['backtest_config']
    output_cfg = config.get('output_config', {
        'save_to_file': True,
        'output_dir': 'backtest_results',
        'include_timestamp': True
    })
    
    tickers = backtest_cfg['tickers']
    strategies = parse_strategies(backtest_cfg['strategies'])
    start_date = backtest_cfg['start_date']
    end_date = backtest_cfg['end_date']
    starting_capital = backtest_cfg['starting_capital_jpy']
    include_benchmark = backtest_cfg['include_benchmark']
    
    # Setup output redirection
    output_file = None
    redirector = None
    
    if output_cfg.get('save_to_file', True):
        output_dir = Path(output_cfg.get('output_dir', 'backtest_results'))
        output_dir.mkdir(exist_ok=True)
        
        if output_cfg.get('include_timestamp', True):
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = output_dir / f"backtest_result_{timestamp}.txt"
        else:
            output_file = output_dir / "backtest_result.txt"
        
        redirector = OutputRedirector(output_file)
        sys.stdout = redirector
        logger.info(f"输出将保存到: {output_file}")
    
    print("\n" + "="*80)
    print("回测配置")
    print("="*80)
    print(f"股票代码: {tickers} ({len(tickers)} 只)")
    print(f"策略组合: {len(strategies)} 个")
    print(f"总回测数: {len(tickers) * len(strategies)}")
    print(f"回测期间: {start_date} 至 {end_date}")
    print(f"起始资金: ¥{starting_capital:,}")
    print(f"包含TOPIX基准: {'是' if include_benchmark else '否'}")
    if output_file:
        print(f"输出文件: {output_file}")
    print("="*80)
    print(f"\n将运行 {len(tickers) * len(strategies)} 个回测...")
    print("开始回测...\n")
    
    # Run backtest
    try:
        results_df = backtest_strategies(
            tickers=tickers,
            strategies=strategies,
            start_date=start_date,
            end_date=end_date,
            starting_capital_jpy=starting_capital,
            include_benchmark=include_benchmark
        )
        
        # Save results to CSV
        csv_file = f"backtest_results_{end_date.replace('-', '')}.csv"
        results_df.to_csv(csv_file, index=False)
        logger.info(f"Results saved to {csv_file}")
        
        # Print summary report
        # Convert DataFrame back to BacktestResult objects for reporting
        from src.backtest.models import BacktestResult
        results_list = []
        for _, row in results_df.iterrows():
            result = BacktestResult(
                ticker=row['ticker'],
                ticker_name=row['ticker_name'],
                scorer_name=row['scorer_name'],
                exiter_name=row['exiter_name'],
                start_date=row['start_date'],
                end_date=row['end_date'],
                starting_capital_jpy=row['starting_capital_jpy'],
                final_capital_jpy=row['final_capital_jpy'],
                total_return_pct=row['total_return_pct'],
                annualized_return_pct=row['annualized_return_pct'],
                sharpe_ratio=row['sharpe_ratio'],
                max_drawdown_pct=row['max_drawdown_pct'],
                num_trades=row['num_trades'],
                win_rate_pct=row['win_rate_pct'],
                avg_gain_pct=row['avg_gain_pct'],
                avg_loss_pct=row['avg_loss_pct'],
                avg_holding_days=row['avg_holding_days'],
                profit_factor=row['profit_factor'],
                buy_hold_return_pct=row.get('buy_hold_return_pct'),
                timing_alpha=row.get('timing_alpha'),
                beat_buy_hold=row.get('beat_buy_hold'),
                benchmark_return_pct=row.get('benchmark_return_pct'),
                stock_selection_alpha=row.get('stock_selection_alpha'),
                alpha=row.get('alpha'),
                beat_benchmark=row.get('beat_benchmark'),
                beta=row.get('beta'),
                tracking_error=row.get('tracking_error'),
                information_ratio=row.get('information_ratio')
            )
            results_list.append(result)
        
        # Print detailed results
        print("\n" + "="*80)
        print("详细回测结果")
        print("="*80)
        
        for result in results_list:
            print(result.to_summary_string())
            print()
        
        # Print comparison table
        print("\n策略对比:")
        print("-"*80)
        comparison_cols = ['ticker', 'ticker_name', 'scorer_name', 'exiter_name', 
                          'total_return_pct', 'sharpe_ratio', 'max_drawdown_pct', 
                          'num_trades', 'win_rate_pct']
        
        # 添加双重基准对比列
        if 'timing_alpha' in results_df.columns:
            comparison_cols.extend(['buy_hold_return_pct', 'timing_alpha', 'beat_buy_hold'])
        
        if 'alpha' in results_df.columns:
            comparison_cols.extend(['stock_selection_alpha', 'alpha', 'beat_benchmark'])
        
        print(results_df[comparison_cols].to_string(index=False))
        
        # Find winner
        best = max(results_list, key=lambda r: r.sharpe_ratio)
        print("\n" + "="*80)
        print(f"🏆 最佳策略: {best.ticker} × {best.scorer_name} + {best.exiter_name}")
        print(f"   夏普比率: {best.sharpe_ratio:.2f}")
        print(f"   总回报: {best.total_return_pct:+.2f}%")
        
        # 显示双重基准对比
        if best.timing_alpha is not None:
            print(f"   vs Buy&Hold: {best.timing_alpha:+.2f}% (择时能力)")
        
        if best.alpha is not None:
            print(f"   vs TOPIX总Alpha: {best.alpha:+.2f}%")
            if best.stock_selection_alpha is not None:
                print(f"   选股Alpha: {best.stock_selection_alpha:+.2f}%")
            if best.beta is not None:
                print(f"   Beta: {best.beta:.2f}")
            if best.information_ratio is not None:
                print(f"   信息比率: {best.information_ratio:.2f}")
        
        print(f"   最大回撤: {best.max_drawdown_pct:.2f}%")
        print("="*80 + "\n")
        
        logger.info("回测完成!")
        
        if output_file:
            print(f"\n✅ 结果已保存到: {output_file}")
            print(f"✅ CSV已保存到: {csv_file}")
        
        print("\n" + "="*80)
        print("回测流程完成")
        print("="*80)
        
    except Exception as e:
        logger.error(f"回测失败: {e}", exc_info=True)
        print(f"\n❌ 错误: {e}")
    
    finally:
        # Restore stdout and close file
        if redirector:
            sys.stdout = redirector.terminal
            redirector.close()
            print(f"\n✅ 输出已保存到: {output_file}")


def main():
    """主函数 - 从 backtest_config.json 加载配置并运行"""
    # Load environment and config
    load_dotenv()
    config = load_config()
    
    # Run backtest
    run_backtest_from_config(config)


if __name__ == '__main__':
    main()
