"""
Production Signal Generator

Generates trading signals for production portfolio management.
Default operation uses a single strategy group, while keeping multi-group compatibility.
- Evaluates entry signals for non-position stocks
- Evaluates exit signals for open positions
- Outputs daily signal file for reporting/UI
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from ..analysis.signals import MarketData, Position, SignalAction, TradingSignal
from ..analysis.strategies.base_entry_strategy import BaseEntryStrategy
from ..analysis.strategies.base_exit_strategy import BaseExitStrategy
from ..data.market_data_builder import MarketDataBuilder
from ..data.stock_data_manager import StockDataManager
from ..signal_generator import generate_signal_v2
from ..utils.strategy_loader import create_strategy_instance
from .state_manager import ProductionState, StrategyGroupState


@dataclass
class Signal:
    """Production trading signal"""

    group_id: str
    ticker: str
    ticker_name: str
    signal_type: str  # "BUY", "SELL", "HOLD", "EXIT"
    action: str  # "BUY", "SELL_25%", "SELL_50%", "SELL_75%", "SELL_100%", "HOLD"
    confidence: float  # 0-1
    score: float  # 0-100 (for entry signals)
    reason: str  # Human-readable explanation
    current_price: float

    # For SELL signals
    position_qty: Optional[int] = None
    entry_price: Optional[float] = None
    entry_date: Optional[str] = None
    holding_days: Optional[int] = None
    unrealized_pl_pct: Optional[float] = None

    # For BUY signals
    suggested_qty: Optional[int] = None
    required_capital: Optional[float] = None

    # Metadata
    strategy_name: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class SignalGenerator:
    """
    Generate trading signals for all strategy groups.

    Workflow:
    1. Load strategy configurations
    2. For each strategy group:
       a. Evaluate exit signals for open positions
       b. Evaluate entry signals for monitor list stocks (excluding positions)
    3. Output signals_YYYY-MM-DD.json
    """

    def __init__(
        self, config: dict, data_manager: StockDataManager, state: ProductionState
    ):
        """
        Initialize SignalGenerator.

        Args:
            config: Production config from config.json
            data_manager: StockDataManager instance for data loading
            state: ProductionState instance for position tracking
        """
        self.config = config
        self.data_manager = data_manager
        self.state = state

        # Strategy cache (loaded on-demand)
        self._strategy_cache: Dict[str, BaseEntryStrategy] = {}
        self._exit_strategy_cache: Dict[str, BaseExitStrategy] = {}

        # Load monitor list
        monitor_file = config.get("monitor_list_file", "data/monitor_list.json")
        with open(monitor_file, "r", encoding="utf-8") as f:
            monitor_data = json.load(f)
            # Extract ticker codes from tickers array
            tickers_data = monitor_data.get("tickers", [])
            self.monitor_list = [
                t["code"] if isinstance(t, dict) else t for t in tickers_data
            ]

    def _load_entry_strategy(self, strategy_name: str) -> BaseEntryStrategy:
        """使用 strategy_loader 统一加载入场策略"""
        if strategy_name in self._strategy_cache:
            return self._strategy_cache[strategy_name]

        strategy = create_strategy_instance(strategy_name, strategy_type="entry")
        self._strategy_cache[strategy_name] = strategy
        return strategy

    def _load_exit_strategy(self, strategy_name: str) -> BaseExitStrategy:
        """使用 strategy_loader 统一加载出场策略"""
        if strategy_name in self._exit_strategy_cache:
            return self._exit_strategy_cache[strategy_name]

        strategy = create_strategy_instance(strategy_name, strategy_type="exit")
        self._exit_strategy_cache[strategy_name] = strategy
        return strategy

    def evaluate_all_groups(
        self, current_date: str, verbose: bool = False
    ) -> Dict[str, List[Signal]]:
        """
        Generate signals for all strategy groups.

        Args:
            current_date: ISO format "YYYY-MM-DD"
            verbose: Print detailed progress

        Returns:
            Dict mapping group_id to list of Signal objects
        """
        all_signals = {}

        strategy_groups = self.config.get("strategy_groups", [])

        for group_config in strategy_groups:
            group_id = group_config["id"]

            if verbose:
                print(f"\n📊 Evaluating {group_id} ({group_config['name']})...")

            signals = self._evaluate_group(
                group_id=group_id,
                group_config=group_config,
                current_date=current_date,
                verbose=verbose,
            )

            all_signals[group_id] = signals

            if verbose:
                buy_count = len([s for s in signals if s.signal_type == "BUY"])
                sell_count = len(
                    [s for s in signals if s.signal_type in ["SELL", "EXIT"]]
                )
                print(f"   Signals: {buy_count} BUY, {sell_count} SELL")

        return all_signals

    def _evaluate_group(
        self,
        group_id: str,
        group_config: dict,
        current_date: str,
        verbose: bool = False,
    ) -> List[Signal]:
        """
        Generate signals for a single strategy group.

        Returns:
            List of Signal objects (BUY + SELL)
        """
        signals = []

        # Get strategy group state
        group = self.state.get_group(group_id)
        if not group:
            print(f"⚠️  Group {group_id} not found in state")
            return signals

        # Load strategies
        entry_strategy_name = group_config["entry_strategy"]
        exit_strategy_name = group_config["exit_strategy"]

        entry_strategy = self._load_entry_strategy(entry_strategy_name)
        exit_strategy = self._load_exit_strategy(exit_strategy_name)

        # 1. Evaluate EXIT signals for open positions
        for position in group.positions:
            if position.quantity <= 0:
                continue

            exit_signal = self._evaluate_exit(
                group_id=group_id,
                position=position,
                exit_strategy=exit_strategy,
                current_date=current_date,
                verbose=verbose,
            )

            if exit_signal:
                signals.append(exit_signal)

        # 2. Evaluate ENTRY signals for monitor list (exclude positions)
        position_tickers = set(
            pos.ticker for pos in group.positions if pos.quantity > 0
        )

        for ticker in self.monitor_list:
            if ticker in position_tickers:
                continue  # Skip stocks we already hold

            entry_signal = self._evaluate_entry(
                group_id=group_id,
                group=group,
                ticker=ticker,
                entry_strategy=entry_strategy,
                current_date=current_date,
                verbose=verbose,
            )

            if entry_signal and entry_signal.signal_type == "BUY":
                signals.append(entry_signal)

        return signals

    def _evaluate_exit(
        self,
        group_id: str,
        position,  # Phase 2 Position
        exit_strategy: BaseExitStrategy,
        current_date: str,
        verbose: bool = False,
    ) -> Optional[Signal]:
        """Evaluate exit signal for a position"""
        ticker = position.ticker

        try:
            # Load market data
            market_data = self._load_market_data(ticker, current_date)

            if market_data is None:
                if verbose:
                    print(f"   ⚠️  {ticker}: No data")
                return None

            # Convert Phase 2 Position to signals.Position
            signals_position = Position(
                ticker=ticker,
                entry_price=position.entry_price,
                entry_date=pd.Timestamp(position.entry_date),
                quantity=position.quantity,
                entry_signal=TradingSignal(
                    action=SignalAction.BUY,
                    confidence=position.entry_score / 100.0,
                    reasons=["Entry"],
                    metadata={"score": position.entry_score},
                    strategy_name="Entry",
                ),
                peak_price_since_entry=position.peak_price,
            )

            # Update peak price
            current_price = market_data.latest_price
            if current_price > signals_position.peak_price_since_entry:
                signals_position.peak_price_since_entry = current_price
                position.peak_price = current_price  # Update Phase 2 position

            # Generate exit signal via unified v2
            trading_signal = generate_signal_v2(
                market_data=market_data,
                exit_strategy=exit_strategy,
                position=signals_position,
            )

            # Convert to Production Signal
            if trading_signal.action == SignalAction.SELL:
                # Parse sell percentage from metadata
                sell_pct = trading_signal.metadata.get("sell_percentage", 1.0)

                if sell_pct >= 0.9:
                    action = "SELL_100%"
                elif sell_pct >= 0.7:
                    action = "SELL_75%"
                elif sell_pct >= 0.45:
                    action = "SELL_50%"
                else:
                    action = "SELL_25%"

                holding_days = (
                    pd.Timestamp(current_date) - pd.Timestamp(position.entry_date)
                ).days

                return Signal(
                    group_id=group_id,
                    ticker=ticker,
                    ticker_name=ticker,  # TODO: lookup name
                    signal_type="SELL",
                    action=action,
                    confidence=trading_signal.confidence,
                    score=0.0,  # N/A for exit
                    reason=", ".join(trading_signal.reasons),
                    current_price=current_price,
                    position_qty=position.quantity,
                    entry_price=position.entry_price,
                    entry_date=position.entry_date,
                    holding_days=holding_days,
                    unrealized_pl_pct=signals_position.current_pnl_pct(current_price),
                    strategy_name=exit_strategy.strategy_name,
                )
            else:
                # HOLD - no signal needed
                return None

        except Exception as e:
            if verbose:
                print(f"   ⚠️  {ticker} exit error: {e}")
            return None

    def _evaluate_entry(
        self,
        group_id: str,
        group: StrategyGroupState,
        ticker: str,
        entry_strategy: BaseEntryStrategy,
        current_date: str,
        verbose: bool = False,
    ) -> Optional[Signal]:
        """Evaluate entry signal for a ticker"""
        try:
            # Load market data
            market_data = self._load_market_data(ticker, current_date)

            if market_data is None:
                if verbose:
                    print(f"   ⚠️  {ticker}: No data")
                return None

            # Generate entry signal via unified v2
            trading_signal = generate_signal_v2(
                market_data=market_data, entry_strategy=entry_strategy
            )

            # Check buy threshold
            buy_threshold = self.config.get("buy_threshold", 65)
            score = trading_signal.metadata.get("score", 0)

            if trading_signal.action == SignalAction.BUY and score >= buy_threshold:
                current_price = market_data.latest_price

                # Calculate suggested quantity
                max_position_pct = self.config.get("max_position_pct", 0.30)
                max_position_value = group.cash * max_position_pct

                suggested_qty = (
                    int(max_position_value / current_price) if current_price > 0 else 0
                )
                required_capital = suggested_qty * current_price

                return Signal(
                    group_id=group_id,
                    ticker=ticker,
                    ticker_name=ticker,  # TODO: lookup name
                    signal_type="BUY",
                    action="BUY",
                    confidence=trading_signal.confidence,
                    score=score,
                    reason=", ".join(trading_signal.reasons),
                    current_price=current_price,
                    suggested_qty=suggested_qty,
                    required_capital=required_capital,
                    strategy_name=entry_strategy.strategy_name,
                )
            else:
                # Below threshold or HOLD
                return None

        except Exception as e:
            if verbose:
                print(f"   ⚠️  {ticker} entry error: {e}")
            return None

    def _load_market_data(self, ticker: str, current_date: str) -> Optional[MarketData]:
        """使用 MarketDataBuilder 加载 MarketData"""
        try:
            current_ts = pd.Timestamp(current_date)
            return MarketDataBuilder.build_from_manager(
                data_manager=self.data_manager, ticker=ticker, current_date=current_ts
            )
        except Exception as e:
            print(f"Error loading data for {ticker}: {e}")
            return None

    def save_signals(
        self, signals_dict: Dict[str, List[Signal]], date: str, output_dir: str = "."
    ) -> str:
        """
        Save signals to JSON file.

        Args:
            signals_dict: Dict mapping group_id to list of Signal objects
            date: ISO format "YYYY-MM-DD"
            output_dir: Output directory

        Returns:
            Path to saved file
        """
        filename = f"signals_{date}.json"
        filepath = os.path.join(output_dir, filename)

        # Convert to dict
        data = {
            "date": date,
            "timestamp": datetime.now().isoformat(),
            "signals": {
                group_id: [asdict(sig) for sig in signals]
                for group_id, signals in signals_dict.items()
            },
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return filepath


if __name__ == "__main__":
    # Quick test
    import json

    from ..data.stock_data_manager import StockDataManager
    from .state_manager import ProductionState

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)["production"]

    state = ProductionState()
    data_manager = StockDataManager()

    generator = SignalGenerator(config, data_manager, state)
    signals = generator.evaluate_all_groups("2026-01-21", verbose=True)

    print(f"\n✅ Generated {sum(len(s) for s in signals.values())} signals")
