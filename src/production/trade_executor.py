"""
Production Trade Executor

Executes trading signals and updates portfolio state.
- Handles BUY/SELL signal execution
- Updates production_state.json
- Records trades to trade_history.json
- Validates cash/position constraints
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd

from .signal_generator import Signal
from .state_manager import ProductionState, TradeHistoryManager, StrategyGroupState


@dataclass
class ExecutionResult:
    """Result of signal execution"""
    success: bool
    signal: Signal
    executed_qty: int = 0
    executed_price: float = 0.0
    proceeds: float = 0.0  # For SELL
    reason: str = ""  # Error reason if failed


class TradeExecutor:
    """
    Execute trading signals and update portfolio state.
    
    Workflow:
    1. Validate signal (cash/position constraints)
    2. Execute trade (BUY or SELL)
    3. Update ProductionState
    4. Record to TradeHistoryManager
    5. Return ExecutionResult
    """
    
    def __init__(
        self,
        state: ProductionState,
        history: TradeHistoryManager,
        current_date: str
    ):
        """
        Initialize TradeExecutor.
        
        Args:
            state: ProductionState instance
            history: TradeHistoryManager instance
            current_date: ISO format "YYYY-MM-DD"
        """
        self.state = state
        self.history = history
        self.current_date = current_date
    
    def execute_signal(
        self,
        signal: Signal,
        dry_run: bool = False,
        verbose: bool = False
    ) -> ExecutionResult:
        """
        Execute a single signal.
        
        Args:
            signal: Signal object to execute
            dry_run: If True, validate but don't execute
            verbose: Print execution details
        
        Returns:
            ExecutionResult with success/failure info
        """
        if signal.signal_type == "BUY":
            return self._execute_buy(signal, dry_run, verbose)
        elif signal.signal_type in ["SELL", "EXIT"]:
            return self._execute_sell(signal, dry_run, verbose)
        else:
            return ExecutionResult(
                success=False,
                signal=signal,
                reason=f"Unknown signal type: {signal.signal_type}"
            )
    
    def execute_batch(
        self,
        signals: list,
        dry_run: bool = False,
        verbose: bool = False
    ) -> list:
        """
        Execute multiple signals.
        
        Args:
            signals: List of Signal objects
            dry_run: If True, validate but don't execute
            verbose: Print execution details
        
        Returns:
            List of ExecutionResult objects
        """
        results = []
        
        for signal in signals:
            result = self.execute_signal(signal, dry_run, verbose)
            results.append(result)
        
        return results
    
    def _execute_buy(
        self,
        signal: Signal,
        dry_run: bool = False,
        verbose: bool = False
    ) -> ExecutionResult:
        """Execute BUY signal"""
        group = self.state.get_group(signal.group_id)
        
        if not group:
            return ExecutionResult(
                success=False,
                signal=signal,
                reason=f"Group {signal.group_id} not found"
            )
        
        # Use suggested quantity from signal
        qty = signal.suggested_qty or 0
        price = signal.current_price
        required_capital = qty * price
        
        if qty <= 0:
            return ExecutionResult(
                success=False,
                signal=signal,
                reason="Invalid quantity (0)"
            )
        
        # Check cash availability
        if group.cash < required_capital:
            return ExecutionResult(
                success=False,
                signal=signal,
                reason=f"Insufficient cash: ¥{group.cash:,.0f} < ¥{required_capital:,.0f}"
            )
        
        if dry_run:
            if verbose:
                print(f"✅ [DRY RUN] BUY {qty}x{signal.ticker} @ ¥{price:,.0f}")
            return ExecutionResult(
                success=True,
                signal=signal,
                executed_qty=qty,
                executed_price=price,
                reason="Dry run - validated"
            )
        
        # Execute BUY
        try:
            group.add_position(
                ticker=signal.ticker,
                quantity=qty,
                entry_price=price,
                entry_date=self.current_date,
                entry_score=signal.score
            )
            
            # Record trade
            self.history.record_trade(
                date=self.current_date,
                group_id=signal.group_id,
                ticker=signal.ticker,
                action="BUY",
                quantity=qty,
                price=price,
                entry_score=signal.score
            )
            
            if verbose:
                print(f"✅ BUY {qty}x{signal.ticker} @ ¥{price:,.0f} → Cash: ¥{group.cash:,.0f}")
            
            return ExecutionResult(
                success=True,
                signal=signal,
                executed_qty=qty,
                executed_price=price,
                reason="Executed successfully"
            )
        
        except Exception as e:
            return ExecutionResult(
                success=False,
                signal=signal,
                reason=f"Execution error: {e}"
            )
    
    def _execute_sell(
        self,
        signal: Signal,
        dry_run: bool = False,
        verbose: bool = False
    ) -> ExecutionResult:
        """Execute SELL signal"""
        group = self.state.get_group(signal.group_id)
        
        if not group:
            return ExecutionResult(
                success=False,
                signal=signal,
                reason=f"Group {signal.group_id} not found"
            )
        
        # Parse sell action
        sell_pct = self._parse_sell_action(signal.action)
        
        # Get positions
        positions = group.get_positions_by_ticker(signal.ticker)
        
        if not positions:
            return ExecutionResult(
                success=False,
                signal=signal,
                reason=f"No position found for {signal.ticker}"
            )
        
        total_qty = sum(p.quantity for p in positions)
        qty_to_sell = int(total_qty * sell_pct)
        
        if qty_to_sell <= 0:
            return ExecutionResult(
                success=False,
                signal=signal,
                reason="Quantity too small to sell"
            )
        
        price = signal.current_price
        
        if dry_run:
            if verbose:
                print(f"✅ [DRY RUN] SELL {qty_to_sell}x{signal.ticker} @ ¥{price:,.0f} ({signal.action})")
            return ExecutionResult(
                success=True,
                signal=signal,
                executed_qty=qty_to_sell,
                executed_price=price,
                proceeds=qty_to_sell * price,
                reason="Dry run - validated"
            )
        
        # Execute SELL (FIFO)
        try:
            proceeds, sold = group.partial_sell(
                ticker=signal.ticker,
                quantity=qty_to_sell,
                exit_price=price
            )
            
            # Record trade
            self.history.record_trade(
                date=self.current_date,
                group_id=signal.group_id,
                ticker=signal.ticker,
                action="SELL",
                quantity=sold,
                price=price,
                exit_reason=signal.reason,
                exit_score=signal.confidence * 100  # Convert back to 0-100
            )
            
            if verbose:
                pl_pct = signal.unrealized_pl_pct or 0
                print(f"✅ SELL {sold}x{signal.ticker} @ ¥{price:,.0f} "
                      f"(P&L: {pl_pct:+.2f}%) → Cash: ¥{group.cash:,.0f}")
            
            return ExecutionResult(
                success=True,
                signal=signal,
                executed_qty=sold,
                executed_price=price,
                proceeds=proceeds,
                reason="Executed successfully"
            )
        
        except Exception as e:
            return ExecutionResult(
                success=False,
                signal=signal,
                reason=f"Execution error: {e}"
            )
    
    def _parse_sell_action(self, action: str) -> float:
        """
        Parse sell action to percentage.
        
        Args:
            action: "SELL_25%", "SELL_50%", "SELL_75%", "SELL_100%"
        
        Returns:
            Percentage as float (0.25, 0.5, 0.75, 1.0)
        """
        if "100" in action:
            return 1.0
        elif "75" in action:
            return 0.75
        elif "50" in action:
            return 0.5
        elif "25" in action:
            return 0.25
        else:
            return 1.0  # Default to full sell
    
    def save_all(self):
        """Save state and history"""
        self.state.save()
        self.history.save()
    
    def get_execution_summary(self, results: list) -> dict:
        """
        Generate execution summary.
        
        Args:
            results: List of ExecutionResult objects
        
        Returns:
            Summary dict with stats
        """
        total = len(results)
        success = len([r for r in results if r.success])
        failed = total - success
        
        buy_count = len([r for r in results if r.success and r.signal.signal_type == "BUY"])
        sell_count = len([r for r in results if r.success and r.signal.signal_type in ["SELL", "EXIT"]])
        
        total_buy_capital = sum(
            r.executed_qty * r.executed_price
            for r in results if r.success and r.signal.signal_type == "BUY"
        )
        
        total_sell_proceeds = sum(
            r.proceeds
            for r in results if r.success and r.signal.signal_type in ["SELL", "EXIT"]
        )
        
        return {
            "total_signals": total,
            "executed": success,
            "failed": failed,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_buy_capital": total_buy_capital,
            "total_sell_proceeds": total_sell_proceeds,
            "failures": [
                {"ticker": r.signal.ticker, "reason": r.reason}
                for r in results if not r.success
            ]
        }


if __name__ == "__main__":
    # Quick test
    from .state_manager import ProductionState, TradeHistoryManager
    from .signal_generator import Signal
    
    state = ProductionState()
    history = TradeHistoryManager()
    executor = TradeExecutor(state, history, "2026-01-21")
    
    # Test dry run
    test_signal = Signal(
        group_id="group_main",
        ticker="8035",
        ticker_name="東京エレクトロン",
        signal_type="BUY",
        action="BUY",
        confidence=0.75,
        score=75.0,
        reason="Strong technical setup",
        current_price=31500,
        suggested_qty=100,
        required_capital=3150000
    )
    
    result = executor.execute_signal(test_signal, dry_run=True, verbose=True)
    print(f"\n✅ Test result: {result.reason}")
