"""
Production State Management Module

Handles portfolio state tracking for production signal workflow.
Default operation uses a single strategy group, with optional multi-group expansion.
Features:
- Independent cash/position tracking per strategy group
- FIFO position handling for partial sells
- Position-level metadata (entry date, entry price, entry score)
- State persistence (JSON-based)
- Interactive strategy group selection
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
import pandas as pd


@dataclass
class Position:
    """Represents a single stock position in a strategy group"""
    ticker: str
    quantity: int
    entry_price: float
    entry_date: str  # ISO format YYYY-MM-DD
    entry_score: float
    peak_price: float = 0.0  # Track for trailing stops
    
    def current_value(self, current_price: float) -> float:
        """Calculate current market value"""
        return self.quantity * current_price
    
    def unrealized_pl(self, current_price: float) -> float:
        """Calculate unrealized P&L in JPY"""
        return (current_price - self.entry_price) * self.quantity
    
    def unrealized_pl_pct(self, current_price: float) -> float:
        """Calculate unrealized P&L percentage"""
        if self.entry_price == 0:
            return 0.0
        return ((current_price - self.entry_price) / self.entry_price) * 100
    
    def holding_days(self, reference_date: Optional[date] = None) -> int:
        """Calculate number of days held"""
        if reference_date is None:
            reference_date = datetime.now().date()
        
        entry = datetime.strptime(self.entry_date, "%Y-%m-%d").date()
        return (reference_date - entry).days


@dataclass
class StrategyGroupState:
    """State of a single strategy group"""
    id: str
    name: str
    initial_capital: float
    cash: float = 0.0  # Will be set to initial_capital if not provided
    positions: List[Position] = field(default_factory=list)
    
    def __post_init__(self):
        """Initialize cash if not set"""
        if self.cash == 0.0:
            self.cash = self.initial_capital
    
    def total_value(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total portfolio value (cash + positions at current prices)
        
        Args:
            current_prices: Dict of {ticker: current_price}
        
        Returns:
            Total value in JPY
        """
        position_value = sum(
            pos.current_value(current_prices.get(pos.ticker, pos.entry_price))
            for pos in self.positions
        )
        return self.cash + position_value
    
    def add_position(
        self,
        ticker: str,
        quantity: int,
        entry_price: float,
        entry_date: str,
        entry_score: float
    ) -> None:
        """
        Add a new position to this strategy group.
        
        Updates cash immediately.
        """
        position = Position(
            ticker=ticker,
            quantity=quantity,
            entry_price=entry_price,
            entry_date=entry_date,
            entry_score=entry_score,
            peak_price=entry_price
        )
        self.positions.append(position)
        self.cash -= entry_price * quantity
    
    def get_position(self, ticker: str) -> Optional[Position]:
        """Get first (FIFO) position for a ticker"""
        for pos in self.positions:
            if pos.ticker == ticker:
                return pos
        return None
    
    def get_positions_by_ticker(self, ticker: str) -> List[Position]:
        """Get all positions for a ticker (for FIFO handling)"""
        return [pos for pos in self.positions if pos.ticker == ticker]
    
    def remove_position(self, ticker: str, quantity: int) -> Tuple[int, float]:
        """
        Remove position(s) using FIFO method.
        
        Args:
            ticker: Stock code
            quantity: Number of shares to sell
        
        Returns:
            Tuple of (total_proceeds_jpy, actual_quantity_sold)
        
        Raises:
            ValueError: If not enough shares to sell
        """
        positions_to_sell = self.get_positions_by_ticker(ticker)
        
        if not positions_to_sell:
            raise ValueError(f"No positions for {ticker} in {self.id}")
        
        total_quantity = sum(p.quantity for p in positions_to_sell)
        if quantity > total_quantity:
            raise ValueError(
                f"Cannot sell {quantity} shares of {ticker}. "
                f"Only {total_quantity} available in {self.id}"
            )
        
        remaining_to_sell = quantity
        total_proceeds = 0.0
        
        # Process FIFO
        for position in positions_to_sell:
            if remaining_to_sell == 0:
                break
            
            if position.quantity <= remaining_to_sell:
                # Sell entire position
                sale_proceeds = position.quantity * position.entry_price  # Exit at entry for now
                total_proceeds += sale_proceeds
                remaining_to_sell -= position.quantity
                self.positions.remove(position)
            else:
                # Partial sell
                sale_proceeds = remaining_to_sell * position.entry_price
                total_proceeds += sale_proceeds
                position.quantity -= remaining_to_sell
                remaining_to_sell = 0
        
        self.cash += total_proceeds
        return total_proceeds, quantity
    
    def partial_sell(
        self,
        ticker: str,
        quantity: int,
        exit_price: float
    ) -> Tuple[float, int]:
        """
        Sell shares at a specific exit price (for backtesting).
        Uses FIFO for multiple positions.
        
        Returns:
            Tuple of (total_proceeds_jpy, actual_quantity_sold)
        """
        positions_to_sell = self.get_positions_by_ticker(ticker)
        
        if not positions_to_sell:
            raise ValueError(f"No positions for {ticker} in {self.id}")
        
        total_quantity = sum(p.quantity for p in positions_to_sell)
        if quantity > total_quantity:
            raise ValueError(
                f"Cannot sell {quantity} shares of {ticker}. "
                f"Only {total_quantity} available in {self.id}"
            )
        
        remaining_to_sell = quantity
        total_proceeds = 0.0
        
        # Process FIFO
        for position in positions_to_sell:
            if remaining_to_sell == 0:
                break
            
            if position.quantity <= remaining_to_sell:
                # Sell entire position
                sale_proceeds = position.quantity * exit_price
                total_proceeds += sale_proceeds
                remaining_to_sell -= position.quantity
                self.positions.remove(position)
            else:
                # Partial sell
                sale_proceeds = remaining_to_sell * exit_price
                total_proceeds += sale_proceeds
                position.quantity -= remaining_to_sell
                remaining_to_sell = 0
        
        self.cash += total_proceeds
        return total_proceeds, quantity
    
    def get_status(self, current_prices: Dict[str, float] = None) -> Dict:
        """Get summary status of this strategy group"""
        if current_prices is None:
            current_prices = {}
        
        total_value = self.total_value(current_prices)
        total_invested = sum(
            pos.entry_price * pos.quantity for pos in self.positions
        )
        
        return {
            "id": self.id,
            "name": self.name,
            "initial_capital": self.initial_capital,
            "current_cash": self.cash,
            "invested": total_invested,
            "total_value": total_value,
            "num_positions": len(self.positions),
            "position_count": len([p for p in self.positions if p.quantity > 0])
        }


