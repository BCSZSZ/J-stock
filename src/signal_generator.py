"""
策略信号生成器
用于生成指定日期的交易信号（入场/出场判断）
"""
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analysis.signals import MarketData, Position, SignalAction
from src.data.stock_data_manager import StockDataManager


def generate_trading_signal(
    ticker: str,
    date: str,
    entry_strategy: str,
    exit_strategy: str,
    entry_params: dict = None,
    exit_params: dict = None,
    position: Position = None
) -> dict:
    """
    生成交易信号
    
    Args:
        ticker: 股票代码
        date: 目标日期 (YYYY-MM-DD)
        entry_strategy: 入场策略名称
        exit_strategy: 出场策略名称
        entry_params: 入场策略参数
        exit_params: 出场策略参数
        position: 当前持仓（如果有）
        
    Returns:
        信号字典，包含 action, confidence, reason 等信息
    """
    # 使用StockDataManager加载数据（只读模式）
    data_manager = StockDataManager()  # 不需要API key
    stock_data = data_manager.load_stock_features(ticker)
    
    if stock_data.empty:
        print(f"❌ 错误: 无法找到股票 {ticker} 的数据文件")
        print(f"   请先运行: python main.py fetch --tickers {ticker}")
        return None
    
    # 标准化日期列并设置为字符串格式
    if 'Date' not in stock_data.columns:
        print(f"❌ 错误: 数据文件缺少Date列")
        return None
    
    stock_data['date'] = pd.to_datetime(stock_data['Date']).dt.strftime('%Y-%m-%d')
    
    if stock_data.empty:
        print(f"❌ 错误: 股票 {ticker} 的数据为空")
        return None
    
    # 找到目标日期的数据
    target_data = stock_data[stock_data['date'] == date]
    
    if target_data.empty:
        print(f"❌ 错误: 未找到日期 {date} 的数据")
        print(f"   可用日期范围: {stock_data['date'].min()} → {stock_data['date'].max()}")
        return None
    
    # 获取历史数据（用于计算指标）- 包含目标日期及之前的数据
    target_idx = stock_data[stock_data['date'] == date].index[0]
    historical_data = stock_data.loc[:target_idx].copy()
    
    if len(historical_data) < 20:
        print(f"⚠️ 警告: 历史数据不足 ({len(historical_data)} 天)")
    
    # 创建MarketData对象（使用正确的构造函数）
    current_date = pd.to_datetime(date)
    
    # 加载辅助数据（trades和financials）
    df_trades = data_manager.load_trades(ticker)
    df_financials = data_manager.load_financials(ticker)
    metadata = data_manager.load_metadata(ticker)
    
    # 过滤trades到TSEPrime
    if not df_trades.empty and 'Section' in df_trades.columns:
        df_trades = df_trades[df_trades['Section'] == 'TSEPrime'].copy()
        df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
    
    # 标准化financials日期
    if not df_financials.empty:
        df_financials['DiscDate'] = pd.to_datetime(df_financials['DiscDate'])
    
    # 创建MarketData对象
    market_data = MarketData(
        ticker=ticker,
        current_date=current_date,
        df_features=historical_data.reset_index(drop=True),
        df_trades=df_trades,
        df_financials=df_financials,
        metadata=metadata
    )
    
    # 动态导入策略
    entry_strategy_class = _load_entry_strategy(entry_strategy)
    exit_strategy_class = _load_exit_strategy(exit_strategy)
    
    if not entry_strategy_class or not exit_strategy_class:
        return None
    
    # 实例化策略
    entry_params = entry_params or {}
    exit_params = exit_params or {}
    
    entry_inst = entry_strategy_class(**entry_params)
    exit_inst = exit_strategy_class(**exit_params)
    
    # 生成信号
    if position:
        # 如果有持仓，检查出场信号
        exit_signal = exit_inst.should_exit(market_data, position)
        
        if exit_signal.should_exit:
            return {
                'action': 'SELL',
                'confidence': exit_signal.confidence,
                'reason': exit_signal.reason,
                'exit_type': exit_signal.exit_type,
                'price': market_data.latest_price
            }
        else:
            return {
                'action': 'HOLD',
                'reason': 'No exit signal',
                'price': market_data.latest_price
            }
    else:
        # 无持仓，检查入场信号
        entry_signal = entry_inst.generate_entry_signal(market_data)
        
        if entry_signal.action == SignalAction.BUY:
            return {
                'action': 'BUY',
                'confidence': entry_signal.confidence,
                'reason': entry_signal.reasons[0] if entry_signal.reasons else 'Buy signal triggered',
                'score': entry_signal.metadata.get('score', None),
                'price': market_data.latest_price
            }
        else:
            return {
                'action': 'WAIT',
                'reason': entry_signal.reasons[0] if entry_signal.reasons else 'No entry signal',
                'score': entry_signal.metadata.get('score', None),
                'price': market_data.latest_price
            }


