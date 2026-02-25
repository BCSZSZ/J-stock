"""
Portfolio Backtest Engine - 组合投资回测引擎
Backtests portfolio strategies with multiple concurrent positions
"""

import logging
import math
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from ..analysis.signals import MarketData, SignalAction, TradingSignal
from ..analysis.filters import EntrySecondaryFilter
from ..analysis.strategies.base_entry_strategy import BaseEntryStrategy
from ..analysis.strategies.base_exit_strategy import BaseExitStrategy
from ..data.benchmark_manager import BenchmarkManager
from ..data.market_data_builder import MarketDataBuilder
from ..data.stock_data_manager import StockDataManager
from ..overlays import OverlayContext, OverlayManager
from ..signal_generator import generate_signal_v2
from .lot_size_manager import LotSizeManager
from .models import BacktestResult, Trade
from .portfolio import Portfolio, Position
from .signal_ranker import SignalRanker

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
        data_root: str = "./data",
        overlay_manager: Optional[OverlayManager] = None,
        preloaded_cache: Optional["BacktestDataCache"] = None,
        entry_filter_config: Optional[Dict] = None,
    ):
        """
        Args:
            starting_capital: 起始资金
            max_positions: 最大持仓数
            max_position_pct: 单股最大仓位
            min_position_pct: 单股最小仓位
            signal_ranking_method: 信号排序方法
            data_root: 数据根目录
            overlay_manager: Overlay管理器
            preloaded_cache: 预加载的数据缓存（可选，用于性能优化）
            entry_filter_config: 入场二级过滤配置（可选）
        """
        self.starting_capital = starting_capital
        self.max_positions = max_positions
        self.max_position_pct = max_position_pct
        self.min_position_pct = min_position_pct
        self.data_root = data_root
        self.overlay_manager = overlay_manager
        self.preloaded_cache = preloaded_cache
        self.entry_filter = EntrySecondaryFilter.from_dict(entry_filter_config)

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
        show_signal_ranking: bool = True,
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
        strategy_name = (
            f"{entry_strategy.strategy_name} + {exit_strategy.strategy_name}"
        )
        logger.info(f"Backtesting Portfolio: {strategy_name}")
        logger.info(f"Stock pool: {tickers}")

        # 创建组合
        portfolio = Portfolio(
            starting_cash=self.starting_capital,
            max_positions=self.max_positions,
            max_position_pct=self.max_position_pct,
            min_position_pct=self.min_position_pct,
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
            return self._empty_result(
                tickers, entry_strategy, exit_strategy, start_date, end_date
            )

        # 获取交易日历（取所有股票的交易日并集）
        trading_days = self._get_trading_calendar(all_data, start_date, end_date)

        if not trading_days:
            logger.warning("No trading days in date range")
            return self._empty_result(
                tickers, entry_strategy, exit_strategy, start_date, end_date
            )

        # 回测状态
        trades: List[Trade] = []
        daily_equity = {}

        # 待执行订单（信号今天生成，明天执行）
        pending_buy_signals: Dict[str, TradingSignal] = {}
        pending_sell_signals: Dict[str, TradingSignal] = {}

        benchmark_data = None
        if self.overlay_manager and self.overlay_manager.needs_benchmark_data:
            manager = BenchmarkManager(client=None, data_root=self.data_root)
            benchmark_data = manager.get_topix_data()

        # 每日循环
        for i, current_date in enumerate(trading_days):
            executed_buys = []
            executed_sells = []
            current_prices = self._get_current_prices(all_data, current_date)

            overlay_decision = None
            if self.overlay_manager:
                total_value = portfolio.get_total_value(current_prices)
                overlay_context = OverlayContext(
                    current_date=current_date,
                    portfolio_cash=portfolio.cash,
                    portfolio_value=total_value,
                    positions=portfolio.positions,
                    current_prices=current_prices,
                    benchmark_data=benchmark_data,
                )
                overlay_decision, _ = self.overlay_manager.evaluate(overlay_context)
                if overlay_decision.force_exit:
                    for ticker, position in portfolio.positions.items():
                        if ticker not in pending_sell_signals:
                            pending_sell_signals[ticker] = TradingSignal(
                                action=SignalAction.SELL,
                                confidence=1.0,
                                reasons=["Overlay force exit"],
                                metadata={"trigger": "OVERLAY_FORCE_EXIT"},
                                strategy_name="Overlay",
                            )
                if overlay_decision.exit_overrides:
                    for ticker, reason in overlay_decision.exit_overrides.items():
                        if ticker in portfolio.positions:
                            pending_sell_signals[ticker] = TradingSignal(
                                action=SignalAction.SELL,
                                confidence=1.0,
                                reasons=[reason],
                                metadata={"trigger": "OVERLAY_EXIT"},
                                strategy_name="Overlay",
                            )

            # ================================================================
            # STEP 1: 执行待执行的卖出订单（释放资金）
            # ================================================================
            for ticker in list(pending_sell_signals.keys()):
                if ticker in portfolio.positions:
                    sell_signal = pending_sell_signals[ticker]
                    position = portfolio.positions[ticker]

                    # 获取卖出价格（明天开盘价）
                    exit_price = self._get_next_open_price(
                        all_data[ticker], current_date
                    )

                    if exit_price is None:
                        continue

                    # 支持部分卖出：默认全卖
                    sell_pct = float(sell_signal.metadata.get("sell_percentage", 1.0))
                    qty_to_sell = self._calculate_sell_quantity(
                        ticker=ticker,
                        total_qty=position.quantity,
                        sell_pct=sell_pct,
                    )

                    if qty_to_sell <= 0:
                        continue

                    entry_price = position.entry_price
                    entry_date = position.entry_date
                    peak_price = position.peak_price_since_entry
                    entry_score = position.entry_signal.metadata.get("score", 0.0)
                    entry_confidence = position.entry_signal.confidence
                    entry_metadata = position.entry_signal.metadata

                    # 执行卖出
                    proceeds = portfolio.close_partial_position(
                        ticker=ticker,
                        quantity=qty_to_sell,
                        exit_price=exit_price,
                    )

                    if proceeds is not None:
                        # 记录交易
                        holding_days = (current_date - entry_date).days
                        return_pct = ((exit_price / entry_price) - 1) * 100
                        return_jpy = (exit_price - entry_price) * qty_to_sell

                        trade = Trade(
                            ticker=ticker,
                            entry_date=entry_date.strftime("%Y-%m-%d"),
                            entry_price=entry_price,
                            entry_score=entry_score,
                            entry_confidence=entry_confidence,
                            entry_metadata=entry_metadata,
                            exit_date=current_date.strftime("%Y-%m-%d"),
                            exit_price=exit_price,
                            exit_reason=sell_signal.reasons[0]
                            if sell_signal.reasons
                            else "Unknown",
                            exit_urgency=sell_signal.metadata.get("trigger", "Unknown"),
                            holding_days=holding_days,
                            shares=qty_to_sell,
                            return_pct=return_pct,
                            return_jpy=return_jpy,
                            peak_price=peak_price,
                        )
                        trades.append(trade)

                        profit_icon = "↑" if return_pct > 0 else "↓"
                        trigger = sell_signal.metadata.get("trigger", "N/A")
                        executed_sells.append(
                            f"{profit_icon} SELL {current_date.date()} {ticker}: {qty_to_sell:,} shares @ ¥{exit_price:,.2f} "
                            f"({return_pct:+.2f}%, ¥{return_jpy:+,.0f}) - {trigger}"
                        )

                del pending_sell_signals[ticker]

            # ================================================================
            # STEP 2: 执行待执行的买入订单
            # ================================================================
            if pending_buy_signals:
                if overlay_decision and overlay_decision.block_new_entries:
                    pending_buy_signals.clear()
                else:
                    max_new_positions = (
                        overlay_decision.max_new_positions if overlay_decision else None
                    )
                    new_positions_opened = 0

                    # 对买入信号排序
                    market_data_dict = {
                        ticker: self._build_market_data(
                            ticker, all_data[ticker], current_date
                        )
                        for ticker in pending_buy_signals.keys()
                        if ticker in all_data
                    }

                    ranked_signals = self.signal_ranker.rank_buy_signals(
                        pending_buy_signals, market_data_dict
                    )

                    # 依次尝试买入
                    for ticker, buy_signal, priority in ranked_signals:
                        if max_new_positions is not None:
                            if new_positions_opened >= max_new_positions:
                                break
                        # 检查是否已达持仓上限
                        if not portfolio.can_open_new_position():
                            if show_signal_ranking:
                                print(
                                    f"  ⚠️  已达最大持仓数 {portfolio.max_positions}，跳过剩余信号"
                                )
                            break

                        # 检查是否已持有
                        if portfolio.has_position(ticker):
                            continue

                        # 获取买入价格（明天开盘价）
                        entry_price = self._get_next_open_price(
                            all_data[ticker], current_date
                        )

                        if entry_price is None:
                            continue

                        # 计算可用资金
                        max_cash = portfolio.calculate_max_position_size(current_prices)
                        if (
                            overlay_decision
                            and overlay_decision.position_scale is not None
                        ):
                            max_cash *= overlay_decision.position_scale

                        if (
                            overlay_decision
                            and overlay_decision.target_exposure is not None
                        ):
                            total_value = portfolio.get_total_value(current_prices)
                            invested = total_value - portfolio.cash
                            max_invested = (
                                total_value * overlay_decision.target_exposure
                            )
                            available_exposure = max(0.0, max_invested - invested)
                            max_cash = min(max_cash, available_exposure)

                        # 计算可购买股数（考虑lot size）
                        shares = LotSizeManager.calculate_buyable_shares(
                            ticker, max_cash, entry_price
                        )

                        if shares > 0:
                            # 创建持仓
                            position = Position(
                                ticker=ticker,
                                quantity=shares,
                                entry_price=entry_price,
                                entry_date=current_date,
                                entry_signal=buy_signal,
                                peak_price_since_entry=entry_price,
                            )

                            # 添加到组合
                            if portfolio.add_position(position):
                                score_display = buy_signal.metadata.get("score", "N/A")
                                executed_buys.append(
                                    f"[BUY] {current_date.date()} {ticker}: {shares:,} shares @ {entry_price:,.2f}JPY "
                                    f"(Score: {score_display})"
                                )
                                new_positions_opened += 1

                pending_buy_signals.clear()

            if executed_buys or executed_sells:
                print(f"\n交易 ({current_date.date()}):")
                print("  买入:")
                if executed_buys:
                    for line in executed_buys:
                        print(f"    {line}")
                else:
                    print("    无")
                print("  卖出:")
                if executed_sells:
                    for line in executed_sells:
                        print(f"    {line}")
                else:
                    print("    无")

            # ================================================================
            # STEP 3: 生成新的信号（为明天准备）
            # ================================================================
            buy_signals_today: Dict[str, TradingSignal] = {}
            sell_signals_today: Dict[str, TradingSignal] = {}

            for ticker in tickers:
                if ticker not in all_data:
                    continue

                market_data = self._build_market_data(
                    ticker, all_data[ticker], current_date
                )

                if market_data is None:
                    continue

                # 生成入场信号（对所有未持仓的股票）
                if not portfolio.has_position(ticker):
                    entry_signal = generate_signal_v2(
                        market_data=market_data, entry_strategy=entry_strategy
                    )
                    if entry_signal.action == SignalAction.BUY:
                        if not self.entry_filter.passes(market_data):
                            continue
                        buy_signals_today[ticker] = entry_signal

                # 生成出场信号（仅对已持仓的股票）
                if portfolio.has_position(ticker):
                    position = portfolio.positions[ticker]
                    exit_signal = generate_signal_v2(
                        market_data=market_data,
                        entry_strategy=entry_strategy,
                        exit_strategy=exit_strategy,
                        position=position,
                    )
                    if exit_signal.action == SignalAction.SELL:
                        sell_signals_today[ticker] = exit_signal

            if buy_signals_today or sell_signals_today:
                print(f"\n信号 ({current_date.date()}):")
                print("  买入信号:")
                if buy_signals_today:
                    if show_signal_ranking:
                        market_data_dict = {
                            ticker: self._build_market_data(
                                ticker, all_data[ticker], current_date
                            )
                            for ticker in buy_signals_today.keys()
                            if ticker in all_data
                        }
                        ranked_signals = self.signal_ranker.rank_buy_signals(
                            buy_signals_today, market_data_dict
                        )
                        for rank, (ticker, signal, priority) in enumerate(
                            ranked_signals[:5], 1
                        ):
                            score = signal.metadata.get("score", "N/A")
                            print(
                                f"    #{rank} {ticker}: Score={score}, Priority={priority:.1f}"
                            )
                    else:
                        for ticker, signal in list(buy_signals_today.items())[:5]:
                            score = signal.metadata.get("score", "N/A")
                            print(f"    {ticker}: Score={score}")
                else:
                    print("    无")

                print("  卖出信号:")
                if sell_signals_today:
                    for ticker, signal in list(sell_signals_today.items())[:5]:
                        trigger = signal.metadata.get("trigger", "N/A")
                        print(f"    {ticker}: {trigger}")
                else:
                    print("    无")

            pending_buy_signals = buy_signals_today
            pending_sell_signals = sell_signals_today

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
                print(f"\n  [Portfolio] 组合状态 ({current_date.date()}):")
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
            current_prices=current_prices,
        )

    def _calculate_sell_quantity(
        self, ticker: str, total_qty: int, sell_pct: float
    ) -> int:
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

    def _load_stock_data(self, ticker: str) -> Dict:
        """
        加载单只股票的数据

        优先从预加载缓存读取，缓存未命中时从磁盘加载。
        """
        # 优先使用预加载缓存（性能优化）
        if self.preloaded_cache and self.preloaded_cache.has_ticker(ticker):
            return {
                "features": self.preloaded_cache.get_features(ticker),
                "trades": self.preloaded_cache.get_trades(ticker),
                "financials": self.preloaded_cache.get_financials(ticker),
                "metadata": self.preloaded_cache.get_metadata(ticker),
            }

        # 缓存未命中，从磁盘加载（传统方式）
        features_path = Path(self.data_root) / "features" / f"{ticker}_features.parquet"
        trades_path = Path(self.data_root) / "raw_trades" / f"{ticker}_trades.parquet"
        financials_path = (
            Path(self.data_root) / "raw_financials" / f"{ticker}_financials.parquet"
        )
        metadata_path = Path(self.data_root) / "metadata" / f"{ticker}_metadata.json"

        if not features_path.exists():
            raise FileNotFoundError(f"Features file not found: {features_path}")

        data_manager = StockDataManager(api_key=None, data_root=self.data_root)
        df_features = data_manager.load_stock_features(ticker)
        if df_features.empty:
            raise FileNotFoundError(f"Features file empty: {features_path}")
        df_features["Date"] = pd.to_datetime(df_features["Date"])
        df_features.set_index("Date", inplace=True)

        df_trades = (
            pd.read_parquet(trades_path) if trades_path.exists() else pd.DataFrame()
        )
        df_financials = (
            pd.read_parquet(financials_path)
            if financials_path.exists()
            else pd.DataFrame()
        )

        metadata = data_manager.load_metadata(ticker)

        return {
            "features": df_features,
            "trades": df_trades,
            "financials": df_financials,
            "metadata": metadata,
        }

    def _get_trading_calendar(
        self, all_data: Dict[str, Dict], start_date: str, end_date: str
    ) -> List[pd.Timestamp]:
        """获取交易日历（所有股票的交易日并集）"""
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)

        all_dates = set()
        for data in all_data.values():
            df = data["features"]
            dates = df.index[(df.index >= start) & (df.index <= end)]
            all_dates.update(dates)

        return sorted(list(all_dates))

    def _get_current_prices(
        self, all_data: Dict[str, Dict], current_date: pd.Timestamp
    ) -> Dict[str, float]:
        """获取所有股票的当前价格"""
        prices = {}
        for ticker, data in all_data.items():
            df = data["features"]
            if current_date in df.index:
                prices[ticker] = df.loc[current_date, "Close"]
        return prices

    def _get_next_open_price(
        self, data: Dict, current_date: pd.Timestamp
    ) -> Optional[float]:
        """获取下一个交易日的开盘价"""
        df = data["features"]
        if current_date not in df.index:
            return None
        return df.loc[current_date, "Open"]

    def _build_market_data(
        self, ticker: str, data: Dict, current_date: pd.Timestamp
    ) -> Optional[MarketData]:
        """使用 MarketDataBuilder 构建 MarketData 对象"""
        df = data["features"]

        if current_date not in df.index:
            return None

        df_historical = df[df.index <= current_date]

        return MarketDataBuilder.build_from_dataframes(
            ticker=ticker,
            current_date=current_date,
            df_features=df_historical,
            df_trades=data["trades"],
            df_financials=data["financials"],
            metadata=data["metadata"],
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
        current_prices: Dict[str, float],
    ) -> BacktestResult:
        """构建组合回测结果"""

        final_value = portfolio.get_total_value(current_prices)
        total_return_pct = ((final_value / self.starting_capital) - 1) * 100

        # 计算年化回报
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        years = (end - start).days / 365.25
        annualized_return = (
            ((final_value / self.starting_capital) ** (1 / years) - 1) * 100
            if years > 0
            else 0
        )

        # 计算其他指标
        winning_trades = [t for t in trades if t.return_pct > 0]
        losing_trades = [t for t in trades if t.return_pct <= 0]

        win_rate = len(winning_trades) / len(trades) * 100 if trades else 0
        avg_gain = (
            sum(t.return_pct for t in winning_trades) / len(winning_trades)
            if winning_trades
            else 0
        )
        avg_loss = (
            sum(t.return_pct for t in losing_trades) / len(losing_trades)
            if losing_trades
            else 0
        )

        # 计算最大回撤
        max_drawdown_pct = self._calculate_max_drawdown(daily_equity)

        # 计算夏普比率
        sharpe_ratio = self._calculate_sharpe_ratio(daily_equity, years)

        # 计算盈亏比
        profit_factor = self._calculate_profit_factor(winning_trades, losing_trades)

        # 计算TOPIX基准收益
        benchmark_return_pct = None
        alpha = None
        beat_benchmark = None

        try:
            manager = BenchmarkManager(client=None, data_root=self.data_root)
            benchmark_return_pct = manager.calculate_benchmark_return(
                start_date, end_date, use_cached=True
            )

            if benchmark_return_pct is not None:
                alpha = total_return_pct - benchmark_return_pct
                beat_benchmark = total_return_pct > benchmark_return_pct
        except Exception as e:
            logger.warning(f"Failed to calculate benchmark: {e}")

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
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_drawdown_pct,
            num_trades=len(trades),
            win_rate_pct=win_rate,
            avg_gain_pct=avg_gain,
            avg_loss_pct=avg_loss,
            avg_holding_days=sum(t.holding_days for t in trades) / len(trades)
            if trades
            else 0,
            profit_factor=profit_factor,
            benchmark_return_pct=benchmark_return_pct,
            alpha=alpha,
            beat_benchmark=beat_benchmark,
            trades=trades,
        )

    def _empty_result(
        self, tickers, entry_strategy, exit_strategy, start_date, end_date
    ) -> BacktestResult:
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
            profit_factor=0.0,
            trades=[],
        )

    def _calculate_max_drawdown(self, daily_equity: Dict) -> float:
        """
        计算最大回撤百分比

        Args:
            daily_equity: 每日资产价值字典 {date: value}

        Returns:
            最大回撤百分比 (正数表示下跌)
        """
        if not daily_equity or len(daily_equity) < 2:
            return 0.0

        # 转换为Series并排序
        equity_series = pd.Series(daily_equity).sort_index()

        # 计算累积最高值
        cumulative_max = equity_series.expanding().max()

        # 计算回撤（当前值相对于历史最高值的下跌）
        drawdown = (equity_series - cumulative_max) / cumulative_max * 100

        # 最大回撤（绝对值）
        max_drawdown = abs(drawdown.min())

        return max_drawdown

    def _calculate_sharpe_ratio(self, daily_equity: Dict, years: float) -> float:
        """
        计算夏普比率

        Args:
            daily_equity: 每日资产价值字典 {date: value}
            years: 回测年数

        Returns:
            夏普比率（年化）
        """
        if not daily_equity or len(daily_equity) < 2:
            return 0.0

        # 转换为Series并排序
        equity_series = pd.Series(daily_equity).sort_index()

        # 计算每日收益率
        daily_returns = equity_series.pct_change().dropna()

        if len(daily_returns) == 0:
            return 0.0

        # 计算年化收益率（平均值）
        avg_daily_return = daily_returns.mean()

        # 计算年化波动率（标准差）
        daily_std = daily_returns.std()

        if daily_std == 0:
            return 0.0

        # 假设一年252个交易日
        trading_days_per_year = 252

        # 年化夏普比率（假设无风险利率为0）
        sharpe_ratio = (avg_daily_return / daily_std) * (trading_days_per_year**0.5)

        return sharpe_ratio

    def _calculate_profit_factor(
        self, winning_trades: List, losing_trades: List
    ) -> float:
        """
        计算盈亏比（Profit Factor）

        盈亏比 = 总盈利金额 / 总亏损金额（绝对值）

        Args:
            winning_trades: 盈利交易列表
            losing_trades: 亏损交易列表

        Returns:
            盈亏比（>1表示盈利大于亏损）
        """
        if not winning_trades and not losing_trades:
            return 0.0

        # 计算总盈利
        total_profit = sum(t.return_jpy for t in winning_trades)

        # 计算总亏损（绝对值）
        total_loss = abs(sum(t.return_jpy for t in losing_trades))

        if total_loss == 0:
            # 没有亏损交易
            return float("inf") if total_profit > 0 else 0.0

        profit_factor = total_profit / total_loss

        return profit_factor
