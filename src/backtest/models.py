"""
Backtest Data Models
Dataclasses for trade records and backtest results.
"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
import pandas as pd


@dataclass
class Trade:
    """Record of a single buy/sell cycle."""
    ticker: str
    entry_date: str
    entry_price: float
    entry_score: float
    exit_date: str
    exit_price: float
    exit_reason: str
    exit_urgency: str
    holding_days: int
    shares: int
    return_pct: float
    return_jpy: float
    peak_price: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class BacktestResult:
    """Complete backtest results for one strategy on one ticker."""
    ticker: str
    ticker_name: str
    scorer_name: str
    exiter_name: str
    start_date: str
    end_date: str
    starting_capital_jpy: float
    
    # Performance Metrics
    final_capital_jpy: float
    total_return_pct: float
    annualized_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    
    # Trade Statistics
    num_trades: int
    win_rate_pct: float
    avg_gain_pct: float
    avg_loss_pct: float
    avg_holding_days: float
    profit_factor: float  # Gross profit / Gross loss
    
    # Benchmark 1: Buy & Hold该股票 (评估择时能力)
    buy_hold_return_pct: Optional[float] = None  # 该股票Buy&Hold回报
    timing_alpha: Optional[float] = None         # vs Buy&Hold的Alpha (择时能力)
    beat_buy_hold: Optional[bool] = None         # 是否跑赢Buy&Hold
    
    # Benchmark 2: TOPIX (评估选股能力)
    benchmark_return_pct: Optional[float] = None # TOPIX回报
    stock_selection_alpha: Optional[float] = None # Buy&Hold vs TOPIX (选股能力)
    alpha: Optional[float] = None                 # 策略 vs TOPIX (总Alpha = 择时+选股)
    beat_benchmark: Optional[bool] = None
    beta: Optional[float] = None                  # Systematic risk (strategy vs TOPIX)
    tracking_error: Optional[float] = None        # Active risk (annualized %)
    information_ratio: Optional[float] = None     # Alpha quality (alpha / tracking_error)
    
    # Trade Details
    trades: List[Trade] = field(default_factory=list)
    
    # Internal: daily equity series for Beta/IR calculation (not serialized)
    _daily_equity_series: Any = field(default=None, repr=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excluding trades list for summary)."""
        d = asdict(self)
        # Remove internal fields and large lists
        d.pop('_daily_equity_series', None)
        d.pop('trades', None)
        return d
    
    def to_summary_string(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"{'='*70}",
            f"Backtest: {self.ticker} ({self.ticker_name})",
            f"Strategy: {self.scorer_name} + {self.exiter_name}",
            f"Period: {self.start_date} to {self.end_date}",
            f"{'='*70}",
            f"",
            f"💰 Capital:",
            f"  Starting: ¥{self.starting_capital_jpy:,.0f}",
            f"  Ending:   ¥{self.final_capital_jpy:,.0f}",
            f"  Profit:   ¥{self.final_capital_jpy - self.starting_capital_jpy:,.0f}",
            f"",
            f"📊 Returns:",
            f"  Total Return:      {self.total_return_pct:+.2f}%",
            f"  Annualized:        {self.annualized_return_pct:+.2f}%",
            f"  Sharpe Ratio:      {self.sharpe_ratio:.2f}",
            f"  Max Drawdown:      {self.max_drawdown_pct:.2f}%",
            f"",
            f"📈 Trading:",
            f"  Trades:            {self.num_trades}",
            f"  Win Rate:          {self.win_rate_pct:.1f}%",
            f"  Avg Gain:          {self.avg_gain_pct:+.2f}%",
            f"  Avg Loss:          {self.avg_loss_pct:+.2f}%",
            f"  Avg Hold:          {self.avg_holding_days:.1f} days",
            f"  Profit Factor:     {self.profit_factor:.2f}",
        ]
        
        # Buy&Hold基准对比 (择时能力评估)
        if self.buy_hold_return_pct is not None:
            timing_icon = "✅" if self.beat_buy_hold else "❌"
            lines.extend([
                f"",
                f"📊 vs Buy&Hold {self.ticker} (择时能力):",
                f"  Buy&Hold Return:   {self.buy_hold_return_pct:+.2f}%",
                f"  Timing Alpha:      {self.timing_alpha:+.2f}%",
                f"  Beat Buy&Hold:     {timing_icon} {self.beat_buy_hold}",
            ])
        
        # TOPIX基准对比 (选股能力评估)
        if self.benchmark_return_pct is not None:
            selection_icon = "✅" if self.stock_selection_alpha and self.stock_selection_alpha > 0 else "❌"
            total_icon = "✅" if self.beat_benchmark else "❌"
            lines.extend([
                f"",
                f"🎯 vs TOPIX (选股+择时):",
                f"  TOPIX Return:      {self.benchmark_return_pct:+.2f}%",
                f"  Stock Alpha:       {self.stock_selection_alpha:+.2f}% {selection_icon}",
                f"  Total Alpha:       {self.alpha:+.2f}% {total_icon}",
            ])
        
        lines.append(f"{'='*70}")
        return "\n".join(lines)
