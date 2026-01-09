"""
Portfolio Backtest Engine - 组合投资回测引擎
Backtests portfolio strategies with multiple concurrent positions
"""
import logging
import pandas as pd
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from datetime import datetime

from .portfolio import Portfolio, Position
from .signal_ranker import SignalRanker
from .lot_size_manager import LotSizeManager
from .models import BacktestResult, Trade
from ..analysis.signals import TradingSignal, SignalAction, MarketData
from ..analysis.strategies.base_entry_strategy import BaseEntryStrategy
from ..analysis.strategies.base_exit_strategy import BaseExitStrategy

logger = logging.getLogger(__name__)


class PortfolioBacktestEngine:
    """
    组合投资回测引擎
    
    与单股票引擎的主要区别:
    1. 同时管理多只股票
    2. 资金分配策略
    3. 信号竞争处理
    4. 最小购买单位限制
    """
    
    def __init__(
        self,
        starting_capital: float,
        max_positions: int = 5,
        max_position_pct: float = 0.30,
        min_position_pct: float = 0.05,
        signal_ranking_method: str = "simple_score",
        data_root: str = './data'
    ):
        """
        Args:
            starting_capital: 起始资金
            max_positions: 最大持仓数
            max_position_pct: 单股最大仓位
            min_position_pct: 单股最小仓位
            signal_ranking_method: 信号排序方法
            data_root: 数据根目录
        """
        self.starting_capital = starting_capital
        self.max_positions = max_positions
        self.max_position_pct = max_position_pct
        self.min_position_pct = min_position_pct
        self.data_root = data_root
        
        # 创建信号排序器
        self.signal_ranker = SignalRanker(method=signal_ranking_method)
    
    def backtest_portfolio_strategy(
        self,
        tickers: List[str],
        entry_strategy: BaseEntryStrategy,
        exit_strategy: BaseExitStrategy,
        start_date: str,
        end_date: str,
        show_daily_status: bool = False,
        show_signal_ranking: bool = True
    ) -> BacktestResult:
        """
        回测组合策略
        
        Args:
            tickers: 股票池列表
            entry_strategy: 入场策略
            exit_strategy: 出场策略
            start_date: 开始日期
            end_date: 结束日期
            show_daily_status: 是否显示每日组合状态
            show_signal_ranking: 是否显示信号排序过程
            
        Returns:
            组合回测结果
        """
        strategy_name = f"{entry_strategy.strategy_name} + {exit_strategy.strategy_name}"
        logger.info(f"Backtesting Portfolio: {strategy_name}")
        logger.info(f"Stock pool: {tickers}")
        
        # 创建组合
        portfolio = Portfolio(
            starting_cash=self.starting_capital,
            max_positions=self.max_positions,
            max_position_pct=self.max_position_pct,
            min_position_pct=self.min_position_pct
        )
        
        # 加载所有股票数据
        all_data = {}
        for ticker in tickers:
            try:
                data = self._load_stock_data(ticker)
                all_data[ticker] = data
            except Exception as e:
                logger.warning(f"Failed to load {ticker}: {e}")
        
        if not all_data:
            logger.error("No stock data loaded!")
            return self._empty_result(tickers, entry_strategy, exit_strategy, start_date, end_date)
        
        # 获取交易日历（取所有股票的交易日并集）
        trading_days = self._get_trading_calendar(all_data, start_date, end_date)
        
        if not trading_days:
            logger.warning("No trading days in date range")
            return self._empty_result(tickers, entry_strategy, exit_strategy, start_date, end_date)
        
        # 回测状态
        trades: List[Trade] = []
        daily_equity = {}
        
        # 待执行订单（信号今天生成，明天执行）
        pending_buy_signals: Dict[str, TradingSignal] = {}
        pending_sell_signals: Dict[str, TradingSignal] = {}
        
        # 每日循环
        for i, current_date in enumerate(trading_days):
            current_prices = self._get_current_prices(all_data, current_date)
            
            # ================================================================
            # STEP 1: 执行待执行的卖出订单（释放资金）
            # ================================================================
            for ticker in list(pending_sell_signals.keys()):
                if ticker in portfolio.positions:
                    sell_signal = pending_sell_signals[ticker]
                    position = portfolio.positions[ticker]
                    
                    # 获取卖出价格（明天开盘价）
                    exit_price = self._get_next_open_price(all_data[ticker], current_date)
                    
                    if exit_price is None:
                        continue
                    
                    # 执行卖出
                    proceeds = portfolio.close_position(ticker, exit_price)
                    
                    if proceeds is not None:
                        # 记录交易
                        holding_days = (current_date - position.entry_date).days
                        return_pct = ((exit_price / position.entry_price) - 1) * 100
                        return_jpy = (exit_price - position.entry_price) * position.quantity
                        
                        trade = Trade(
                            entry_date=position.entry_date.strftime('%Y-%m-%d'),
                            entry_price=position.entry_price,
                            entry_score=position.entry_signal.metadata.get('score', 0.0),
                            exit_date=current_date.strftime('%Y-%m-%d'),
                            exit_price=exit_price,
                            exit_reason=sell_signal.reasons[0] if sell_signal.reasons else "Unknown",
                            exit_urgency=sell_signal.metadata.get('trigger', 'Unknown'),
                            holding_days=holding_days,
                            shares=position.quantity,
                            return_pct=return_pct,
                            return_jpy=return_jpy,
                            peak_price=position.peak_price_since_entry
                        )
                        trades.append(trade)
                        
                        profit_icon = "📈" if return_pct > 0 else "📉"
                        trigger = sell_signal.metadata.get('trigger', 'N/A')
                        print(f"  {profit_icon} SELL {ticker}: {position.quantity:,} shares @ ¥{exit_price:,.2f} "
                              f"({return_pct:+.2f}%, ¥{return_jpy:+,.0f}) - {trigger}")
                
                del pending_sell_signals[ticker]
            
            # ================================================================
            # STEP 2: 执行待执行的买入订单
            # ================================================================
            if pending_buy_signals:
                # 对买入信号排序
                market_data_dict = {
                    ticker: self._build_market_data(ticker, all_data[ticker], current_date)
                    for ticker in pending_buy_signals.keys()
                    if ticker in all_data
                }
                
                ranked_signals = self.signal_ranker.rank_buy_signals(
                    pending_buy_signals,
                    market_data_dict
                )
                
                if show_signal_ranking and ranked_signals:
                    print(f"\n  🎯 买入信号排序 ({current_date.date()}):")
                    for rank, (ticker, signal, priority) in enumerate(ranked_signals[:5], 1):
                        score = signal.metadata.get('score', 'N/A')
                        print(f"     #{rank} {ticker}: Score={score}, Priority={priority:.1f}")
                
                # 依次尝试买入
                for ticker, buy_signal, priority in ranked_signals:
                    # 检查是否已达持仓上限
                    if not portfolio.can_open_new_position():
                        if show_signal_ranking:
                            print(f"  ⚠️  已达最大持仓数 {portfolio.max_positions}，跳过剩余信号")
                        break
                    
                    # 检查是否已持有
                    if portfolio.has_position(ticker):
                        continue
                    
                    # 获取买入价格（明天开盘价）
                    entry_price = self._get_next_open_price(all_data[ticker], current_date)
                    
                    if entry_price is None:
                        continue
                    
                    # 计算可用资金
                    max_cash = portfolio.calculate_max_position_size(current_prices)
                    
                    # 计算可购买股数（考虑lot size）
                    shares = LotSizeManager.calculate_buyable_shares(
                        ticker, 
                        max_cash, 
                        entry_price
                    )
                    
                    if shares > 0:
                        # 创建持仓
                        position = Position(
                            ticker=ticker,
                            quantity=shares,
                            entry_price=entry_price,
                            entry_date=current_date,
                            entry_signal=buy_signal,
                            peak_price_since_entry=entry_price
                        )
                        
                        # 添加到组合
                        if portfolio.add_position(position):
                            score_display = buy_signal.metadata.get('score', 'N/A')
                            print(f"  📊 BUY  {ticker}: {shares:,} shares @ ¥{entry_price:,.2f} "
                                  f"(Score: {score_display})")
                
                pending_buy_signals.clear()
            
            # ================================================================
            # STEP 3: 生成新的信号（为明天准备）
            # ================================================================
            for ticker in tickers:
                if ticker not in all_data:
                    continue
                
                market_data = self._build_market_data(ticker, all_data[ticker], current_date)
                
                if market_data is None:
                    continue
                
                # 生成入场信号（对所有未持仓的股票）
                if not portfolio.has_position(ticker):
                    entry_signal = entry_strategy.generate_entry_signal(market_data)
                    if entry_signal.action == SignalAction.BUY:
                        pending_buy_signals[ticker] = entry_signal
                
                # 生成出场信号（仅对已持仓的股票）
                if portfolio.has_position(ticker):
                    position = portfolio.positions[ticker]
                    exit_signal = exit_strategy.generate_exit_signal(position, market_data)
                    if exit_signal.action == SignalAction.SELL:
                        pending_sell_signals[ticker] = exit_signal
            
            # ================================================================
            # STEP 4: 更新峰值价格
            # ================================================================
            portfolio.update_peak_prices(current_prices)
            
            # ================================================================
            # STEP 5: 记录每日资产
            # ================================================================
            total_value = portfolio.get_total_value(current_prices)
            daily_equity[current_date] = total_value
            
            if show_daily_status and (i % 20 == 0 or i == len(trading_days) - 1):
                print(f"\n  📊 组合状态 ({current_date.date()}):")
                print(f"     {portfolio.get_portfolio_summary(current_prices)}")
        
        # ================================================================
        # 构建回测结果
        # ================================================================
        return self._build_portfolio_result(
            portfolio=portfolio,
            trades=trades,
            daily_equity=daily_equity,
            tickers=tickers,
            entry_strategy=entry_strategy,
            exit_strategy=exit_strategy,
            start_date=start_date,
            end_date=end_date,
            current_prices=current_prices
        )
    
    def _load_stock_data(self, ticker: str) -> Dict:
        """加载单只股票的数据"""
        features_path = Path(self.data_root) / 'features' / f'{ticker}_features.parquet'
        trades_path = Path(self.data_root) / 'raw_trades' / f'{ticker}_trades.parquet'
        financials_path = Path(self.data_root) / 'raw_financials' / f'{ticker}_financials.parquet'
        metadata_path = Path(self.data_root) / 'metadata' / f'{ticker}_metadata.json'
        
        if not features_path.exists():
            raise FileNotFoundError(f"Features file not found: {features_path}")
        
        df_features = pd.read_parquet(features_path)
        df_features['Date'] = pd.to_datetime(df_features['Date'])
        df_features.set_index('Date', inplace=True)
        
        df_trades = pd.read_parquet(trades_path) if trades_path.exists() else pd.DataFrame()
        df_financials = pd.read_parquet(financials_path) if financials_path.exists() else pd.DataFrame()
        
        import json
        metadata = json.load(open(metadata_path, 'r', encoding='utf-8')) if metadata_path.exists() else {}
        
        return {
            'features': df_features,
            'trades': df_trades,
            'financials': df_financials,
            'metadata': metadata
        }
    
    def _get_trading_calendar(
        self, 
        all_data: Dict[str, Dict], 
        start_date: str, 
        end_date: str
    ) -> List[pd.Timestamp]:
        """获取交易日历（所有股票的交易日并集）"""
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        
        all_dates = set()
        for data in all_data.values():
            df = data['features']
            dates = df.index[(df.index >= start) & (df.index <= end)]
            all_dates.update(dates)
        
        return sorted(list(all_dates))
    
    def _get_current_prices(
        self, 
        all_data: Dict[str, Dict], 
        current_date: pd.Timestamp
    ) -> Dict[str, float]:
        """获取所有股票的当前价格"""
        prices = {}
        for ticker, data in all_data.items():
            df = data['features']
            if current_date in df.index:
                prices[ticker] = df.loc[current_date, 'Close']
        return prices
    
    def _get_next_open_price(
        self, 
        data: Dict, 
        current_date: pd.Timestamp
    ) -> Optional[float]:
        """获取下一个交易日的开盘价"""
        df = data['features']
        if current_date not in df.index:
            return None
        return df.loc[current_date, 'Open']
    
    def _build_market_data(
        self,
        ticker: str,
        data: Dict, 
        current_date: pd.Timestamp
    ) -> Optional[MarketData]:
        """构建MarketData对象"""
        df = data['features']
        
        if current_date not in df.index:
            return None
        
        df_historical = df[df.index <= current_date]
        
        return MarketData(
            ticker=ticker,
            df_features=df_historical,
            df_trades=data['trades'],
            df_financials=data['financials'],
            metadata=data['metadata'],
            current_date=current_date
        )
    
    def _build_portfolio_result(
        self,
        portfolio: Portfolio,
        trades: List[Trade],
        daily_equity: Dict,
        tickers: List[str],
        entry_strategy,
        exit_strategy,
        start_date: str,
        end_date: str,
        current_prices: Dict[str, float]
    ) -> BacktestResult:
        """构建组合回测结果"""
        
        final_value = portfolio.get_total_value(current_prices)
        total_return_pct = ((final_value / self.starting_capital) - 1) * 100
        
        # 计算年化回报
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        years = (end - start).days / 365.25
        annualized_return = ((final_value / self.starting_capital) ** (1 / years) - 1) * 100 if years > 0 else 0
        
        # 计算其他指标
        winning_trades = [t for t in trades if t.return_pct > 0]
        losing_trades = [t for t in trades if t.return_pct <= 0]
        
        win_rate = len(winning_trades) / len(trades) * 100 if trades else 0
        avg_gain = sum(t.return_pct for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.return_pct for t in losing_trades) / len(losing_trades) if losing_trades else 0
        
        # TODO: 实现Sharpe ratio, max drawdown等
        
        ticker_display = f"Portfolio[{', '.join(tickers)}]"
        
        return BacktestResult(
            ticker=ticker_display,
            ticker_name="Portfolio",
            scorer_name=entry_strategy.strategy_name,
            exiter_name=exit_strategy.strategy_name,
            start_date=start_date,
            end_date=end_date,
            starting_capital_jpy=self.starting_capital,
            final_capital_jpy=final_value,
            total_return_pct=total_return_pct,
            annualized_return_pct=annualized_return,
            sharpe_ratio=0.0,  # TODO
            max_drawdown_pct=0.0,  # TODO
            num_trades=len(trades),
            win_rate_pct=win_rate,
            avg_gain_pct=avg_gain,
            avg_loss_pct=avg_loss,
            avg_holding_days=sum(t.holding_days for t in trades) / len(trades) if trades else 0,
            profit_factor=0.0  # TODO
        )
    
    def _empty_result(self, tickers, entry_strategy, exit_strategy, start_date, end_date) -> BacktestResult:
        """创建空结果"""
        ticker_display = f"Portfolio[{', '.join(tickers)}]"
        return BacktestResult(
            ticker=ticker_display,
            ticker_name="Portfolio",
            scorer_name=entry_strategy.strategy_name,
            exiter_name=exit_strategy.strategy_name,
            start_date=start_date,
            end_date=end_date,
            starting_capital_jpy=self.starting_capital,
            final_capital_jpy=self.starting_capital,
            total_return_pct=0.0,
            annualized_return_pct=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            num_trades=0,
            win_rate_pct=0.0,
            avg_gain_pct=0.0,
            avg_loss_pct=0.0,
            avg_holding_days=0.0,
            profit_factor=0.0
        )
