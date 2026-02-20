"""
Backtest Engine
Core simulation logic for testing strategies on historical data.
"""
import logging
import json
import math
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from src.analysis.strategies.base_entry_strategy import BaseEntryStrategy
from src.analysis.strategies.base_exit_strategy import BaseExitStrategy
from src.analysis.signals import TradingSignal, SignalAction, MarketData, Position
from src.signal_generator import generate_signal_v2
from src.backtest.models import Trade, BacktestResult
from src.backtest.lot_size_manager import LotSizeManager
from src.data.market_data_builder import MarketDataBuilder
from src.overlays import OverlayContext, OverlayManager
from src.backtest.metrics import (
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_equity_curve,
    calculate_annualized_return,
    calculate_trade_statistics,
    calculate_beta,
    calculate_tracking_error_and_ir
)
from src.client.jquants_client import JQuantsV2Client
from src.data.benchmark_manager import BenchmarkManager

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Day-by-day backtest simulation engine.
    
    Critical Rules:
    - NO FUTURE PEEKING: Only use data up to current simulation date
    - Forward-fill sparse data (trades, financials)
    - Track peak price for trailing stops
    """
    
    def __init__(
        self,
        starting_capital_jpy: float = 5_000_000,  # ¥5M default
        buy_threshold: float = 65.0,               # Score >= 65 to buy
        data_root: str = './data',
        overlay_manager: Optional[OverlayManager] = None
    ):
        """
        Initialize backtest engine.
        
        Args:
            starting_capital_jpy: Starting capital in JPY
            buy_threshold: Minimum score to trigger buy signal
            data_root: Root directory for data files
        """
        self.starting_capital = starting_capital_jpy
        self.buy_threshold = buy_threshold
        self.data_root = Path(data_root)
        self.overlay_manager = overlay_manager
    
    def _load_data(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
        """
        Load all data for a ticker.
        
        Returns:
            (features_df, trades_df, financials_df, metadata)
        """
        # Load features (daily)
        features_path = self.data_root / 'features' / f"{ticker}_features.parquet"
        df_features = pd.read_parquet(features_path)
        # Ensure Date column is datetime and set as index
        if 'Date' in df_features.columns:
            df_features['Date'] = pd.to_datetime(df_features['Date'])
            df_features = df_features.set_index('Date')
        else:
            df_features.index = pd.to_datetime(df_features.index)
        
        # Load trades (weekly) - keep original format for scorer
        trades_path = self.data_root / 'raw_trades' / f"{ticker}_trades.parquet"
        if trades_path.exists():
            df_trades = pd.read_parquet(trades_path)
            # Filter to TSEPrime section only (most stocks are here)
            if 'Section' in df_trades.columns:
                df_trades = df_trades[df_trades['Section'] == 'TSEPrime'].copy()
            # Convert dates but keep as columns (scorer expects EnDate column)
            df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
        else:
            df_trades = pd.DataFrame()
        
        # Load financials (quarterly) - keep original format for scorer
        financials_path = self.data_root / 'raw_financials' / f"{ticker}_financials.parquet"
        if financials_path.exists():
            df_financials = pd.read_parquet(financials_path)
            # Convert dates but keep as columns (scorer expects DiscDate column)
            df_financials['DiscDate'] = pd.to_datetime(df_financials['DiscDate'])
        else:
            df_financials = pd.DataFrame()
        
        # Load metadata
        metadata_path = self.data_root / 'metadata' / f"{ticker}_metadata.json"
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        return df_features, df_trades, df_financials, metadata
    
    def backtest_strategy(
        self,
        ticker: str,
        entry_strategy,  # BaseEntryStrategy or BaseScorer (backward compatible)
        exit_strategy,   # BaseExitStrategy or BaseExiter (backward compatible)
        start_date: str = "2021-01-01",
        end_date: str = "2026-01-08"
    ) -> BacktestResult:
        """
        Run backtest for one strategy on one ticker.
        
        Supports both new Strategy interface and old Scorer/Exiter interface.
        
        Args:
            ticker: Stock code
            entry_strategy: Entry strategy (BaseEntryStrategy or BaseScorer)
            exit_strategy: Exit strategy (BaseExitStrategy or BaseExiter)
            start_date: Backtest start date
            end_date: Backtest end date
            
        Returns:
            BacktestResult with metrics and trade history
        """
        # Strategy names for logging
        strategy_name = f"{getattr(entry_strategy, 'strategy_name', entry_strategy.__class__.__name__)} + {getattr(exit_strategy, 'strategy_name', exit_strategy.__class__.__name__)}"
        logger.info(f"Backtesting {ticker}: {strategy_name}")
        
        # Load data
        df_features, df_trades, df_financials, metadata = self._load_data(ticker)
        
        # Filter date range
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        df_features = df_features[(df_features.index >= start) & (df_features.index <= end)]
        
        if df_features.empty:
            logger.warning(f"No data for {ticker} in date range")
            return self._empty_result(ticker, metadata, entry_strategy, exit_strategy, start_date, end_date)
        
        # Simulation state
        position: Optional[Position] = None
        trades: List[Trade] = []
        cash = self.starting_capital
        
        # Pending orders (signal today, execute tomorrow)
        pending_buy_signal: Optional[TradingSignal] = None
        pending_sell_signal: Optional[TradingSignal] = None
        
        # Daily equity tracking (for Beta & IR calculation)
        daily_equity = {}
        
        benchmark_data = None
        if self.overlay_manager and self.overlay_manager.needs_benchmark_data:
            manager = BenchmarkManager(client=None, data_root=str(self.data_root))
            benchmark_data = manager.get_topix_data()

        # Day-by-day simulation
        trading_days = df_features.index.tolist()
        
        for i, current_date in enumerate(trading_days):
            # Get data UP TO current date (NO FUTURE PEEKING!)
            df_features_historical = df_features[df_features.index <= current_date]
            
            # Filter trades/financials by their date columns (keep original format for scorer)
            df_trades_historical = df_trades[df_trades['EnDate'] <= current_date] if not df_trades.empty else pd.DataFrame()
            df_financials_historical = df_financials[df_financials['DiscDate'] <= current_date] if not df_financials.empty else pd.DataFrame()
            
            current_close = df_features.loc[current_date, 'Close']
            current_open = df_features.loc[current_date, 'Open']
            
            overlay_decision = None
            if self.overlay_manager:
                total_value = cash
                if position is not None:
                    total_value += position.quantity * current_close
                overlay_context = OverlayContext(
                    current_date=current_date,
                    portfolio_cash=cash,
                    portfolio_value=total_value,
                    positions={position.ticker: position} if position else {},
                    current_prices={ticker: current_close},
                    benchmark_data=benchmark_data,
                )
                overlay_decision, _ = self.overlay_manager.evaluate(overlay_context)
                if overlay_decision.force_exit and position is not None:
                    pending_sell_signal = TradingSignal(
                        action=SignalAction.SELL,
                        confidence=1.0,
                        reasons=["Overlay force exit"],
                        metadata={"trigger": "OVERLAY_FORCE_EXIT"},
                        strategy_name="Overlay",
                    )
                if (
                    overlay_decision.exit_overrides
                    and position is not None
                    and position.ticker in overlay_decision.exit_overrides
                ):
                    reason = overlay_decision.exit_overrides[position.ticker]
                    pending_sell_signal = TradingSignal(
                        action=SignalAction.SELL,
                        confidence=1.0,
                        reasons=[reason],
                        metadata={"trigger": "OVERLAY_EXIT"},
                        strategy_name="Overlay",
                    )

            # =====================================================================
            # STEP 1: EXECUTE PENDING ORDERS (from yesterday's signals)
            # =====================================================================
            
            if pending_buy_signal and position is None:
                if overlay_decision and overlay_decision.block_new_entries:
                    pending_buy_signal = None
                else:
                    # Execute BUY at today's open price (signal was generated yesterday)
                    entry_price = current_open
                    max_cash = cash
                    if overlay_decision and overlay_decision.position_scale is not None:
                        max_cash *= overlay_decision.position_scale
                    if overlay_decision and overlay_decision.target_exposure is not None:
                        max_cash = min(max_cash, cash * overlay_decision.target_exposure)

                    shares = LotSizeManager.calculate_buyable_shares(
                        ticker, max_cash, entry_price
                    )
                
                    if shares > 0:
                        # Create new Position with entry signal
                        position = Position(
                            ticker=ticker,
                            entry_price=entry_price,
                            entry_date=current_date,
                            quantity=shares,
                            entry_signal=pending_buy_signal,
                            peak_price_since_entry=entry_price
                        )
                        cash -= shares * entry_price
                        
                        score_display = pending_buy_signal.metadata.get('score', 'N/A')
                        print(f"  📊 BUY  {current_date.date()}: {shares:,} shares @ ¥{entry_price:,.2f} "
                              f"({pending_buy_signal.strategy_name}, Score: {score_display})")
                        logger.info(f"BUY executed: {shares} shares @ ¥{entry_price:.2f}")
                    
                    pending_buy_signal = None
            
            if pending_sell_signal and position is not None:
                # Execute SELL at today's open price
                exit_price = current_open
                entry_date = position.entry_date
                sell_pct = float(pending_sell_signal.metadata.get('sell_percentage', 1.0))
                qty_to_sell = self._calculate_sell_quantity(
                    ticker=ticker,
                    total_qty=position.quantity,
                    sell_pct=sell_pct,
                )

                if qty_to_sell <= 0:
                    pending_sell_signal = None
                    continue
                
                cash += qty_to_sell * exit_price
                holding_days = (current_date - entry_date).days
                return_pct = ((exit_price / position.entry_price) - 1) * 100
                return_jpy = (exit_price - position.entry_price) * qty_to_sell
                
                # Get entry score from signal metadata
                entry_score = position.entry_signal.metadata.get('score', 0.0)
                
                trade = Trade(
                    entry_date=entry_date.strftime('%Y-%m-%d') if hasattr(entry_date, 'strftime') else str(entry_date),
                    entry_price=position.entry_price,
                    entry_score=entry_score,
                    exit_date=current_date.strftime('%Y-%m-%d'),
                    exit_price=exit_price,
                    exit_reason=pending_sell_signal.reasons[0] if pending_sell_signal.reasons else "Unknown",
                    exit_urgency=pending_sell_signal.metadata.get('trigger', 'Unknown'),
                    holding_days=holding_days,
                    shares=qty_to_sell,
                    return_pct=return_pct,
                    return_jpy=return_jpy,
                    peak_price=position.peak_price_since_entry
                )
                trades.append(trade)
                
                profit_icon = "📈" if return_pct > 0 else "📉"
                trigger = pending_sell_signal.metadata.get('trigger', 'N/A')
                print(f"  {profit_icon} SELL {current_date.date()}: {qty_to_sell:,} shares @ ¥{exit_price:,.2f} "
                      f"({return_pct:+.2f}%, ¥{return_jpy:+,.0f}) - {trigger}")
                logger.info(f"SELL executed: {qty_to_sell} shares @ ¥{exit_price:.2f} ({return_pct:+.2f}%)")

                position.quantity -= qty_to_sell
                if position.quantity <= 0:
                    position = None
                pending_sell_signal = None
            
            # =====================================================================
            # STEP 2: GENERATE NEW SIGNALS (for tomorrow's execution)
            # =====================================================================
            
            # 使用 MarketDataBuilder 标准化数据并创建 MarketData 对象
            market_data = MarketDataBuilder.build_from_dataframes(
                ticker=ticker,
                current_date=current_date,
                df_features=df_features_historical,
                df_trades=df_trades_historical,
                df_financials=df_financials_historical,
                metadata=metadata
            )
            
            if position is None:
                # ENTRY LOGIC: No position, check for buy signal via v2
                try:
                    signal = generate_signal_v2(
                        market_data=market_data,
                        entry_strategy=entry_strategy
                    )

                    if signal.action == SignalAction.BUY:
                        pending_buy_signal = signal
                        score_display = signal.metadata.get('score', 'N/A')
                        logger.info(f"BUY SIGNAL generated on {current_date.date()} ({signal.strategy_name}, Score: {score_display})")
                except Exception as e:
                    logger.warning(f"Entry strategy failed on {current_date.date()}: {e}")
                    continue
            
            else:
                # EXIT LOGIC: Holding position, check for exit signal via v2
                # Update peak price (using today's close)
                position.peak_price_since_entry = max(position.peak_price_since_entry, current_close)
                
                try:
                    signal = generate_signal_v2(
                        market_data=market_data,
                        entry_strategy=entry_strategy,
                        exit_strategy=exit_strategy,
                        position=position
                    )

                    if signal.action == SignalAction.SELL:
                        pending_sell_signal = signal
                        logger.info(f"SELL SIGNAL generated on {current_date.date()} ({signal.strategy_name}: {signal.reasons[0] if signal.reasons else 'N/A'})")
                except Exception as e:
                    logger.warning(f"Exit strategy failed on {current_date.date()}: {e}")            
            # =====================================================================
            # STEP 3: RECORD DAILY EQUITY (for Beta & IR calculation)
            # =====================================================================
            if position is not None:
                # Holding position: value position at today's close
                position_value = position.quantity * current_close
                equity = cash + position_value
            else:
                # No position: equity = cash
                equity = cash
            
            daily_equity[current_date] = equity        
        
        # Build result
        return self._build_result(
            ticker=ticker,
            metadata=metadata,
            entry_strategy=entry_strategy,
            exit_strategy=exit_strategy,
            start_date=start_date,
            end_date=end_date,
            trades=trades,
            final_cash=cash,
            daily_equity=daily_equity
        )

    @staticmethod
    def _calculate_sell_quantity(ticker: str, total_qty: int, sell_pct: float) -> int:
        """Calculate sell quantity with lot-size-aware upward rounding."""
        if total_qty <= 0:
            return 0

        if sell_pct >= 0.999:
            return total_qty

        lot_size = LotSizeManager.get_lot_size(ticker)
        raw_qty = total_qty * max(sell_pct, 0.0)
        rounded_qty = int(math.ceil(raw_qty / lot_size) * lot_size)
        rounded_qty = min(total_qty, rounded_qty)

        if rounded_qty <= 0:
            rounded_qty = min(total_qty, lot_size)

        return rounded_qty
    
    def _build_result(
        self,
        ticker: str,
        metadata: dict,
        entry_strategy,  # BaseEntryStrategy or BaseScorer
        exit_strategy,   # BaseExitStrategy or BaseExiter
        start_date: str,
        end_date: str,
        trades: List[Trade],
        final_cash: float,
        daily_equity: dict
    ) -> BacktestResult:
        """Build BacktestResult from simulation data."""
        
        # Calculate metrics - use final equity from daily_equity which includes position value
        # daily_equity already accounts for cash + position value (see line 361-367)
        final_capital = list(daily_equity.values())[-1] if daily_equity else final_cash
        total_return_pct = ((final_capital / self.starting_capital) - 1) * 100
        annualized_return = calculate_annualized_return(total_return_pct, start_date, end_date)
        
        trade_stats = calculate_trade_statistics(trades)
        
        # Sharpe ratio from trade returns
        returns = [t.return_pct for t in trades]
        sharpe = calculate_sharpe_ratio(returns) if returns else 0.0
        
        # Build daily equity series for Beta/IR calculation
        equity_series = pd.Series(daily_equity)
        
        # Max drawdown from equity curve
        max_dd = calculate_max_drawdown(equity_series) if not equity_series.empty else 0.0
        
        # === NEW: Calculate Buy & Hold benchmark ===
        buy_hold_return_pct = None
        timing_alpha = None
        beat_buy_hold = None
        
        try:
            # Load stock price data
            from pathlib import Path
            features_path = Path(self.data_root) / 'features' / f'{ticker}_features.parquet'
            if features_path.exists():
                df_stock = pd.read_parquet(features_path)
                if 'Date' in df_stock.columns:
                    df_stock['Date'] = pd.to_datetime(df_stock['Date'])
                    df_stock = df_stock[(df_stock['Date'] >= start_date) & (df_stock['Date'] <= end_date)]
                    
                    if len(df_stock) > 0:
                        start_price = df_stock.iloc[0]['Close']
                        end_price = df_stock.iloc[-1]['Close']
                        buy_hold_return_pct = ((end_price - start_price) / start_price) * 100
                        
                        # Timing Alpha = 策略回报 - Buy&Hold回报
                        timing_alpha = total_return_pct - buy_hold_return_pct
                        beat_buy_hold = total_return_pct > buy_hold_return_pct
        except Exception as e:
            self.logger.warning(f"Could not calculate Buy&Hold benchmark: {e}")
        
        # Get strategy names
        entry_name = entry_strategy.strategy_name if hasattr(entry_strategy, 'strategy_name') else entry_strategy.__class__.__name__
        exit_name = exit_strategy.strategy_name if hasattr(exit_strategy, 'strategy_name') else exit_strategy.__class__.__name__
        
        return BacktestResult(
            ticker=ticker,
            ticker_name=metadata.get('company_name', 'Unknown'),
            scorer_name=entry_name,
            exiter_name=exit_name,
            start_date=start_date,
            end_date=end_date,
            starting_capital_jpy=self.starting_capital,
            final_capital_jpy=final_capital,
            total_return_pct=total_return_pct,
            annualized_return_pct=annualized_return,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd,
            num_trades=trade_stats['num_trades'],
            win_rate_pct=trade_stats['win_rate_pct'],
            avg_gain_pct=trade_stats['avg_gain_pct'],
            avg_loss_pct=trade_stats['avg_loss_pct'],
            avg_holding_days=trade_stats['avg_holding_days'],
            profit_factor=trade_stats['profit_factor'],
            buy_hold_return_pct=buy_hold_return_pct,
            timing_alpha=timing_alpha,
            beat_buy_hold=beat_buy_hold,
            trades=trades,
            _daily_equity_series=equity_series  # Store for later Beta/IR calculation
        )
    
    def _empty_result(
        self,
        ticker: str,
        metadata: dict,
        entry_strategy,
        exit_strategy,
        start_date: str,
        end_date: str
    ) -> BacktestResult:
        """Create empty result for failed backtests."""
        entry_name = entry_strategy.strategy_name if hasattr(entry_strategy, 'strategy_name') else entry_strategy.__class__.__name__
        exit_name = exit_strategy.strategy_name if hasattr(exit_strategy, 'strategy_name') else exit_strategy.__class__.__name__
        
        return BacktestResult(
            ticker=ticker,
            ticker_name=metadata.get('company_name', 'Unknown'),
            scorer_name=entry_name,
            exiter_name=exit_name,
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
            profit_factor=0.0,
            trades=[]
        )


def calculate_benchmark_return(
    start_date: str,
    end_date: str,
    data_root: str = './data'
) -> float:
    """
    Calculate TOPIX buy-and-hold return from local cached data.
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        data_root: Root directory for data files
        
    Returns:
        TOPIX total return percentage
    """
    logger.info("Calculating TOPIX benchmark return from local data...")
    
    # Use BenchmarkManager to load cached data
    manager = BenchmarkManager(client=None, data_root=data_root)
    benchmark_return = manager.calculate_benchmark_return(
        start_date, 
        end_date, 
        use_cached=True
    )
    
    if benchmark_return is None:
        logger.warning("TOPIX data not available. Run main.py first to fetch benchmarks.")
        return 0.0
    
    return benchmark_return


def backtest_strategy(
    ticker: str,
    entry_strategy: BaseEntryStrategy,
    exit_strategy: BaseExitStrategy,
    start_date: str = "2021-01-01",
    end_date: str = "2026-01-08",
    starting_capital_jpy: float = 5_000_000,
    overlay_manager: Optional[OverlayManager] = None,
) -> BacktestResult:
    """
    Convenience function: Backtest single strategy on single ticker.
    
    Args:
        ticker: Stock code
        entry_strategy: Entry strategy
        exit_strategy: Exit strategy
        start_date: Backtest start
        end_date: Backtest end
        starting_capital_jpy: Starting capital
        
    Returns:
        BacktestResult
    """
    engine = BacktestEngine(
        starting_capital_jpy=starting_capital_jpy,
        overlay_manager=overlay_manager,
    )
    return engine.backtest_strategy(ticker, entry_strategy, exit_strategy, start_date, end_date)


def backtest_strategies(
    tickers: List[str],
    strategies: List[Tuple[BaseEntryStrategy, BaseExitStrategy]],
    start_date: str = "2021-01-01",
    end_date: str = "2026-01-08",
    starting_capital_jpy: float = 5_000_000,
    include_benchmark: bool = True,
    data_root: str = './data',
    overlay_manager: Optional[OverlayManager] = None,
) -> pd.DataFrame:
    """
    Backtest multiple strategies on multiple tickers.
    
    Args:
        tickers: List of stock codes
        strategies: List of (scorer, exiter) tuples
        start_date: Backtest start
        end_date: Backtest end
        starting_capital_jpy: Starting capital
        include_benchmark: Whether to include TOPIX comparison
        data_root: Root directory for data files
        
    Returns:
        DataFrame with results for all combinations
    """
    engine = BacktestEngine(
        starting_capital_jpy=starting_capital_jpy,
        data_root=data_root,
        overlay_manager=overlay_manager,
    )
    
    # Fetch benchmark once (from local cache)
    benchmark_return = None
    if include_benchmark:
        benchmark_return = calculate_benchmark_return(start_date, end_date, data_root)
        if benchmark_return == 0.0:
            logger.warning("TOPIX comparison disabled (no cached data)")
            benchmark_return = None
    
    # Run all combinations
    results = []
    total_runs = len(tickers) * len(strategies)
    current_run = 0
    
    for ticker in tickers:
        for entry_strategy, exit_strategy in strategies:
            current_run += 1
            logger.info(f"Progress: {current_run}/{total_runs}")
            
            # Print strategy separator
            strategy_name = f"{entry_strategy.strategy_name} + {exit_strategy.strategy_name}"
            print("\n" + "─" * 80)
            print(f"策略 {current_run}/{total_runs}: {ticker} × {strategy_name}")
            print("─" * 80)
            
            result = engine.backtest_strategy(ticker, entry_strategy, exit_strategy, start_date, end_date)
            
            # Add benchmark comparison
            if benchmark_return is not None:
                result.benchmark_return_pct = benchmark_return
                
                # 总Alpha = 策略回报 - TOPIX回报 (包含择时+选股)
                result.alpha = result.total_return_pct - benchmark_return
                result.beat_benchmark = result.alpha > 0
                
                # 选股Alpha = Buy&Hold回报 - TOPIX回报 (纯选股能力)
                if result.buy_hold_return_pct is not None:
                    result.stock_selection_alpha = result.buy_hold_return_pct - benchmark_return
                
                # Calculate Beta and Information Ratio
                if result._daily_equity_series is not None and not result._daily_equity_series.empty:
                    result.beta = calculate_beta(
                        result._daily_equity_series,
                        start_date,
                        end_date,
                        data_root
                    )
                    
                    result.tracking_error, result.information_ratio = calculate_tracking_error_and_ir(
                        result._daily_equity_series,
                        result.alpha,
                        start_date,
                        end_date,
                        data_root
                    )
            
            results.append(result)
    
    # Convert to DataFrame
    df = pd.DataFrame([r.to_dict() for r in results])
    
    logger.info(f"Backtest complete: {len(results)} results")
    return df
