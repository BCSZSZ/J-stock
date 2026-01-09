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
from src.analysis.scorers import SimpleScorer, EnhancedScorer
from src.analysis.exiters import ATRExiter, LayeredExiter

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
        self.terminal.write(message)
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
    """解析策略配置"""
    scorer_map = {
        'SimpleScorer': SimpleScorer,
        'EnhancedScorer': EnhancedScorer
    }
    
    exiter_map = {
        'ATRExiter': ATRExiter,
        'LayeredExiter': LayeredExiter
    }
    
    strategies = []
    for config in strategy_configs:
        scorer_class = scorer_map.get(config['scorer'])
        exiter_class = exiter_map.get(config['exiter'])
        
        if scorer_class and exiter_class:
            strategies.append((scorer_class(), exiter_class()))
        else:
            logger.warning(f"Unknown strategy: {config['scorer']} + {config['exiter']}")
    
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
        # Create default config if missing
        default_config = {
            "backtest_config": {
                "tickers": ["7203", "6501", "8035"],
                "start_date": "2021-01-01",
                "end_date": "2026-01-08",
                "starting_capital_jpy": 5000000,
                "include_benchmark": True,
                "strategies": [
                    {"scorer": "SimpleScorer", "exiter": "ATRExiter"},
                    {"scorer": "SimpleScorer", "exiter": "LayeredExiter"},
                    {"scorer": "EnhancedScorer", "exiter": "ATRExiter"},
                    {"scorer": "EnhancedScorer", "exiter": "LayeredExiter"}
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
    print(f"配置文件: backtest_config.json")
    print(f"股票代码: {tickers} ({len(tickers)} 只)")
    print(f"策略组合: {len(strategies)} 个")
    print(f"总回测数: {len(tickers) * len(strategies)}")
    print(f"回测期间: {start_date} 至 {end_date}")
    print(f"起始资金: ¥{starting_capital:,}")
    print(f"包含TOPIX基准: {'是' if include_benchmark else '否'}")
    if output_file:
        print(f"输出文件: {output_file}")
    print("="*80)
    
    # User confirmation if running many backtests
    total_runs = len(tickers) * len(strategies)
    if total_runs > 10:
        response = input(f"\n将运行 {total_runs} 个回测，预计耗时 {total_runs // 4} 分钟。继续? (y/n): ")
        if response.lower() != 'y':
            print("回测已取消。")
            if redirector:
                sys.stdout = redirector.terminal
                redirector.close()
            return
    
    print("\n开始回测...\n")
    
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
                benchmark_return_pct=row.get('benchmark_return_pct'),
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
        if 'alpha' in results_df.columns:
            comparison_cols.extend(['alpha', 'beta', 'information_ratio', 'beat_benchmark'])
        
        print(results_df[comparison_cols].to_string(index=False))
        
        # Find winner
        best = max(results_list, key=lambda r: r.sharpe_ratio)
        print("\n" + "="*80)
        print(f"🏆 最佳策略: {best.ticker} × {best.scorer_name} + {best.exiter_name}")
        print(f"   夏普比率: {best.sharpe_ratio:.2f}")
        print(f"   总回报: {best.total_return_pct:+.2f}%")
        if best.alpha is not None:
            print(f"   Alpha: {best.alpha:+.2f}%")
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
        
    except Exception as e:
        logger.error(f"回测失败: {e}", exc_info=True)
    
    finally:
        # Restore stdout and close file
        if redirector:
            sys.stdout = redirector.terminal
            redirector.close()
            print(f"\n✅ 输出已保存到: {output_file}")


if __name__ == '__main__':
    main()