def _load_entry_strategy(strategy_name: str):
    """动态加载入场策略类"""
    try:
        if strategy_name == 'SimpleScorerStrategy':
            from src.analysis.strategies.entry.scorer_strategy import SimpleScorerStrategy
            return SimpleScorerStrategy
        elif strategy_name == 'EnhancedScorerStrategy':
            from src.analysis.strategies.entry.scorer_strategy import EnhancedScorerStrategy
            return EnhancedScorerStrategy
        elif strategy_name == 'MACDCrossoverStrategy':
            from src.analysis.strategies.entry.macd_crossover import MACDCrossoverStrategy
            return MACDCrossoverStrategy
        else:
            print(f"❌ 错误: 未知的入场策略 '{strategy_name}'")
            print(f"   可用策略: SimpleScorerStrategy, EnhancedScorerStrategy, MACDCrossoverStrategy")
            return None
    except ImportError as e:
        print(f"❌ 错误: 无法导入策略 {strategy_name}: {e}")
        return None


def _load_exit_strategy(strategy_name: str):
    """动态加载出场策略类"""
    try:
        if strategy_name == 'ATRExitStrategy':
            from src.analysis.strategies.exit.atr_exit import ATRExitStrategy
            return ATRExitStrategy
        elif strategy_name == 'ScoreBasedExitStrategy':
            from src.analysis.strategies.exit.score_based_exit import ScoreBasedExitStrategy
            return ScoreBasedExitStrategy
        elif strategy_name == 'LayeredExitStrategy':
            from src.analysis.strategies.exit.layered_exit import LayeredExitStrategy
            return LayeredExitStrategy
        else:
            print(f"❌ 错误: 未知的出场策略 '{strategy_name}'")
            print(f"   可用策略: ATRExitStrategy, ScoreBasedExitStrategy, LayeredExitStrategy")
            return None
    except ImportError as e:
        print(f"❌ 错误: 无法导入策略 {strategy_name}: {e}")
        return None


if __name__ == '__main__':
    # 测试用例
    import argparse
    
    parser = argparse.ArgumentParser(description='生成交易信号')
    parser.add_argument('ticker', help='股票代码')
    parser.add_argument('--date', default=datetime.now().strftime('%Y-%m-%d'), help='日期')
    parser.add_argument('--entry', default='SimpleScorerStrategy', help='入场策略')
    parser.add_argument('--exit', default='ATRExitStrategy', help='出场策略')
    
    args = parser.parse_args()
    
    signal = generate_trading_signal(
        ticker=args.ticker,
        date=args.date,
        entry_strategy=args.entry,
        exit_strategy=args.exit
    )
    
    if signal:
        print(f"\n✅ 信号: {signal['action']}")
        print(f"   价格: ¥{signal['price']:.2f}")
        if signal.get('confidence'):
            print(f"   置信度: {signal['confidence']:.2f}")
        if signal.get('reason'):
            print(f"   原因: {signal['reason']}")
        if signal.get('score'):
            print(f"   得分: {signal['score']:.2f}")