@dataclass
class Trade:
    """Record of a completed trade (for history tracking)"""
    date: str  # ISO format YYYY-MM-DD
    group_id: str
    ticker: str
    action: str  # "BUY" or "SELL"
    quantity: int
    price: float
    total_jpy: float
    entry_score: Optional[float] = None  # For BUY
    exit_reason: Optional[str] = None    # For SELL
    exit_score: Optional[float] = None   # For SELL


class ProductionState:
    """
    Main state manager for production trading system.
    
    Handles:
    - Multi-group portfolio state
    - Persistence (JSON read/write)
    - State transitions (trading, cash updates)
    - Query/reporting
    """
    
    def __init__(self, state_file: str = "production_state.json"):
        """
        Initialize ProductionState.
        
        Args:
            state_file: Path to JSON state file
        """
        self.state_file = state_file
        self.strategy_groups: Dict[str, StrategyGroupState] = {}
        self.last_updated = datetime.now().isoformat()
        self.load_or_initialize()
    
    def load_or_initialize(self) -> None:
        """Load state from file or initialize with defaults"""
        if os.path.exists(self.state_file):
            self.load()
        else:
            # Will be created on first save
            pass
    
    def load(self) -> None:
        """Load state from JSON file"""
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.last_updated = data.get("last_updated", datetime.now().isoformat())
            self.strategy_groups = {}
            
            for group_data in data.get("strategy_groups", []):
                positions = [
                    Position(**pos) for pos in group_data.get("positions", [])
                ]
                group = StrategyGroupState(
                    id=group_data["id"],
                    name=group_data["name"],
                    initial_capital=group_data["initial_capital"],
                    cash=group_data.get("cash", group_data["initial_capital"]),
                    positions=positions
                )
                self.strategy_groups[group.id] = group
        
        except Exception as e:
            print(f"Error loading state file: {e}")
            raise
    
    def save(self) -> None:
        """Save state to JSON file"""
        self.last_updated = datetime.now().isoformat()
        
        data = {
            "last_updated": self.last_updated,
            "strategy_groups": [
                {
                    "id": group.id,
                    "name": group.name,
                    "initial_capital": group.initial_capital,
                    "cash": group.cash,
                    "positions": [asdict(pos) for pos in group.positions]
                }
                for group in self.strategy_groups.values()
            ]
        }
        
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def add_group(
        self,
        group_id: str,
        name: str,
        initial_capital: float
    ) -> StrategyGroupState:
        """Add a new strategy group"""
        group = StrategyGroupState(
            id=group_id,
            name=name,
            initial_capital=initial_capital,
            cash=initial_capital
        )
        self.strategy_groups[group_id] = group
        return group
    
    def get_group(self, group_id: str) -> Optional[StrategyGroupState]:
        """Get a strategy group by ID"""
        return self.strategy_groups.get(group_id)
    
    def get_all_groups(self) -> List[StrategyGroupState]:
        """Get all strategy groups"""
        return list(self.strategy_groups.values())
    
    def select_group_interactive(self) -> StrategyGroupState:
        """
        Interactively select a strategy group (for CLI).
        
        Returns:
            Selected StrategyGroupState
        """
        groups = self.get_all_groups()
        
        if not groups:
            raise ValueError("No strategy groups available")
        
        if len(groups) == 1:
            return groups[0]
        
        print("\n📊 Available Strategy Groups:")
        print("-" * 50)
        for i, group in enumerate(groups, 1):
            status = group.get_status()
            print(f"{i}. [{group.id}] {group.name}")
            print(f"   Cash: ¥{status['current_cash']:,.0f}")
            print(f"   Positions: {status['position_count']}")
            print()
        
        while True:
            try:
                choice = input("Select group (1-n): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(groups):
                    return groups[idx]
                else:
                    print("Invalid selection. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number.")
    
    def get_portfolio_status(
        self,
        current_prices: Dict[str, float] = None
    ) -> Dict:
        """Get summary status across all strategy groups"""
        if current_prices is None:
            current_prices = {}
        
        total_cash = sum(g.cash for g in self.strategy_groups.values())
        total_value = sum(
            g.total_value(current_prices)
            for g in self.strategy_groups.values()
        )
        total_invested = sum(
            sum(pos.entry_price * pos.quantity for pos in g.positions)
            for g in self.strategy_groups.values()
        )
        
        all_positions = []
        for group in self.strategy_groups.values():
            for pos in group.positions:
                all_positions.append({
                    "group_id": group.id,
                    "ticker": pos.ticker,
                    "quantity": pos.quantity,
                    "entry_price": pos.entry_price,
                    "entry_date": pos.entry_date
                })
        
        return {
            "total_cash": total_cash,
            "total_invested": total_invested,
            "total_value": total_value,
            "total_positions": len(all_positions),
            "num_groups": len(self.strategy_groups),
            "positions": all_positions,
            "groups": [g.get_status(current_prices) for g in self.strategy_groups.values()]
        }
    
    def get_open_positions_for_ticker(self, ticker: str) -> List[Dict]:
        """
        Get all open positions for a ticker across all groups.
        
        Returns:
            List of position info dicts
        """
        positions = []
        for group in self.strategy_groups.values():
            for pos in group.get_positions_by_ticker(ticker):
                if pos.quantity > 0:
                    positions.append({
                        "group_id": group.id,
                        "group_name": group.name,
                        "ticker": ticker,
                        "quantity": pos.quantity,
                        "entry_price": pos.entry_price,
                        "entry_date": pos.entry_date,
                        "entry_score": pos.entry_score
                    })
        return positions


class TradeHistoryManager:
    """Manages trade history (append-only log)"""
    
    def __init__(self, history_file: str = "trade_history.json"):
        """Initialize trade history manager"""
        self.history_file = history_file
        self.trades: List[Trade] = []
        self.load_or_initialize()
    
    def load_or_initialize(self) -> None:
        """Load history from file or initialize empty"""
        if os.path.exists(self.history_file):
            self.load()
        else:
            self.trades = []
    
    def load(self) -> None:
        """Load trade history from JSON file"""
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.trades = [Trade(**trade_data) for trade_data in data.get("trades", [])]
        except Exception as e:
            print(f"Error loading trade history: {e}")
            self.trades = []
    
    def save(self) -> None:
        """Save trade history to JSON file"""
        data = {
            "trades": [asdict(trade) for trade in self.trades]
        }
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def record_trade(
        self,
        date: str,
        group_id: str,
        ticker: str,
        action: str,
        quantity: int,
        price: float,
        entry_score: Optional[float] = None,
        exit_reason: Optional[str] = None,
        exit_score: Optional[float] = None
    ) -> Trade:
        """
        Record a new trade.
        
        Args:
            date: ISO format YYYY-MM-DD
            group_id: Strategy group ID
            ticker: Stock code
            action: "BUY" or "SELL"
            quantity: Number of shares
            price: Execution price per share
            entry_score: Score at entry (for BUY)
            exit_reason: Reason for exit (for SELL)
            exit_score: Score at exit (for SELL)
        
        Returns:
            Trade object
        """
        trade = Trade(
            date=date,
            group_id=group_id,
            ticker=ticker,
            action=action,
            quantity=quantity,
            price=price,
            total_jpy=quantity * price,
            entry_score=entry_score,
            exit_reason=exit_reason,
            exit_score=exit_score
        )
        self.trades.append(trade)
        return trade
    
    def get_trades_by_group(self, group_id: str) -> List[Trade]:
        """Get all trades for a specific group"""
        return [t for t in self.trades if t.group_id == group_id]
    
    def get_trades_by_ticker(self, ticker: str) -> List[Trade]:
        """Get all trades for a specific ticker"""
        return [t for t in self.trades if t.ticker == ticker]
    
    def get_trades_by_date(self, date_str: str) -> List[Trade]:
        """Get all trades on a specific date"""
        return [t for t in self.trades if t.date == date_str]


if __name__ == "__main__":
    # Example usage
    state = ProductionState()
    
    # List groups
    print("Strategy Groups:")
    for group in state.get_all_groups():
        print(f"- {group.id}: {group.name} (¥{group.cash:,.0f})")
