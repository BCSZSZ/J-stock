"""
组合投资回测启动脚本
Portfolio Backtest Entry Point

与单股票回测的区别:
- 同时管理多只股票
- 资金分配策略
- 信号竞争处理
- 考虑最小购买单位

使用方法:
    python start_portfolio_backtest.py
    
配置文件: portfolio_config.json
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

from src.backtest.portfolio_engine import PortfolioBacktestEngine
from src.backtest.lot_size_manager import LotSizeManager

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
        try:
            self.terminal.write(message)
        except UnicodeEncodeError:
            self.terminal.write(message.encode('ascii', 'replace').decode('ascii'))
        self.log.write(message)
    
    def flush(self):
        self.terminal.flush()
        self.log.flush()
    
    def close(self):
        self.log.close()


def load_config(config_path: str = "portfolio_config.json") -> dict:
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config


def parse_strategies(strategy_configs: list) -> list:
    """解析策略配置"""
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
        
        entry_params = config.get('entry_params', {})
        exit_params = config.get('exit_params', {})
        
        strategies.append((entry_class(**entry_params), exit_class(**exit_params)))
    
    return strategies


def run_portfolio_backtest_from_config(config: dict):
    """
    从配置字典运行组合回测
    
    Args:
        config: 配置字典，包含 portfolio_backtest_config 和 output_config
    """
    # Parse config
    backtest_cfg = config['portfolio_backtest_config']
    output_cfg = config.get('output_config', {
        'save_to_file': True,
        'output_dir': 'portfolio_backtest_results',
        'include_timestamp': True
    })
    
    tickers = backtest_cfg['tickers']
    strategies = parse_strategies(backtest_cfg['strategies'])
    start_date = backtest_cfg['start_date']
    end_date = backtest_cfg['end_date']
    
    # Portfolio rules
    portfolio_rules = backtest_cfg['portfolio_rules']
    starting_capital = portfolio_rules['starting_capital_jpy']
    max_positions = portfolio_rules.get('max_positions', 5)
    max_position_pct = portfolio_rules.get('max_position_pct', 0.30)
    min_position_pct = portfolio_rules.get('min_position_pct', 0.05)
    
    # Signal ranking
    signal_ranking = backtest_cfg.get('signal_ranking', {})
    ranking_method = signal_ranking.get('method', 'simple_score')
    
    # Load lot sizes
    lot_sizes = backtest_cfg.get('lot_sizes', {})
    if lot_sizes:
        LotSizeManager.load_from_config(lot_sizes)
    
    include_benchmark = backtest_cfg.get('include_benchmark', True)
    
    # Setup output redirection
    output_file = None
    redirector = None
    
    if output_cfg.get('save_to_file', True):
        output_dir = Path(output_cfg.get('output_dir', 'portfolio_backtest_results'))
        output_dir.mkdir(exist_ok=True)
        
        if output_cfg.get('include_timestamp', True):
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = output_dir / f"portfolio_result_{timestamp}.txt"
        else:
            output_file = output_dir / "portfolio_result.txt"
        
        redirector = OutputRedirector(output_file)
        sys.stdout = redirector
        logger.info(f"输出将保存到: {output_file}")
    
    print("\n" + "="*80)
    print("组合投资回测配置")
    print("="*80)
    print(f"股票池: {tickers} ({len(tickers)} 只)")
    print(f"策略组合: {len(strategies)} 个")
    print(f"总回测数: {len(strategies)} 个组合策略")
    print(f"回测期间: {start_date} 至 {end_date}")
    print(f"起始资金: ¥{starting_capital:,}")
    print(f"最大持仓数: {max_positions} 只")
    print(f"单股最大仓位: {max_position_pct*100:.0f}%")
    print(f"信号排序方法: {ranking_method}")
    print(f"包含TOPIX基准: {'是' if include_benchmark else '否'}")
    if output_file:
        print(f"输出文件: {output_file}")
    print("="*80)
    
    print(f"\n将运行 {len(strategies)} 个组合策略回测...")
    print("开始回测...\n")
    
    # Create portfolio backtest engine
    engine = PortfolioBacktestEngine(
        starting_capital=starting_capital,
        max_positions=max_positions,
        max_position_pct=max_position_pct,
        min_position_pct=min_position_pct,
        signal_ranking_method=ranking_method
    )
    
    # Run backtest
    try:
        results = []
        
        for idx, (entry_strategy, exit_strategy) in enumerate(strategies, 1):
            print("\n" + "━"*80)
            print(f"策略 {idx}/{len(strategies)}: {entry_strategy.strategy_name} + {exit_strategy.strategy_name}")
            print("━"*80)
            
            result = engine.backtest_portfolio_strategy(
                tickers=tickers,
                entry_strategy=entry_strategy,
                exit_strategy=exit_strategy,
                start_date=start_date,
                end_date=end_date,
                show_daily_status=output_cfg.get('show_daily_portfolio_status', False),
                show_signal_ranking=output_cfg.get('show_signal_ranking', True)
            )
            
            results.append(result)
            
            # Print strategy summary
            print("\n" + "-"*80)
            print(result.to_summary_string())
            print("-"*80)
        
        # Print comparison table
        print("\n\n" + "="*80)
        print("策略对比汇总")
        print("="*80)
        
        print(f"\n{'策略':<40} {'总回报':<10} {'年化回报':<10} {'交易次数':<8} {'胜率':<8}")
        print("-"*80)
        
        for result in results:
            strategy_name = f"{result.scorer_name} + {result.exiter_name}"
            print(f"{strategy_name:<40} {result.total_return_pct:>8.2f}% {result.annualized_return_pct:>8.2f}% "
                  f"{result.num_trades:>8} {result.win_rate_pct:>7.1f}%")
        
        # Find best strategy
        best = max(results, key=lambda r: r.total_return_pct)
        print("\n" + "="*80)
        print(f"🏆 最佳策略: {best.scorer_name} + {best.exiter_name}")
        print(f"   总回报: {best.total_return_pct:+.2f}%")
        print(f"   年化回报: {best.annualized_return_pct:+.2f}%")
        print(f"   交易次数: {best.num_trades}")
        print(f"   胜率: {best.win_rate_pct:.1f}%")
        print("="*80 + "\n")
        
        logger.info("组合回测完成!")
        
        if output_file:
            print(f"\n✅ 结果已保存到: {output_file}")
        
        print("\n" + "="*80)
        print("回测流程完成")
        print("="*80)
        
    except Exception as e:
        logger.error(f"组合回测失败: {e}", exc_info=True)
        print(f"\n❌ 错误: {e}")
    
    finally:
        # Restore stdout and close file
        if redirector:
            sys.stdout = redirector.terminal
            redirector.close()
            print(f"\n✅ 输出已保存到: {output_file}")


def main():
    """主函数"""
    # Load environment
    load_dotenv()
    
    # Load configuration
    try:
        config = load_config("portfolio_config.json")
    except FileNotFoundError:
        logger.error("portfolio_config.json not found!")
        print("\n❌ 找不到配置文件: portfolio_config.json")
        print("请先创建配置文件，参考 portfolio_config.json.example")
        return
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in portfolio_config.json: {e}")
        print(f"\n❌ 配置文件JSON格式错误: {e}")
        return
    
    # Run backtest
    run_portfolio_backtest_from_config(config)


if __name__ == '__main__':
    main()
