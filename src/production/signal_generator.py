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

from ..analysis.filters import EntrySecondaryFilter
from ..analysis.signals import MarketData, Position, SignalAction, TradingSignal
from ..analysis.strategies.base_entry_strategy import BaseEntryStrategy
from ..analysis.strategies.base_exit_strategy import BaseExitStrategy
from ..backtest.lot_size_manager import LotSizeManager
from ..data.market_data_builder import MarketDataBuilder
from ..data.stock_data_manager import StockDataManager
from ..signal_generator import generate_signal_v2
from ..utils.atr_position_sizing import (
    AtrSizingInput,
    atr_sizing_metadata,
    calculate_atr_position_size,
    parse_portfolio_sizing_config,
)
from ..utils.signal_sizing import extract_buy_size_multiplier
from ..utils.strategy_loader import create_strategy_instance, load_strategy_pair
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
    close_price: Optional[float] = None
    planned_price: Optional[float] = None
    planning_price_factor: Optional[float] = None
    sell_price_factor: Optional[float] = None

    # For SELL signals
    position_qty: Optional[int] = None
    entry_price: Optional[float] = None
    entry_date: Optional[str] = None
    holding_days: Optional[int] = None
    unrealized_pl_pct: Optional[float] = None
    planned_sell_qty: Optional[int] = None
    planned_sell_value: Optional[float] = None

    # For BUY signals
    suggested_qty: Optional[int] = None
    required_capital: Optional[float] = None

    # Capacity audit
    capacity_regime_mode: Optional[str] = None
    capacity_regime_version: Optional[str] = None
    capacity_tier_name: Optional[str] = None
    capacity_effective_equity_jpy: Optional[float] = None
    capacity_effective_max_positions: Optional[int] = None
    capacity_effective_max_position_pct: Optional[float] = None
    capacity_participation_cap_pct: Optional[float] = None
    capacity_min_turnover_20_jpy: Optional[float] = None
    capacity_order_cap_jpy: Optional[float] = None
    capacity_turnover_jpy: Optional[float] = None
    capacity_participation_pct: Optional[float] = None
    capacity_blocking_reason: Optional[str] = None

    # Ranking (populated when signal_ranking_strategy is configured)
    rank: Optional[int] = None
    rank_score: Optional[float] = None

    # Explicit UI/API semantics
    momentum_rank: Optional[int] = None
    momentum_value: Optional[float] = None
    momentum_exhaustion_mode: Optional[str] = None
    momentum_exhaustion_threshold_method: Optional[str] = None
    momentum_exhaustion_max_score: Optional[float] = None
    momentum_exhaustion_score: Optional[float] = None
    momentum_exhaustion_threshold: Optional[float] = None
    momentum_exhaustion_blocked: bool = False
    momentum_exhaustion_filtered: bool = False
    momentum_exhaustion_reason: Optional[str] = None
    is_executable: bool = False
    is_executable_buy: bool = False
    is_executable_sell: bool = False

    # Metadata
    strategy_name: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    signal_metadata: Dict = field(default_factory=dict)

    # Exit strategy evaluation details (for report display)
    evaluation_details: Optional[Dict] = None

    # SELL execution guidance
    exit_trigger: Optional[str] = None
    execution_intent: Optional[str] = None
    execution_method: Optional[str] = None
    execution_summary: Optional[str] = None
    execution_period: Optional[str] = None
    broker_order_type: Optional[str] = None
    oco1_price: Optional[float] = None
    oco1_condition: Optional[str] = None
    oco2_trigger_price: Optional[float] = None
    oco2_limit_price: Optional[float] = None
    oco2_order_mode: Optional[str] = None
    formula_basis: Optional[str] = None
    guidance_notes: Optional[str] = None


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
        sizing_overrides = dict(config)
        if "max_positions_per_group" in config:
            sizing_overrides["max_positions"] = config["max_positions_per_group"]
        self.position_sizing_config = parse_portfolio_sizing_config(
            config,
            sizing_overrides,
        )
        self.entry_filter = EntrySecondaryFilter.from_dict(config.get("entry_filter", {}))

        # Strategy cache (loaded on-demand)
        self._strategy_cache: Dict[tuple[str, str], BaseEntryStrategy] = {}
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

    def _load_strategy_pair(
        self,
        entry_strategy_name: str,
        exit_strategy_name: str,
    ) -> tuple[BaseEntryStrategy, BaseExitStrategy]:
        pair_key = (entry_strategy_name, exit_strategy_name)
        cached_entry = self._strategy_cache.get(pair_key)
        cached_exit = self._exit_strategy_cache.get(exit_strategy_name)
        if cached_entry is not None and cached_exit is not None:
            return cached_entry, cached_exit

        entry_strategy, exit_strategy = load_strategy_pair(
            entry_strategy_name,
            exit_strategy_name,
        )
        self._strategy_cache[pair_key] = entry_strategy
        self._exit_strategy_cache[exit_strategy_name] = exit_strategy
        return entry_strategy, exit_strategy

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

        entry_strategy, exit_strategy = self._load_strategy_pair(
            entry_strategy_name,
            exit_strategy_name,
        )

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
                signal_entry_price=position.signal_entry_price,
                entry_date=pd.Timestamp(position.entry_date),
                quantity=position.quantity,
                entry_signal=TradingSignal(
                    action=SignalAction.BUY,
                    confidence=position.entry_score / 100.0,
                    reasons=["Entry"],
                    metadata={"score": position.entry_score},
                    strategy_name="Entry",
                ),
                peak_price_since_entry=(
                    position.peak_price
                    or position.signal_entry_price
                    or position.entry_price
                ),
                entry_atr=getattr(position, "entry_atr", None),
                initial_stop_price=getattr(position, "initial_stop_price", None),
                locked_stop_price=getattr(position, "locked_stop_price", None),
            )

            # Update peak price
            current_price = market_data.latest_price
            if current_price > signals_position.peak_price_since_entry:
                signals_position.peak_price_since_entry = current_price
                position.peak_price = current_price  # Update Phase 2 position

            # Generate exit signal via unified v2
            trading_signal = generate_signal_v2(
                market_data=market_data,
                entry_strategy=exit_strategy,
                exit_strategy=exit_strategy,
                position=signals_position,
            )
            position.entry_atr = signals_position.entry_atr
            position.initial_stop_price = signals_position.initial_stop_price
            position.locked_stop_price = signals_position.locked_stop_price

            # Get evaluation details (for all cases, SELL or HOLD)
            evaluation_details = None
            if hasattr(exit_strategy, "get_evaluation_details"):
                try:
                    evaluation_details = exit_strategy.get_evaluation_details(
                        signals_position, market_data
                    )
                except Exception as e:
                    if verbose:
                        print(f"   ⚠️  {ticker} evaluation details error: {e}")

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
                    unrealized_pl_pct=signals_position.current_execution_pnl_pct(current_price),
                    strategy_name=exit_strategy.strategy_name,
                    evaluation_details=evaluation_details,
                )
            else:
                # HOLD - return hold signal with evaluation details for reporting
                holding_days = (
                    pd.Timestamp(current_date) - pd.Timestamp(position.entry_date)
                ).days

                return Signal(
                    group_id=group_id,
                    ticker=ticker,
                    ticker_name=ticker,
                    signal_type="HOLD",
                    action="HOLD",
                    confidence=0.0,
                    score=0.0,
                    reason=", ".join(trading_signal.reasons)
                    if trading_signal.reasons
                    else "No exit condition met",
                    current_price=current_price,
                    position_qty=position.quantity,
                    entry_price=position.entry_price,
                    entry_date=position.entry_date,
                    holding_days=holding_days,
                    unrealized_pl_pct=signals_position.current_execution_pnl_pct(current_price),
                    strategy_name=exit_strategy.strategy_name,
                    evaluation_details=evaluation_details,
                )

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
                if not self.entry_filter.passes(market_data):
                    return None

                signal_metadata = dict(trading_signal.metadata or {})
                signal_buy_scale = extract_buy_size_multiplier(signal_metadata)

                # Calculate suggested quantity
                if self.position_sizing_config.mode == "atr":
                    atr_value, atr_ratio = self._extract_atr_values(market_data)
                    sizing_result = calculate_atr_position_size(
                        AtrSizingInput(
                            ticker=ticker,
                            planning_price=current_price,
                            portfolio_value_jpy=group.total_value({ticker: current_price}),
                            available_cash_jpy=group.cash,
                            atr_jpy=atr_value,
                            lot_size=LotSizeManager.get_lot_size(ticker),
                            config=self.position_sizing_config.atr,
                            signal_scale=signal_buy_scale,
                            atr_ratio=atr_ratio,
                        )
                    )
                    signal_metadata.update(
                        atr_sizing_metadata(
                            sizing_result,
                            self.position_sizing_config.atr,
                        )
                    )
                    suggested_qty = sizing_result.quantity
                    required_capital = sizing_result.required_capital_jpy
                else:
                    max_position_pct = self.config.get("max_position_pct", 0.30)
                    max_position_pct *= signal_buy_scale
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
                    signal_metadata=signal_metadata,
                )
            else:
                # Below threshold or HOLD
                return None

        except Exception as e:
            if verbose:
                print(f"   ⚠️  {ticker} entry error: {e}")
            return None

    @staticmethod
    def _extract_atr_values(market_data: MarketData) -> tuple[float, float | None]:
        latest = market_data.latest_features
        if latest.empty:
            return 0.0, None
        atr_raw = latest.get("ATR", 0.0)
        atr = 0.0 if pd.isna(atr_raw) else float(atr_raw or 0.0)
        ratio_raw = latest.get("ATR_Ratio")
        if ratio_raw is not None and not pd.isna(ratio_raw):
            ratio = float(ratio_raw)
            if ratio > 0:
                return atr, ratio
        close_price = market_data.latest_price
        if close_price > 0 and atr > 0:
            return atr, atr / close_price
        return atr, None

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
    from ..data.stock_data_manager import StockDataManager
    from ..config.service import load_config
    from .state_manager import ProductionState

    config = load_config().get("production", {})

    state = ProductionState()
    data_manager = StockDataManager()

    generator = SignalGenerator(config, data_manager, state)
    signals = generator.evaluate_all_groups("2026-01-21", verbose=True)

    print(f"\n✅ Generated {sum(len(s) for s in signals.values())} signals")
