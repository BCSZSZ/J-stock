"""
Phase 4: Report Building Module

Generates Markdown daily trading reports from signals and portfolio state.
"""

from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import pandas as pd

from .state_manager import ProductionState
from .signal_generator import Signal
from .trade_executor import ExecutionResult
from ..data.stock_data_manager import StockDataManager


@dataclass
class MarketSummary:
    """Market context for daily report."""
    date: str
    topix_close: Optional[float] = None
    topix_change_pct: Optional[float] = None
    market_condition: str = "N/A"  # "Bullish", "Bearish", "Neutral"


class ReportBuilder:
    """
    Builds comprehensive Markdown trading reports.
    
    Report Structure:
    1. Market Summary (TOPIX, date, market condition)
    2. BUY Signals (sorted by score, descending)
    3. SELL Signals (sorted by urgency: EMERGENCY > HIGH > MEDIUM > LOW)
    4. Current Portfolio Status (positions with P&L)
    5. Execution Summary (if trades executed)
    
    Usage:
        builder = ReportBuilder(state_manager, data_manager)
        report = builder.generate_daily_report(signals, execution_results)
        path = builder.save_report(report, output_dir="output")
    """
    
    def __init__(
        self, 
        state_manager: ProductionState, 
        data_manager: StockDataManager
    ):
        """
        Initialize report builder.
        
        Args:
            state_manager: Current portfolio state
            data_manager: For fetching market data (TOPIX benchmark)
        """
        self.state_manager = state_manager
        self.data_manager = data_manager
    
    def generate_daily_report(
        self, 
        signals: List[Signal] = None,
        execution_results: Optional[List[ExecutionResult]] = None,
        report_date: Optional[str] = None,
        comprehensive_evaluations: Dict = None  # New: Complete evaluation table
    ) -> str:
        """
        Generate complete Markdown trading report.
        
        Args:
            signals: List of BUY/SELL signals from SignalGenerator (legacy)
            execution_results: Optional list of execution outcomes
            report_date: Report date (default: today, format: YYYY-MM-DD)
            comprehensive_evaluations: Dict[ticker] -> StockComprehensiveEvaluation (new)
        
        Returns:
            Complete Markdown report as string
        """
        if report_date is None:
            report_date = datetime.now().strftime("%Y-%m-%d")
        
        # Use comprehensive evaluations if provided, otherwise fall back to signals
        if comprehensive_evaluations:
            return self._generate_comprehensive_report(
                comprehensive_evaluations,
                execution_results,
                report_date
            )
        
        # Legacy path: signals-only report
        if signals is None:
            signals = []
        
        buy_signals = [s for s in signals if s.signal_type == "BUY"]
        sell_signals = [s for s in signals if s.signal_type == "SELL"]
        
        # Build sections
        sections = []
        sections.append(self._build_header(report_date))
        sections.append(self._build_market_summary(report_date))
        sections.append(self._build_buy_signals_section(buy_signals))
        sections.append(self._build_sell_signals_section(sell_signals))
        sections.append(self._build_portfolio_status_section())
        
        if execution_results:
            sections.append(self._build_execution_summary_section(execution_results))
        
        sections.append(self._build_footer())
        
        return "\n\n".join(sections)
    
    def _generate_comprehensive_report(
        self,
        evaluations: Dict,
        execution_results: Optional[List[ExecutionResult]],
        report_date: str
    ) -> str:
        """
        Generate new comprehensive report with complete evaluation table.
        
        Args:
            evaluations: Dict[ticker] -> StockComprehensiveEvaluation
            execution_results: Optional execution outcomes
            report_date: Report date
        
        Returns:
            Complete Markdown report with evaluation table
        """
        sections = []
        sections.append(self._build_header(report_date))
        sections.append(self._build_market_summary(report_date))
        
        # NEW: Complete evaluation table (all 61 stocks × strategies)
        sections.append(self._build_comprehensive_evaluation_section(evaluations))
        
        # Current portfolio with exit evaluations
        sections.append(self._build_portfolio_status_section())
        
        if execution_results:
            sections.append(self._build_execution_summary_section(execution_results))
        
        sections.append(self._build_footer())
        
        return "\n\n".join(sections)
    
    def _build_comprehensive_evaluation_section(self, evaluations: Dict) -> str:
        """
        Build comprehensive evaluation table for all stocks × strategies.
        
        Shows:
        - All 61 monitored stocks
        - Current price
        - Evaluation from each strategy (SimpleScorerStrategy, IchimokuStochStrategy)
        - Technical indicators
        - Overall signal
        """
        if not evaluations:
            return "## 📊 Stock Evaluation Table\n\n*No evaluations available.*"
        
        lines = [
            "## 📊 Complete Stock Evaluation Table",
            "",
            f"**Total Stocks Evaluated:** {len(evaluations)}",
            f"**Last Update:** {list(evaluations.values())[0].latest_date if evaluations else 'N/A'}",
            ""
        ]
        
        # Sort by overall signal and price
        sorted_evals = sorted(
            evaluations.values(),
            key=lambda e: (
                {"STRONG_BUY": 0, "BUY": 1, "WEAK_BUY": 2, "HOLD": 3}.get(e.overall_signal, 99),
                -e.current_price
            )
        )
        
        # Main evaluation table
        lines.append("### Main Evaluation Table")
        lines.append("")
        lines.append(
            "| Ticker | Name | Price | SimpleScorerStrategy | Ichimoku<br>Strategy | "
            "EMA20 | EMA50 | EMA200 | RSI | ATR | Overall |"
        )
        lines.append(
            "|--------|------|-------|----------------------|----------------------|"
            "-------|-------|--------|-----|-----|---------|"
        )
        
        # Table rows
        for eval_obj in sorted_evals:
            ticker = eval_obj.ticker
            price = f"¥{eval_obj.current_price:,.0f}"
            
            # Get signals from each strategy (if available)
            simple_eval = eval_obj.evaluations.get('SimpleScorerStrategy')
            ichimoku_eval = eval_obj.evaluations.get('IchimokuStochStrategy')
            
            simple_signal = f"{simple_eval.signal_action}" if simple_eval else "—"
            ichimoku_signal = f"{ichimoku_eval.signal_action}" if ichimoku_eval else "—"
            
            # Technical indicators
            ema20 = f"{eval_obj.technical_indicators.get('EMA_20', 0):.0f}"
            ema50 = f"{eval_obj.technical_indicators.get('EMA_50', 0):.0f}"
            ema200 = f"{eval_obj.technical_indicators.get('EMA_200', 0):.0f}"
            rsi = f"{eval_obj.technical_indicators.get('RSI', 0):.0f}"
            atr = f"{eval_obj.technical_indicators.get('ATR', 0):.2f}"
            
            # Overall signal with emoji
            signal_emoji = {
                "STRONG_BUY": "🟢🟢",
                "BUY": "🟢",
                "WEAK_BUY": "🟡",
                "HOLD": "⚪"
            }.get(eval_obj.overall_signal, "⚪")
            
            overall = f"{signal_emoji} {eval_obj.overall_signal}"
            
            lines.append(
                f"| {ticker} | {eval_obj.ticker_name[:15]} | {price} | "
                f"{simple_signal} | {ichimoku_signal} | "
                f"{ema20} | {ema50} | {ema200} | {rsi} | {atr} | {overall} |"
            )
        
        # BUY signals summary
        buy_evals = [e for e in sorted_evals if e.overall_signal in ["STRONG_BUY", "BUY"]]
        if buy_evals:
            lines.append("")
            lines.append("### 🟢 BUY Signals Summary")
            lines.append("")
            lines.append(f"**Total BUY/STRONG_BUY:** {len(buy_evals)}")
            lines.append("")
            lines.append("| Rank | Ticker | Strategy | Score | Confidence | Reason |")
            lines.append("|------|--------|----------|-------|------------|--------|")
            
            for rank, eval_obj in enumerate(buy_evals, 1):
                # Get first BUY signal from any strategy
                buy_signal = None
                for strategy_eval in eval_obj.evaluations.values():
                    if strategy_eval.signal_action == "BUY":
                        buy_signal = strategy_eval
                        break
                
                if buy_signal:
                    confidence_pct = f"{buy_signal.confidence*100:.0f}%"
                    reason = buy_signal.reason[:50] if buy_signal.reason else "..."
                    lines.append(
                        f"| {rank} | {eval_obj.ticker} | {buy_signal.strategy_name} | "
                        f"{buy_signal.score:.1f} | {confidence_pct} | {reason} |"
                    )
        
        return "\n".join(lines)
    
    def _build_header(self, report_date: str) -> str:
        """Build report header."""
        return f"""# Daily Trading Report
**Date:** {report_date}  
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---"""
    
    def _build_market_summary(self, report_date: str) -> str:
        """
        Build market summary section.
        
        Fetches TOPIX benchmark data for context.
        """
        try:
            # Load TOPIX benchmark data using BenchmarkManager
            from ..data.benchmark_manager import BenchmarkManager
            
            benchmark_manager = BenchmarkManager(client=None, data_root=self.data_manager.data_root)
            df_topix = benchmark_manager.get_topix_data()
            
            if df_topix is None or df_topix.empty:
                return self._build_market_summary_unavailable()
            
            import pandas as pd
            df_topix['Date'] = pd.to_datetime(df_topix['Date'])
            
            # Get data for report date and previous date
            target_date = pd.Timestamp(report_date)
            df_topix = df_topix.sort_values('Date')
            
            # Find closest date <= target_date
            mask = df_topix['Date'] <= target_date
            if not mask.any():
                return self._build_market_summary_unavailable()
            
            current_row = df_topix[mask].iloc[-1]
            topix_close = current_row['Close']
            current_date = current_row['Date'].strftime("%Y-%m-%d")
            
            # Calculate change from previous day
            topix_change_pct = None
            if len(df_topix[mask]) >= 2:
                prev_row = df_topix[mask].iloc[-2]
                prev_close = prev_row['Close']
                topix_change_pct = ((topix_close - prev_close) / prev_close) * 100
            
            # Determine market condition
            market_condition = "Neutral"
            if topix_change_pct is not None:
                if topix_change_pct > 1.0:
                    market_condition = "🟢 Strong Bullish"
                elif topix_change_pct > 0.3:
                    market_condition = "🟢 Bullish"
                elif topix_change_pct < -1.0:
                    market_condition = "🔴 Strong Bearish"
                elif topix_change_pct < -0.3:
                    market_condition = "🔴 Bearish"
                else:
                    market_condition = "⚪ Neutral"
            
            # Build section
            lines = [
                "## 📊 Market Summary",
                "",
                f"**TOPIX Index:** {topix_close:,.2f}"
            ]
            
            if topix_change_pct is not None:
                change_sign = "+" if topix_change_pct >= 0 else ""
                lines.append(f"**Daily Change:** {change_sign}{topix_change_pct:.2f}%")
            
            lines.append(f"**Market Condition:** {market_condition}")
            lines.append(f"**Data Date:** {current_date}")
            
            return "\n".join(lines)
            
        except Exception as e:
            print(f"Warning: Failed to load TOPIX data: {e}")
            return self._build_market_summary_unavailable()
    
    def _build_market_summary_unavailable(self) -> str:
        """Fallback when TOPIX data unavailable."""
        return """## 📊 Market Summary

**TOPIX Index:** N/A  
**Market Condition:** Data unavailable"""
    
    def _build_buy_signals_section(self, buy_signals: List[Signal]) -> str:
        """
        Build BUY signals section.
        
        Sorts by score (descending) and displays top opportunities.
        """
        if not buy_signals:
            return """## 🟢 BUY Signals

*No BUY signals generated.*"""
        
        # Sort by score descending
        sorted_signals = sorted(buy_signals, key=lambda s: s.score, reverse=True)
        
        lines = [
            "## 🟢 BUY Signals",
            "",
            f"**Total Opportunities:** {len(sorted_signals)}",
            ""
        ]
        
        # Table header
        lines.append("| Rank | Ticker | Score | Confidence | Strategy | Qty | Capital (¥) |")
        lines.append("|------|--------|-------|-----------|----------|-----|-------------|")
        
        # Table rows
        for rank, signal in enumerate(sorted_signals, 1):
            qty_str = str(signal.suggested_qty) if signal.suggested_qty else "N/A"
            capital_str = f"{signal.required_capital:,.0f}" if signal.required_capital else "N/A"
            confidence_pct = f"{signal.confidence*100:.0f}%" if signal.confidence else "N/A"
            
            lines.append(
                f"| {rank} | **{signal.ticker}** | {signal.score:.1f} | "
                f"{confidence_pct} | {signal.strategy_name} | {qty_str} | {capital_str} |"
            )
        
        # Add details for top 3
        lines.append("")
        lines.append("### Top Opportunities Details")
        lines.append("")
        
        for signal in sorted_signals[:3]:
            lines.append(f"#### {signal.ticker} (Score: {signal.score:.1f})")
            lines.append(f"- **Strategy:** {signal.strategy_name}")
            lines.append(f"- **Confidence:** {signal.confidence*100:.0f}%")
            lines.append(f"- **Current Price:** ¥{signal.current_price:,.0f}")
            
            if signal.suggested_qty and signal.required_capital:
                lines.append(f"- **Recommended Qty:** {signal.suggested_qty} shares")
                lines.append(f"- **Capital Required:** ¥{signal.required_capital:,.0f}")
            
            if signal.reason:
                lines.append(f"- **Reason:** {signal.reason}")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def _build_sell_signals_section(self, sell_signals: List[Signal]) -> str:
        """
        Build SELL signals section.
        
        Sorts by urgency derived from action.
        """
        if not sell_signals:
            return """## 🔴 SELL Signals

*No SELL signals generated.*"""
        
        # Derive urgency from action and reason
        def get_urgency(signal: Signal) -> str:
            if "EMERGENCY" in signal.reason.upper() or "STOP" in signal.reason.upper():
                return "EMERGENCY"
            elif signal.action == "SELL_100%":
                return "HIGH"
            elif signal.action in ["SELL_75%", "SELL_50%"]:
                return "MEDIUM"
            else:
                return "LOW"
        
        # Add urgency field temporarily for sorting
        for sig in sell_signals:
            if not hasattr(sig, 'urgency_derived'):
                sig.urgency_derived = get_urgency(sig)
        
        # Sort by urgency (custom order)
        urgency_order = {"EMERGENCY": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        sorted_signals = sorted(
            sell_signals, 
            key=lambda s: (urgency_order.get(s.urgency_derived, 99), -s.score)
        )
        
        lines = [
            "## 🔴 SELL Signals",
            "",
            f"**Total Exit Recommendations:** {len(sorted_signals)}",
            ""
        ]
        
        # Table header
        lines.append("| Urgency | Ticker | Score | Action | Reason | Strategy |")
        lines.append("|---------|--------|-------|--------|--------|----------|")
        
        # Table rows with urgency icons
        urgency_icons = {
            "EMERGENCY": "🚨",
            "HIGH": "⚠️",
            "MEDIUM": "⚡",
            "LOW": "ℹ️"
        }
        
        for signal in sorted_signals:
            icon = urgency_icons.get(signal.urgency_derived, "")
            urgency_display = f"{icon} {signal.urgency_derived}"
            
            lines.append(
                f"| {urgency_display} | **{signal.ticker}** | {signal.score:.1f} | "
                f"{signal.action} | {signal.reason or 'N/A'} | {signal.strategy_name} |"
            )
        
        # Add details for high urgency
        high_urgency = [s for s in sorted_signals if s.urgency_derived in ("EMERGENCY", "HIGH")]
        
        if high_urgency:
            lines.append("")
            lines.append("### High Urgency Details")
            lines.append("")
            
            for signal in high_urgency:
                lines.append(f"#### {signal.ticker} ({signal.urgency_derived})")
                lines.append(f"- **Action:** {signal.action}")
                lines.append(f"- **Reason:** {signal.reason or 'N/A'}")
                lines.append(f"- **Current Score:** {signal.score:.1f}")
                lines.append(f"- **Current Price:** ¥{signal.current_price:,.0f}")
                lines.append(f"- **Strategy:** {signal.strategy_name}")
                
                if signal.position_qty and signal.entry_price:
                    lines.append(f"- **Position:** {signal.position_qty} shares @ ¥{signal.entry_price:,.0f}")
                    if signal.unrealized_pl_pct is not None:
                        lines.append(f"- **P&L:** {signal.unrealized_pl_pct:+.2f}%")
                
                lines.append("")
        
        return "\n".join(lines)
    
    def _build_portfolio_status_section(self) -> str:
        """
        Build current portfolio status section.
        
        Shows all positions across all strategy groups with P&L.
        """
        lines = [
            "## 💼 Current Portfolio Status",
            ""
        ]
        
        # Overall status
        status = self.state_manager.get_portfolio_status()
        total_value = status['total_value']
        
        lines.append(f"**Total Portfolio Value:** ¥{total_value:,.0f}")
        lines.append(f"**Number of Strategy Groups:** {status['num_groups']}")
        lines.append("")
        
        # Per-group breakdown
        for group_status in status['groups']:
            lines.append(f"### {group_status['name']}")
            lines.append("")
            lines.append(f"**Cash Available:** ¥{group_status['current_cash']:,.0f}")
            lines.append(f"**Position Value:** ¥{group_status['invested']:,.0f}")
            lines.append(f"**Total Value:** ¥{group_status['total_value']:,.0f}")
            lines.append(f"**Number of Positions:** {group_status['num_positions']}")
            lines.append("")
            
            # Get positions for this group from strategy_groups
            group_obj = self.state_manager.get_group(group_status['id'])
            if group_obj and group_obj.positions:
                lines.append("| Ticker | Shares | Avg Price | Current Price | P&L (¥) | P&L (%) | Value (¥) |")
                lines.append("|--------|--------|-----------|---------------|---------|---------|-----------|")
                
                for pos in group_obj.positions:
                    # Use peak_price as proxy for current price (or entry_price if not updated)
                    # In production, you'd pass current_prices dict to get_portfolio_status()
                    current_price = pos.peak_price if pos.peak_price > pos.entry_price else pos.entry_price
                    current_value = pos.quantity * current_price
                    cost_basis = pos.quantity * pos.entry_price
                    pnl_jpy = current_value - cost_basis
                    pnl_pct = (pnl_jpy / cost_basis) * 100 if cost_basis > 0 else 0
                    
                    pnl_jpy_str = f"{pnl_jpy:+,.0f}"
                    pnl_pct_str = f"{pnl_pct:+.2f}%"
                    
                    lines.append(
                        f"| {pos.ticker} | {pos.quantity} | "
                        f"¥{pos.entry_price:,.0f} | ¥{current_price:,.0f} | "
                        f"{pnl_jpy_str} | {pnl_pct_str} | ¥{current_value:,.0f} |"
                    )
                
                lines.append("")
            else:
                lines.append("*No open positions.*")
                lines.append("")
        
        return "\n".join(lines)
    
    def _build_execution_summary_section(
        self, 
        execution_results: List[ExecutionResult]
    ) -> str:
        """
        Build execution summary section.
        
        Shows which trades were executed and outcomes.
        """
        if not execution_results:
            return ""
        
        lines = [
            "## ✅ Execution Summary",
            "",
            f"**Total Signals Processed:** {len(execution_results)}",
            ""
        ]
        
        # Separate successful and failed
        successful = [r for r in execution_results if r.success]
        failed = [r for r in execution_results if not r.success]
        
        lines.append(f"**Successful Executions:** {len(successful)}")
        lines.append(f"**Failed Executions:** {len(failed)}")
        lines.append("")
        
        # Successful executions table
        if successful:
            lines.append("### ✅ Successful Executions")
            lines.append("")
            lines.append("| Ticker | Type | Qty | Price | Capital/Proceeds | Strategy |")
            lines.append("|--------|------|-----|-------|------------------|----------|")
            
            for result in successful:
                signal = result.signal
                qty_str = str(signal.suggested_qty) if signal.signal_type == "BUY" else str(signal.position_qty)
                qty_str = qty_str if qty_str and qty_str != "None" else "N/A"
                
                if signal.signal_type == "BUY":
                    amount = signal.required_capital
                    amount_str = f"¥{amount:,.0f}" if amount else "N/A"
                else:  # SELL
                    # Extract proceeds from message if available
                    amount_str = "N/A"
                    if result.reason and "Proceeds:" in result.reason:
                        try:
                            amount_str = result.reason.split("Proceeds:")[1].split(",")[0].strip()
                        except:
                            pass
                
                lines.append(
                    f"| {signal.ticker} | {signal.signal_type} | {qty_str} | "
                    f"¥{signal.current_price:,.0f} | {amount_str} | {signal.strategy_name} |"
                )
            
            lines.append("")
        
        # Failed executions
        if failed:
            lines.append("### ❌ Failed Executions")
            lines.append("")
            
            for result in failed:
                signal = result.signal
                lines.append(f"- **{signal.ticker}** ({signal.signal_type}): {result.reason}")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def _build_footer(self) -> str:
        """Build report footer."""
        return """---

**Report generated by J-Stock-Analyzer Production System**  
*For internal use only. Not financial advice.*"""
    
    def save_report(
        self, 
        report_content: str, 
        filepath: str
    ) -> str:
        """
        Save report to file.
        
        Args:
            report_content: Markdown report string
            filepath: Full path to save report file (e.g., output/report/2026-01-21.md)
        
        Returns:
            Path to saved report file
        """
        # Create parent directories if needed
        output_path = Path(filepath).parent
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Save file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        return str(filepath)


def load_signals_from_file(signals_file: str) -> List[Signal]:
    """
    Load signals from JSON file.
    
    Args:
        signals_file: Path to signals JSON file (e.g., signals_2026-01-21.json)
    
    Returns:
        List of Signal objects
    """
    with open(signals_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    signals = []
    for item in data.get('signals', []):
        signal = Signal(
            group_id=item['group_id'],
            ticker=item['ticker'],
            ticker_name=item.get('ticker_name', ''),
            signal_type=item['signal_type'],
            action=item['action'],
            confidence=item['confidence'],
            score=item['score'],
            reason=item['reason'],
            current_price=item['current_price'],
            position_qty=item.get('position_qty'),
            entry_price=item.get('entry_price'),
            entry_date=item.get('entry_date'),
            holding_days=item.get('holding_days'),
            unrealized_pl_pct=item.get('unrealized_pl_pct'),
            suggested_qty=item.get('suggested_qty'),
            required_capital=item.get('required_capital'),
            strategy_name=item.get('strategy_name', ''),
            timestamp=item.get('timestamp', datetime.now().isoformat())
        )
        signals.append(signal)
    
    return signals
