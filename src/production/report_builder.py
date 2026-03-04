"""
Phase 4: Report Building Module

Generates Markdown daily trading reports from signals and portfolio state.
"""

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..data.stock_data_manager import StockDataManager
from .signal_generator import Signal
from .state_manager import ProductionState
from .state_manager import CashHistoryManager
from .state_manager import TradeHistoryManager
from .trade_executor import ExecutionResult


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
        data_manager: StockDataManager,
        history_file: Optional[str] = None,
        cash_history_file: Optional[str] = None,
        initial_capital_override: Optional[float] = None,
    ):
        """
        Initialize report builder.

        Args:
            state_manager: Current portfolio state
            data_manager: For fetching market data (TOPIX benchmark)
        """
        self.state_manager = state_manager
        self.data_manager = data_manager
        self.initial_capital_override = (
            float(initial_capital_override)
            if initial_capital_override is not None
            else None
        )
        self.trade_history_manager: Optional[TradeHistoryManager] = None
        self.cash_history_manager: Optional[CashHistoryManager] = None
        if history_file:
            try:
                self.trade_history_manager = TradeHistoryManager(history_file=history_file)
            except Exception:
                self.trade_history_manager = None
        if cash_history_file:
            try:
                self.cash_history_manager = CashHistoryManager(
                    cash_history_file=cash_history_file
                )
            except Exception:
                self.cash_history_manager = None

    def generate_daily_report(
        self,
        signals: List[Signal] = None,
        execution_results: Optional[List[ExecutionResult]] = None,
        report_date: Optional[str] = None,
        comprehensive_evaluations: Dict = None,  # New: Complete evaluation table
        overlay_summary: Optional[List[Dict]] = None,
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

        if signals is None:
            signals = []

        # Use comprehensive evaluations if provided, otherwise fall back to signals
        if comprehensive_evaluations:
            return self._generate_comprehensive_report(
                comprehensive_evaluations,
                signals,
                execution_results,
                report_date,
                overlay_summary,
            )

        # Legacy path: signals-only report
        buy_signals = [s for s in signals if s.signal_type == "BUY"]
        sell_signals = [s for s in signals if s.signal_type == "SELL"]

        # Build sections
        sections = []
        sections.append(self._build_header(report_date))
        sections.append(self._build_market_summary(report_date))
        if overlay_summary:
            sections.append(self._build_overlay_summary_section(overlay_summary))
            sections.append(
                self._build_overlay_effect_audit_section(signals, overlay_summary)
            )
        sections.append(self._build_buy_signals_section(buy_signals))
        sections.append(self._build_sell_signals_section(sell_signals))
        sections.append(self._build_portfolio_status_section(report_date))
        sections.append(self._build_performance_summary_section(report_date))

        if execution_results:
            sections.append(self._build_execution_summary_section(execution_results))

        sections.append(self._build_footer())

        return "\n\n".join(sections)

    def _generate_comprehensive_report(
        self,
        evaluations: Dict,
        signals: List[Signal],
        execution_results: Optional[List[ExecutionResult]],
        report_date: str,
        overlay_summary: Optional[List[Dict]],
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
        if overlay_summary:
            sections.append(self._build_overlay_summary_section(overlay_summary))
            sections.append(
                self._build_overlay_effect_audit_section(signals, overlay_summary)
            )

        # NEW: Complete evaluation table (all 61 stocks × strategies)
        sections.append(
            self._build_comprehensive_evaluation_section(evaluations, signals)
        )

        # Actionable recommendations from signals
        sections.append(self._build_actionable_recommendations(signals))

        # Final picks from ranked executable BUY signals
        sections.append(self._build_final_picks(evaluations, signals))

        # Current portfolio with exit evaluations
        sections.append(self._build_portfolio_status_section(report_date))
        sections.append(self._build_performance_summary_section(report_date))

        if execution_results:
            sections.append(self._build_execution_summary_section(execution_results))

        sections.append(self._build_footer())

        return "\n\n".join(sections)

    def _build_overlay_summary_section(self, overlay_summary: List[Dict]) -> str:
        lines = [
            "## 🧭 Overlay Summary",
            "",
            "### EN",
            "",
        ]
        for item in overlay_summary:
            group_id = item.get("group_id", "N/A")
            group_name = item.get("group_name", "N/A")
            combined = item.get("combined", {})
            metadata = combined.get("metadata", {})
            per_overlay = item.get("overlays", [])
            regime = None
            for overlay_meta in metadata.values():
                if isinstance(overlay_meta, dict) and "regime" in overlay_meta:
                    regime = overlay_meta.get("regime")
                    break
            parts = [f"{group_name} ({group_id})"]
            if regime:
                parts.append(f"Regime: {regime}")
            if combined.get("target_exposure") is not None:
                parts.append(f"Target Exposure: {combined.get('target_exposure')}")
            if combined.get("position_scale") is not None:
                parts.append(f"Position Scale: {combined.get('position_scale')}")
            if combined.get("max_new_positions") is not None:
                parts.append(f"Max New Positions: {combined.get('max_new_positions')}")
            if combined.get("block_new_entries"):
                parts.append("New Entries: BLOCKED")
            if combined.get("force_exit"):
                parts.append("Force Exit: ENABLED")
            exit_overrides = combined.get("exit_overrides") or {}
            parts.append(f"Exit Overrides: {len(exit_overrides)}")
            lines.append("- " + " | ".join(parts))

            lines.append("  - Combined Decision:")
            lines.append(
                f"    - target_exposure={combined.get('target_exposure')} | "
                f"position_scale={combined.get('position_scale')} | "
                f"max_new_positions={combined.get('max_new_positions')} | "
                f"block_new_entries={combined.get('block_new_entries')} | "
                f"force_exit={combined.get('force_exit')}"
            )

            if exit_overrides:
                lines.append("  - Triggered Exit Overrides:")
                for ticker, reason in sorted(exit_overrides.items()):
                    lines.append(f"    - {ticker}: {reason}")

            if per_overlay:
                lines.append("  - Overlay Metrics & Judgement:")
                for decision in per_overlay:
                    source = decision.get("source", "UnknownOverlay")
                    lines.append(f"    - {source}:")
                    lines.append(
                        "      - decision: "
                        f"target_exposure={decision.get('target_exposure')}, "
                        f"position_scale={decision.get('position_scale')}, "
                        f"max_new_positions={decision.get('max_new_positions')}, "
                        f"block_new_entries={decision.get('block_new_entries')}, "
                        f"force_exit={decision.get('force_exit')}, "
                        f"exit_overrides={len(decision.get('exit_overrides') or {})}"
                    )

                    overlay_meta = decision.get("metadata")
                    if isinstance(overlay_meta, dict) and overlay_meta:
                        lines.append("      - metrics:")
                        for key in sorted(overlay_meta.keys()):
                            lines.append(f"        - {key}: {overlay_meta.get(key)}")

        lines.append("")
        lines.append("### 中文")
        lines.append("")

        for item in overlay_summary:
            group_id = item.get("group_id", "N/A")
            group_name = item.get("group_name", "N/A")
            combined = item.get("combined", {})
            metadata = combined.get("metadata", {})
            per_overlay = item.get("overlays", [])
            regime = None
            for overlay_meta in metadata.values():
                if isinstance(overlay_meta, dict) and "regime" in overlay_meta:
                    regime = overlay_meta.get("regime")
                    break

            parts_zh = [f"{group_name} ({group_id})"]
            if regime:
                parts_zh.append(f"状态: {regime}")
            if combined.get("target_exposure") is not None:
                parts_zh.append(f"目标仓位暴露: {combined.get('target_exposure')}")
            if combined.get("position_scale") is not None:
                parts_zh.append(f"仓位缩放: {combined.get('position_scale')}")
            if combined.get("max_new_positions") is not None:
                parts_zh.append(f"当日最大新开仓: {combined.get('max_new_positions')}")
            if combined.get("block_new_entries"):
                parts_zh.append("新开仓: 阻断")
            if combined.get("force_exit"):
                parts_zh.append("强制退出: 开启")

            exit_overrides = combined.get("exit_overrides") or {}
            parts_zh.append(f"覆盖卖出数: {len(exit_overrides)}")
            lines.append("- " + " | ".join(parts_zh))

            lines.append("  - 组合决策:")
            lines.append(
                f"    - 目标仓位暴露(target_exposure)={combined.get('target_exposure')} | "
                f"仓位缩放(position_scale)={combined.get('position_scale')} | "
                f"当日最大新开仓(max_new_positions)={combined.get('max_new_positions')} | "
                f"阻断新开仓(block_new_entries)={combined.get('block_new_entries')} | "
                f"强制退出(force_exit)={combined.get('force_exit')}"
            )

            if exit_overrides:
                lines.append("  - 覆盖卖出明细:")
                for ticker, reason in sorted(exit_overrides.items()):
                    lines.append(f"    - {ticker}: {reason}")

            if per_overlay:
                lines.append("  - Overlay 指标与判断:")
                for decision in per_overlay:
                    source = decision.get("source", "UnknownOverlay")
                    lines.append(f"    - {source}:")
                    lines.append(
                        "      - 决策: "
                        f"目标仓位暴露(target_exposure)={decision.get('target_exposure')}, "
                        f"仓位缩放(position_scale)={decision.get('position_scale')}, "
                        f"当日最大新开仓(max_new_positions)={decision.get('max_new_positions')}, "
                        f"阻断新开仓(block_new_entries)={decision.get('block_new_entries')}, "
                        f"强制退出(force_exit)={decision.get('force_exit')}, "
                        f"覆盖卖出数(exit_overrides)={len(decision.get('exit_overrides') or {})}"
                    )

                    overlay_meta = decision.get("metadata")
                    if isinstance(overlay_meta, dict) and overlay_meta:
                        lines.append("      - 指标:")
                        for key in sorted(overlay_meta.keys()):
                            label_zh = self._translate_overlay_metric_key(key)
                            lines.append(
                                f"        - {label_zh}: {overlay_meta.get(key)}"
                            )

        lines.append("")
        lines.append("### 附录：Overlay 指标释义")
        lines.append("")
        lines.append(
            "- `strong_ratio`：强势板块占比，表示当日被判定为强势的板块数量 / 有效板块数量。"
        )
        lines.append(
            "- `weak_ratio`：弱势板块占比，表示当日被判定为弱势的板块数量 / 有效板块数量。"
        )
        lines.append(
            "- `valid_sector_count`：有效板块数量，表示当日有足够数据并参与 Overlay 统计的板块数。"
        )
        lines.append(
            "- 解释示例：`strong_ratio=0.24` 与 `weak_ratio=0.32` 意味着弱势板块比例高于强势板块比例，叠加风控后更可能给出偏保守仓位决策。"
        )

        return "\n".join(lines).strip()

    def _translate_overlay_metric_key(self, key: str) -> str:
        key_map = {
            "latest_date": "最新交易日 (latest_date)",
            "low_coverage_ratio": "低覆盖板块占比 (low_coverage_ratio)",
            "median_sector_score": "板块得分中位数 (median_sector_score)",
            "metrics_file": "指标文件路径 (metrics_file)",
            "regime": "市场状态 (regime)",
            "sector_count": "板块总数 (sector_count)",
            "snapshot_dir": "快照目录 (snapshot_dir)",
            "status": "状态 (status)",
            "strong_ratio": "强势板块占比 (strong_ratio)",
            "valid_sector_count": "有效板块数 (valid_sector_count)",
            "weak_ratio": "弱势板块占比 (weak_ratio)",
        }
        return key_map.get(key, key)

    def _build_overlay_effect_audit_section(
        self,
        signals: List[Signal],
        overlay_summary: Optional[List[Dict]],
    ) -> str:
        signals = signals or []
        overlay_summary = overlay_summary or []

        blocked_buy_signals = [
            s
            for s in signals
            if s.signal_type == "BUY"
            and "overlay blocked new entries" in (s.reason or "").lower()
        ]
        overlay_sell_signals = [
            s
            for s in signals
            if s.signal_type == "SELL"
            and (
                (s.strategy_name or "") == "Overlay"
                or "overlay" in (s.reason or "").lower()
            )
        ]

        blocked_buy_count = len(blocked_buy_signals)
        overlay_sell_count = len(overlay_sell_signals)

        blocked_buy_tickers = sorted({s.ticker for s in blocked_buy_signals})
        overlay_sell_tickers = sorted({s.ticker for s in overlay_sell_signals})

        lines = [
            "## 🧪 Overlay Effect Audit",
            "",
            "### EN",
            "",
            f"- Blocked BUY signals by overlay: {blocked_buy_count}",
            f"- Overlay-triggered SELL signals: {overlay_sell_count}",
            f"- Blocked BUY tickers: {', '.join(blocked_buy_tickers) if blocked_buy_tickers else 'None'}",
            f"- Overlay SELL tickers: {', '.join(overlay_sell_tickers) if overlay_sell_tickers else 'None'}",
            "",
            "### 中文",
            "",
            f"- 当日被 overlay 阻断的买入信号数: {blocked_buy_count}",
            f"- 当日由 overlay 触发的卖出信号数: {overlay_sell_count}",
            f"- 被阻断买入标的: {', '.join(blocked_buy_tickers) if blocked_buy_tickers else '无'}",
            f"- overlay 触发卖出标的: {', '.join(overlay_sell_tickers) if overlay_sell_tickers else '无'}",
        ]

        if overlay_summary:
            lines.extend(["", "### Per Group", ""])
            for item in overlay_summary:
                group_id = item.get("group_id", "N/A")
                group_name = item.get("group_name", "N/A")
                combined = item.get("combined", {})
                lines.append(
                    f"- {group_name} ({group_id}): "
                    f"block_new_entries={combined.get('block_new_entries')}, "
                    f"max_new_positions={combined.get('max_new_positions')}, "
                    f"target_exposure={combined.get('target_exposure')}, "
                    f"exit_overrides={len(combined.get('exit_overrides') or {})}"
                )

        return "\n".join(lines).strip()

    def _build_comprehensive_evaluation_section(
        self, evaluations: Dict, signals: List[Signal]
    ) -> str:
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
            "",
        ]

        buy_signals = [s for s in (signals or []) if s.signal_type == "BUY"]
        best_buy_by_ticker: Dict[str, Signal] = {}
        for sig in buy_signals:
            current = best_buy_by_ticker.get(sig.ticker)
            if current is None:
                best_buy_by_ticker[sig.ticker] = sig
                continue
            current_exec = 1 if (current.suggested_qty or 0) > 0 else 0
            sig_exec = 1 if (sig.suggested_qty or 0) > 0 else 0
            current_cap = (
                current.required_capital if current.required_capital else float("inf")
            )
            sig_cap = sig.required_capital if sig.required_capital else float("inf")
            current_key = (
                current_exec,
                -current.score,
                -current.confidence,
                -current_cap,
            )
            sig_key = (sig_exec, -sig.score, -sig.confidence, -sig_cap)
            if sig_key > current_key:
                best_buy_by_ticker[sig.ticker] = sig

        # Sort by overall signal, executable priority, then affordability
        sorted_evals = sorted(
            evaluations.values(),
            key=lambda e: (
                {"STRONG_BUY": 0, "BUY": 1, "WEAK_BUY": 2, "HOLD": 3}.get(
                    e.overall_signal, 99
                ),
                0
                if (
                    best_buy_by_ticker.get(e.ticker)
                    and (best_buy_by_ticker[e.ticker].suggested_qty or 0) > 0
                )
                else 1,
                (
                    best_buy_by_ticker.get(e.ticker).required_capital
                    if (
                        best_buy_by_ticker.get(e.ticker)
                        and best_buy_by_ticker[e.ticker].required_capital
                    )
                    else float("inf")
                ),
                -e.current_price,
            ),
        )

        # Main evaluation table (dynamic strategy columns)
        strategy_names = []
        for eval_obj in evaluations.values():
            for name in eval_obj.evaluations.keys():
                if name not in strategy_names:
                    strategy_names.append(name)
        strategy_names = sorted(strategy_names)

        lines.append("### Main Evaluation Table")
        lines.append("")

        strategy_header = " | ".join(strategy_names) if strategy_names else "Strategies"
        lines.append(
            "| Ticker | Name | Price | "
            f"{strategy_header} | EMA20 | EMA50 | EMA200 | RSI | ATR | Overall |"
        )
        lines.append(
            "|--------|------|-------|"
            + "|".join(["----------------------"] * max(len(strategy_names), 1))
            + "|-------|-------|--------|-----|-----|---------|"
        )

        # Table rows
        for eval_obj in sorted_evals:
            ticker = eval_obj.ticker
            price = f"¥{eval_obj.current_price:,.0f}"

            # Get signals from each strategy (if available)
            strategy_cells = []
            if strategy_names:
                for strategy_name in strategy_names:
                    strategy_eval = eval_obj.evaluations.get(strategy_name)
                    strategy_cells.append(
                        f"{strategy_eval.signal_action}" if strategy_eval else "—"
                    )
            else:
                strategy_cells.append("—")

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
                "HOLD": "⚪",
            }.get(eval_obj.overall_signal, "⚪")

            overall = f"{signal_emoji} {eval_obj.overall_signal}"

            strategy_row = " | ".join(strategy_cells)
            lines.append(
                f"| {ticker} | {eval_obj.ticker_name[:15]} | {price} | "
                f"{strategy_row} | {ema20} | {ema50} | {ema200} | {rsi} | {atr} | {overall} |"
            )

        # BUY signals summary (executable-first ranking)
        buy_evals = [
            e for e in sorted_evals if e.overall_signal in ["STRONG_BUY", "BUY"]
        ]
        if buy_evals:
            lines.append("")
            lines.append("### 🟢 BUY Signals Summary")
            lines.append("")
            lines.append(f"**Total BUY/STRONG_BUY:** {len(buy_evals)}")
            lines.append("")
            lines.append(
                "| Rank | Ticker | Strategy | Score | Confidence | Qty | Capital (¥) | Reason |"
            )
            lines.append(
                "|------|--------|----------|-------|------------|-----|-------------|--------|"
            )

            ranked_signals = []
            for eval_obj in buy_evals:
                best_signal = best_buy_by_ticker.get(eval_obj.ticker)
                if best_signal:
                    ranked_signals.append(best_signal)

            ranked_signals = sorted(
                ranked_signals,
                key=lambda s: (
                    0 if (s.suggested_qty or 0) > 0 else 1,
                    s.required_capital if s.required_capital else float("inf"),
                    -s.score,
                    -s.confidence,
                ),
            )

            for rank, sig in enumerate(ranked_signals, 1):
                confidence_pct = f"{sig.confidence * 100:.0f}%"
                qty_str = str(sig.suggested_qty) if sig.suggested_qty else "0"
                capital_str = (
                    f"{sig.required_capital:,.0f}" if sig.required_capital else "0"
                )
                reason = (sig.reason or "...").replace("|", "/")
                lines.append(
                    f"| {rank} | {sig.ticker} | {sig.strategy_name} | "
                    f"{sig.score:.1f} | {confidence_pct} | {qty_str} | {capital_str} | {reason} |"
                )

        return "\n".join(lines)

    def _build_actionable_recommendations(self, signals: List[Signal]) -> str:
        """Build actionable buy/sell recommendations from signals."""
        buy_signals = [s for s in signals if s.signal_type == "BUY"]
        sell_signals = [s for s in signals if s.signal_type == "SELL"]

        lines = [
            "## ✅ Actionable Trade Recommendations",
            "",
            "### 🟢 BUY (Executable First)",
            "",
        ]

        if buy_signals:
            sorted_buy = sorted(
                buy_signals,
                key=lambda s: (
                    0 if (s.suggested_qty or 0) > 0 else 1,
                    s.required_capital if s.required_capital else float("inf"),
                    -s.score,
                    -s.confidence,
                ),
            )
            lines.append(
                "| Rank | Group | Ticker | Price | Strategy | Score | Confidence | Qty | Capital (¥) | Reason |"
            )
            lines.append(
                "|------|-------|--------|-------|----------|-------|------------|-----|-------------|--------|"
            )
            for rank, sig in enumerate(sorted_buy, 1):
                confidence_pct = (
                    f"{sig.confidence * 100:.0f}%"
                    if sig.confidence is not None
                    else "N/A"
                )
                qty_str = str(sig.suggested_qty) if sig.suggested_qty else "0"
                capital_str = (
                    f"{sig.required_capital:,.0f}" if sig.required_capital else "0"
                )
                reason = (sig.reason or "...").replace("|", "/")
                lines.append(
                    f"| {rank} | {sig.group_id} | {sig.ticker} | "
                    f"¥{sig.current_price:,.0f} | {sig.strategy_name} | {sig.score:.1f} | "
                    f"{confidence_pct} | {qty_str} | {capital_str} | {reason} |"
                )
        else:
            lines.append("*No BUY recommendations.*")

        lines.append("")
        lines.append("### 🔴 SELL (Holdings-Based)")
        lines.append("")

        # Collect all position-related signals (SELL and HOLD)
        signal_by_key = {}
        for sig in signals:
            if sig.signal_type in ["SELL", "HOLD"]:
                key = (sig.group_id, sig.ticker)
                signal_by_key[key] = sig

        lines.append(
            "| Group | Ticker | Shares | Sell Qty | Est. Proceeds (¥) | Current Price | P&L (%) | Recommend | Action | Exit Evaluation |"
        )
        lines.append(
            "|-------|--------|--------|----------|-------------------|---------------|---------|-----------|--------|-----------------|"
        )

        holdings_found = False
        for group in self.state_manager.get_all_groups():
            for pos in group.positions:
                if pos.quantity <= 0:
                    continue
                holdings_found = True
                key = (group.id, pos.ticker)
                sig = signal_by_key.get(key)

                # Get current price from signal or fallback to position data
                current_price = (
                    sig.current_price
                    if sig is not None and sig.current_price
                    else (
                        pos.peak_price
                        if pos.peak_price > pos.entry_price
                        else pos.entry_price
                    )
                )

                cost_basis = pos.entry_price
                pnl_pct = (
                    ((current_price - cost_basis) / cost_basis) * 100
                    if cost_basis > 0
                    else 0
                )
                pnl_pct_str = f"{pnl_pct:+.2f}%"

                # Determine recommendation and action
                recommend = (
                    "YES" if (sig is not None and sig.signal_type == "SELL") else "NO"
                )
                action = sig.action if sig is not None else "HOLD"

                sell_qty = "-"
                est_proceeds = "-"
                if sig is not None and sig.signal_type == "SELL":
                    planned_qty = getattr(sig, "planned_sell_qty", None)
                    if planned_qty is None:
                        if action in ["SELL_25%", "SELL_50%", "SELL_75%"]:
                            ratio_map = {
                                "SELL_25%": 0.25,
                                "SELL_50%": 0.50,
                                "SELL_75%": 0.75,
                            }
                            planned_qty = max(
                                1,
                                int(pos.quantity * ratio_map.get(action, 1.0)),
                            )
                        else:
                            planned_qty = pos.quantity
                    sell_qty = f"{int(planned_qty)}"

                    planned_value = getattr(sig, "planned_sell_value", None)
                    if planned_value is None:
                        planned_value = float(planned_qty) * float(current_price)
                    est_proceeds = f"{float(planned_value):,.0f}"

                # Format evaluation details
                if (
                    sig is not None
                    and hasattr(sig, "evaluation_details")
                    and sig.evaluation_details is not None
                ):
                    eval_text = self._format_evaluation_details(sig.evaluation_details)
                else:
                    eval_text = (
                        sig.reason if sig is not None else "No evaluation available"
                    ).replace("|", "/")

                lines.append(
                    f"| {group.id} | {pos.ticker} | {pos.quantity} | {sell_qty} | {est_proceeds} | "
                    f"¥{current_price:,.0f} | {pnl_pct_str} | {recommend} | {action} | {eval_text} |"
                )

        if not holdings_found:
            lines.append("| - | - | - | - | - | - | - | - | - | No holdings |")

        return "\n".join(lines)

    def _format_evaluation_details(self, details: Dict) -> str:
        """
        Format exit strategy evaluation details for display in report.

        Returns a compact string showing all layer statuses.
        """
        if not details or "layers" not in details:
            return "No details"

        layers = details["layers"]
        triggered = [layer for layer in layers if layer.get("triggered")]

        # Build comprehensive layer-by-layer display
        parts = []

        # If any triggered, show them prominently first
        if triggered:
            trigger_strs = []
            for layer in triggered:
                name = layer["name"].replace("_", " ")
                value = layer.get("value", "")
                threshold = layer.get("threshold", "")
                trigger_strs.append(f"🔴{name}: {value} vs {threshold}")
            parts.append("<br>".join(trigger_strs))

        # Show all non-triggered layers with appropriate icons
        non_triggered = [layer for layer in layers if not layer.get("triggered")]
        if non_triggered:
            layer_strs = []
            for layer in non_triggered:
                status = layer.get("status", "")
                name = layer["name"].replace("_", " ")
                value = layer.get("value", "")
                threshold = layer.get("threshold", "")

                # Choose icon based on status
                if status == "SAFE":
                    icon = "✅"
                elif status == "PENDING":
                    icon = "⏳"
                elif status == "PASS":
                    icon = "✓"
                else:
                    icon = "○"

                layer_strs.append(f"{icon}{name}: {value} vs {threshold}")

            parts.append("<br>".join(layer_strs))

        # Add summary line
        if "summary" in details:
            parts.append(f"[{details['summary']}]")

        return "<br>".join(parts)

        if not holdings_found:
            lines.append("| - | - | - | - | - | - | - | No holdings |")

        return "\n".join(lines)

    def _build_final_picks(self, evaluations: Dict, signals: List[Signal]) -> str:
        """Build final operation summary (SELL first, then BUY)."""
        lines = [
            "## ✅ Final Operation Summary",
            "",
            "**Execution Order:** SELL first (release cash/risk), then BUY (capacity-constrained).",
            "",
        ]

        buy_signals = [s for s in (signals or []) if s.signal_type == "BUY"]
        sell_signals = [s for s in (signals or []) if s.signal_type == "SELL"]

        best_buy_by_group_ticker: Dict[tuple, Signal] = {}
        for sig in buy_signals:
            key = (sig.group_id, sig.ticker)
            current = best_buy_by_group_ticker.get(key)
            if current is None:
                best_buy_by_group_ticker[key] = sig
                continue

            current_exec = 1 if (current.suggested_qty or 0) > 0 else 0
            sig_exec = 1 if (sig.suggested_qty or 0) > 0 else 0
            current_cap = (
                current.required_capital if current.required_capital else float("inf")
            )
            sig_cap = sig.required_capital if sig.required_capital else float("inf")
            current_key = (current_exec, current.score, current.confidence, -current_cap)
            sig_key = (sig_exec, sig.score, sig.confidence, -sig_cap)
            if sig_key > current_key:
                best_buy_by_group_ticker[key] = sig

        buys_by_group: Dict[str, List[Signal]] = {}
        for sig in best_buy_by_group_ticker.values():
            buys_by_group.setdefault(sig.group_id, []).append(sig)

        sells_by_group: Dict[str, List[Signal]] = {}
        for sig in sell_signals:
            sells_by_group.setdefault(sig.group_id, []).append(sig)

        any_operations = False

        for group in self.state_manager.get_all_groups():
            group_sells = sells_by_group.get(group.id, [])
            group_buys = buys_by_group.get(group.id, [])
            active_positions = len([p for p in group.positions if p.quantity > 0])

            executable_buys = sorted(
                [s for s in group_buys if (s.suggested_qty or 0) > 0],
                key=lambda s: (
                    -(s.score or 0.0),
                    -(s.confidence or 0.0),
                    s.required_capital if s.required_capital else float("inf"),
                    s.ticker,
                ),
            )

            executable_sells = []
            for sig in group_sells:
                planned_qty = getattr(sig, "planned_sell_qty", None)
                if planned_qty is None and (sig.position_qty or 0) > 0:
                    if sig.action in ["SELL_25%", "SELL_50%", "SELL_75%"]:
                        ratio_map = {
                            "SELL_25%": 0.25,
                            "SELL_50%": 0.50,
                            "SELL_75%": 0.75,
                        }
                        planned_qty = max(
                            1,
                            int((sig.position_qty or 0) * ratio_map.get(sig.action, 1.0)),
                        )
                    else:
                        planned_qty = sig.position_qty
                if (planned_qty or 0) > 0:
                    executable_sells.append(sig)

            executable_sells = sorted(executable_sells, key=lambda s: s.ticker)

            total_sell_qty = sum(int(getattr(s, "planned_sell_qty", 0) or 0) for s in executable_sells)
            total_sell_value = sum(float(getattr(s, "planned_sell_value", 0.0) or 0.0) for s in executable_sells)
            total_buy_capital = sum(float(s.required_capital or 0.0) for s in executable_buys)

            lines.append(f"### {group.name} ({group.id})")
            lines.append("")
            lines.append(
                f"**Current Positions:** {active_positions} | "
                f"**SELL Orders:** {len(executable_sells)} (Qty {total_sell_qty}, Est. ¥{total_sell_value:,.0f}) | "
                f"**BUY Orders:** {len(executable_buys)} (Est. ¥{total_buy_capital:,.0f})"
            )
            lines.append("")

            lines.append("#### 1) SELL Orders")
            sell_factor = next(
                (
                    s.sell_price_factor
                    for s in executable_sells
                    if getattr(s, "sell_price_factor", None)
                ),
                0.98,
            )
            buy_factor = next(
                (
                    s.planning_price_factor
                    for s in executable_buys
                    if getattr(s, "planning_price_factor", None)
                ),
                1.02,
            )
            lines.append("")
            lines.append(
                f"Pricing Rule: PlanningPrice=Close*{buy_factor:.2f}, SellPrice=Close*{sell_factor:.2f}"
            )
            lines.append("")
            if executable_sells:
                any_operations = True
                lines.append(
                    "| Rank | Ticker | Action | Close Price | Planned Sell Price (Close*SellFactor) | Sell Qty | Est. Proceeds (¥) | Reason |"
                )
                lines.append(
                    "|------|--------|--------|-------------|--------------------------------------|----------|-------------------|--------|"
                )
                for rank, sig in enumerate(executable_sells, 1):
                    planned_qty = int(getattr(sig, "planned_sell_qty", 0) or 0)
                    planned_value = float(getattr(sig, "planned_sell_value", 0.0) or 0.0)
                    close_price = float(
                        getattr(sig, "close_price", None)
                        if getattr(sig, "close_price", None) is not None
                        else (sig.current_price or 0.0)
                    )
                    planned_sell_price = getattr(sig, "planned_price", None)
                    if planned_sell_price is None and planned_qty > 0:
                        planned_sell_price = planned_value / planned_qty
                    reason = (sig.reason or "...").replace("|", "/")
                    lines.append(
                        f"| {rank} | {sig.ticker} | {sig.action} | ¥{close_price:,.2f} | "
                        f"¥{float(planned_sell_price or 0.0):,.2f} | {planned_qty} | {planned_value:,.0f} | {reason} |"
                    )
            else:
                lines.append("*No executable SELL orders.*")

            lines.append("")
            lines.append("#### 2) BUY Orders")
            lines.append("")
            lines.append(
                f"Pricing Rule: PlanningPrice=Close*{buy_factor:.2f}, SellPrice=Close*{sell_factor:.2f}"
            )
            lines.append("")
            if executable_buys:
                any_operations = True
                lines.append(
                    "| Rank | Ticker | Close Price | Planning Price (Close*PlanningFactor) | Score | Confidence | Qty | Capital (¥) | Reason |"
                )
                lines.append(
                    "|------|--------|-------------|---------------------------------------|-------|------------|-----|-------------|--------|"
                )
                for rank, sig in enumerate(executable_buys, 1):
                    confidence_pct = (
                        f"{sig.confidence * 100:.0f}%"
                        if sig.confidence is not None
                        else "N/A"
                    )
                    qty_str = str(sig.suggested_qty) if sig.suggested_qty else "0"
                    capital_str = (
                        f"{sig.required_capital:,.0f}" if sig.required_capital else "0"
                    )
                    planning_price = float(
                        getattr(sig, "planned_price", None)
                        if getattr(sig, "planned_price", None) is not None
                        else (sig.current_price or 0.0)
                    )
                    close_price = getattr(sig, "close_price", None)
                    if close_price is None:
                        factor = (
                            getattr(sig, "planning_price_factor", None)
                            if getattr(sig, "planning_price_factor", None)
                            else buy_factor
                        )
                        close_price = planning_price / factor if factor else planning_price
                    reason = (sig.reason or "...").replace("|", "/")
                    lines.append(
                        f"| {rank} | {sig.ticker} | ¥{float(close_price):,.2f} | ¥{planning_price:,.2f} | {sig.score:.1f} | "
                        f"{confidence_pct} | {qty_str} | {capital_str} | {reason} |"
                    )
            else:
                lines.append("*No executable BUY orders.*")

            lines.append("")

        if not any_operations:
            lines.append("*No executable operations across all groups today.*")

        return "\n".join(lines)

    def _sort_sell_signals(self, sell_signals: List[Signal]) -> List[Signal]:
        """Sort sell signals by urgency and score."""

        def get_urgency(signal: Signal) -> str:
            if signal.reason and "EMERGENCY" in signal.reason.upper():
                return "EMERGENCY"
            if signal.reason and "STOP" in signal.reason.upper():
                return "EMERGENCY"
            if signal.action == "SELL_100%":
                return "HIGH"
            if signal.action in ["SELL_75%", "SELL_50%"]:
                return "MEDIUM"
            return "LOW"

        for sig in sell_signals:
            if not hasattr(sig, "urgency_derived"):
                sig.urgency_derived = get_urgency(sig)

        urgency_order = {"EMERGENCY": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        return sorted(
            sell_signals,
            key=lambda s: (urgency_order.get(s.urgency_derived, 99), -s.score),
        )

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

            benchmark_manager = BenchmarkManager(
                client=None, data_root=self.data_manager.data_root
            )
            df_topix = benchmark_manager.get_topix_data()

            if df_topix is None or df_topix.empty:
                return self._build_market_summary_unavailable()

            import pandas as pd

            df_topix["Date"] = pd.to_datetime(df_topix["Date"])

            # Get data for report date and previous date
            target_date = pd.Timestamp(report_date)
            df_topix = df_topix.sort_values("Date")

            # Find closest date <= target_date
            mask = df_topix["Date"] <= target_date
            if not mask.any():
                return self._build_market_summary_unavailable()

            current_row = df_topix[mask].iloc[-1]
            topix_close = current_row["Close"]
            current_date = current_row["Date"].strftime("%Y-%m-%d")

            # Calculate change from previous day
            topix_change_pct = None
            if len(df_topix[mask]) >= 2:
                prev_row = df_topix[mask].iloc[-2]
                prev_close = prev_row["Close"]
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
            lines = ["## 📊 Market Summary", "", f"**TOPIX Index:** {topix_close:,.2f}"]

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
            "",
        ]

        # Table header
        lines.append(
            "| Rank | Ticker | Score | Confidence | Strategy | Qty | Capital (¥) |"
        )
        lines.append(
            "|------|--------|-------|-----------|----------|-----|-------------|"
        )

        # Table rows
        for rank, signal in enumerate(sorted_signals, 1):
            qty_str = str(signal.suggested_qty) if signal.suggested_qty else "N/A"
            capital_str = (
                f"{signal.required_capital:,.0f}" if signal.required_capital else "N/A"
            )
            confidence_pct = (
                f"{signal.confidence * 100:.0f}%" if signal.confidence else "N/A"
            )

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
            lines.append(f"- **Confidence:** {signal.confidence * 100:.0f}%")
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
            if not hasattr(sig, "urgency_derived"):
                sig.urgency_derived = get_urgency(sig)

        # Sort by urgency (custom order)
        urgency_order = {"EMERGENCY": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        sorted_signals = sorted(
            sell_signals,
            key=lambda s: (urgency_order.get(s.urgency_derived, 99), -s.score),
        )

        lines = [
            "## 🔴 SELL Signals",
            "",
            f"**Total Exit Recommendations:** {len(sorted_signals)}",
            "",
        ]

        # Table header
        lines.append("| Urgency | Ticker | Score | Action | Reason | Strategy |")
        lines.append("|---------|--------|-------|--------|--------|----------|")

        # Table rows with urgency icons
        urgency_icons = {"EMERGENCY": "🚨", "HIGH": "⚠️", "MEDIUM": "⚡", "LOW": "ℹ️"}

        for signal in sorted_signals:
            icon = urgency_icons.get(signal.urgency_derived, "")
            urgency_display = f"{icon} {signal.urgency_derived}"

            lines.append(
                f"| {urgency_display} | **{signal.ticker}** | {signal.score:.1f} | "
                f"{signal.action} | {signal.reason or 'N/A'} | {signal.strategy_name} |"
            )

        # Add details for high urgency
        high_urgency = [
            s for s in sorted_signals if s.urgency_derived in ("EMERGENCY", "HIGH")
        ]

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
                    lines.append(
                        f"- **Position:** {signal.position_qty} shares @ ¥{signal.entry_price:,.0f}"
                    )
                    if signal.unrealized_pl_pct is not None:
                        lines.append(f"- **P&L:** {signal.unrealized_pl_pct:+.2f}%")

                lines.append("")

        return "\n".join(lines)

    def _build_portfolio_status_section(self, report_date: Optional[str] = None) -> str:
        """
        Build current portfolio status section.

        Shows all positions across all strategy groups with P&L.
        """
        current_prices = self._collect_current_prices(report_date)

        lines = ["## 💼 Current Portfolio Status", ""]

        # Overall status
        status = self.state_manager.get_portfolio_status(current_prices)
        total_value = status["total_value"]

        lines.append(f"**Total Portfolio Value:** ¥{total_value:,.0f}")
        lines.append(f"**Number of Strategy Groups:** {status['num_groups']}")
        lines.append("")

        # Per-group breakdown
        for group_status in status["groups"]:
            lines.append(f"### {group_status['name']}")
            lines.append("")
            lines.append(f"**Cash Available:** ¥{group_status['current_cash']:,.0f}")
            lines.append(f"**Position Value:** ¥{group_status['invested']:,.0f}")
            lines.append(f"**Total Value:** ¥{group_status['total_value']:,.0f}")
            lines.append(f"**Number of Positions:** {group_status['num_positions']}")
            lines.append("")

            # Get positions for this group from strategy_groups
            group_obj = self.state_manager.get_group(group_status["id"])
            if group_obj and group_obj.positions:
                lines.append(
                    "| Ticker | Shares | Avg Price | Current Price | P&L (¥) | P&L (%) | Value (¥) |"
                )
                lines.append(
                    "|--------|--------|-----------|---------------|---------|---------|-----------|"
                )

                for pos in group_obj.positions:
                    current_price = current_prices.get(pos.ticker, pos.entry_price)
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

    def _collect_current_prices(self, report_date: Optional[str] = None) -> Dict[str, float]:
        current_prices: Dict[str, float] = {}
        for group in self.state_manager.get_all_groups():
            for pos in group.positions:
                if pos.quantity <= 0 or pos.ticker in current_prices:
                    continue
                latest_close = self._get_latest_close(pos.ticker, report_date)
                if latest_close is not None:
                    current_prices[pos.ticker] = latest_close
        return current_prices

    def _build_performance_summary_section(self, report_date: str) -> str:
        lines = ["## 📈 收益汇总", ""]

        realized = self._calculate_realized_performance(report_date)
        current_prices = self._collect_current_prices(report_date)
        unrealized = self._calculate_unrealized_performance(current_prices)

        lines.append("### 1) 历史交易股票收益")
        lines.append("")
        ticker_rows = realized["ticker_rows"]
        if ticker_rows:
            lines.append(
                "| 股票代码 | 分组 | 买入金额 (¥) | 卖出金额 (¥) | 已实现盈亏 (¥) | 已实现收益率 (%) | 卖出笔数 | 胜率 |"
            )
            lines.append(
                "|----------|------|---------------|---------------|----------------|------------------|---------|------|"
            )
            for row in ticker_rows:
                win_rate_str = f"{row['win_rate']:.1f}%" if row["win_rate"] is not None else "N/A"
                lines.append(
                    f"| {row['ticker']} | {row['group_id']} | {row['buy_amount']:,.0f} | {row['sell_amount']:,.0f} | "
                    f"{row['realized_pnl']:+,.0f} | {row['realized_return_pct']:+.2f}% | {row['sell_trades']} | {win_rate_str} |"
                )
            lines.append("")
            lines.append(
                f"**已实现盈亏合计：** {realized['realized_pnl']:+,.0f} JPY "
                f"({realized['realized_return_pct']:+.2f}%)"
            )
        else:
            lines.append("*暂无交易历史数据。*")

        lines.append("")
        lines.append("### 2) 当前持仓未实现收益")
        lines.append("")
        position_rows = unrealized["position_rows"]
        if position_rows:
            lines.append(
                "| 股票代码 | 分组 | 持仓数量 | 持仓成本 (¥) | 市值 (¥) | 未实现盈亏 (¥) | 未实现收益率 (%) |"
            )
            lines.append(
                "|----------|------|----------|--------------|----------|----------------|------------------|"
            )
            for row in position_rows:
                lines.append(
                    f"| {row['ticker']} | {row['group_id']} | {row['quantity']} | {row['cost_basis']:,.0f} | "
                    f"{row['market_value']:,.0f} | {row['unrealized_pnl']:+,.0f} | {row['unrealized_return_pct']:+.2f}% |"
                )
            lines.append("")
            lines.append(
                f"**未实现盈亏合计：** {unrealized['unrealized_pnl']:+,.0f} JPY "
                f"({unrealized['unrealized_return_pct']:+.2f}%)"
            )
        else:
            lines.append("*当前无持仓。*")

        lines.append("")
        lines.append("### 3) 组合盈亏汇总")
        lines.append("")

        portfolio_status = self.state_manager.get_portfolio_status(current_prices)
        total_value = float(portfolio_status.get("total_value", 0.0))
        baseline_initial_capital = float(
            sum(g.initial_capital for g in self.state_manager.get_all_groups())
        )
        if self.initial_capital_override is not None and self.initial_capital_override > 0:
            baseline_initial_capital = self.initial_capital_override

        net_cash_flow = 0.0
        if self.cash_history_manager:
            for event in self.cash_history_manager.events:
                event_date = getattr(event, "date", None)
                if not event_date:
                    continue
                if self._is_on_or_before(event_date, report_date):
                    net_cash_flow += float(getattr(event, "amount", 0.0) or 0.0)
        effective_initial_capital = baseline_initial_capital + net_cash_flow
        if effective_initial_capital <= 0:
            effective_initial_capital = baseline_initial_capital

        realized_pnl = float(realized["realized_pnl"])
        unrealized_pnl = float(unrealized["unrealized_pnl"])
        total_pnl = realized_pnl + unrealized_pnl
        implied_initial_capital = total_value - total_pnl
        total_return_pct = (
            ((total_value - effective_initial_capital) / effective_initial_capital) * 100
            if effective_initial_capital > 0
            else 0.0
        )

        lines.append(f"- **基准初始资金：** ¥{baseline_initial_capital:,.0f}")
        lines.append(f"- **资金流水净额：** {net_cash_flow:+,.0f} JPY")
        lines.append(f"- **有效初始资金：** ¥{effective_initial_capital:,.0f}")
        lines.append(f"- **当前组合总资产：** ¥{total_value:,.0f}")
        lines.append(f"- **已实现盈亏：** {realized_pnl:+,.0f} JPY")
        lines.append(f"- **未实现盈亏：** {unrealized_pnl:+,.0f} JPY")
        lines.append(f"- **总盈亏（已实现 + 未实现）：** {total_pnl:+,.0f} JPY")
        lines.append(f"- **总收益率（相对有效初始资金）：** {total_return_pct:+.2f}%")

        lines.append("")
        lines.append("### 4) 今日盈亏")
        lines.append("")
        daily_pnl = self._calculate_daily_pnl(report_date, current_prices)
        if daily_pnl["ticker_rows"]:
            lines.append(
                "| 股票代码 | 分组 | 昨收 | 今收 | 开盘前持仓 | 当日买入 | 当日卖出 | 持仓贡献 (¥) | 当日成交贡献 (¥) | 今日盈亏 (¥) |"
            )
            lines.append(
                "|----------|------|------|------|------------|----------|----------|---------------|------------------|-------------|"
            )
            for row in daily_pnl["ticker_rows"]:
                lines.append(
                    f"| {row['ticker']} | {row['group_id']} | ¥{row['prev_close']:,.0f} | ¥{row['close_today']:,.0f} | "
                    f"{row['opening_qty']} | {row['buy_qty']} | {row['sell_qty']} | {row['holding_pnl']:+,.0f} | "
                    f"{row['trade_pnl']:+,.0f} | {row['daily_pnl']:+,.0f} |"
                )
            lines.append("")
            lines.append("**今日盈亏汇总：**")
            lines.append(
                f"- 持仓贡献合计：{daily_pnl['total_holding_pnl']:+,.0f} JPY"
            )
            lines.append(
                f"- 当日成交贡献合计：{daily_pnl['total_trade_pnl']:+,.0f} JPY"
            )
            lines.append(
                f"- 今日盈亏合计：{daily_pnl['total_daily_pnl']:+,.0f} JPY"
            )
        else:
            lines.append("*缺少足够的价格或交易数据，无法计算今日盈亏。*")

        return "\n".join(lines)

    def _get_close_pair(self, ticker: str, report_date: str) -> Optional[Dict[str, float]]:
        df = self.data_manager.load_stock_features(ticker)
        if df is None or df.empty:
            return None

        import pandas as pd

        if "Date" in df.columns:
            date_series = pd.to_datetime(df["Date"])
            close_series = df["Close"]
            frame = pd.DataFrame({"Date": date_series, "Close": close_series})
            frame = frame.dropna(subset=["Date", "Close"]).sort_values("Date")
        else:
            idx = pd.to_datetime(df.index)
            frame = pd.DataFrame({"Date": idx, "Close": df["Close"].values})
            frame = frame.dropna(subset=["Date", "Close"]).sort_values("Date")

        if frame.empty:
            return None

        target = pd.Timestamp(report_date)
        upto_target = frame[frame["Date"] <= target]
        if upto_target.empty:
            return None

        today_row = upto_target.iloc[-1]
        before_today = frame[frame["Date"] < today_row["Date"]]
        if before_today.empty:
            return None

        prev_row = before_today.iloc[-1]
        return {
            "close_today": float(today_row["Close"]),
            "prev_close": float(prev_row["Close"]),
        }

    def _calculate_daily_pnl(self, report_date: str, current_prices: Dict[str, float]) -> Dict:
        from collections import defaultdict

        end_qty_by_key = defaultdict(int)
        for group in self.state_manager.get_all_groups():
            for pos in group.positions:
                if pos.quantity > 0:
                    end_qty_by_key[(group.id, pos.ticker)] += int(pos.quantity)

        buy_qty_by_key = defaultdict(int)
        buy_notional_by_key = defaultdict(float)
        sell_qty_by_key = defaultdict(int)
        sell_notional_by_key = defaultdict(float)

        if self.trade_history_manager:
            for trade in self.trade_history_manager.trades:
                if trade.date != report_date:
                    continue
                key = (trade.group_id, trade.ticker)
                action = (trade.action or "").upper()
                qty = int(trade.quantity or 0)
                notional = float((trade.quantity or 0) * (trade.price or 0.0))
                if action == "BUY":
                    buy_qty_by_key[key] += qty
                    buy_notional_by_key[key] += notional
                elif action == "SELL":
                    sell_qty_by_key[key] += qty
                    sell_notional_by_key[key] += notional

        all_keys = set(end_qty_by_key.keys()) | set(buy_qty_by_key.keys()) | set(sell_qty_by_key.keys())
        ticker_rows = []
        total_holding_pnl = 0.0
        total_trade_pnl = 0.0

        for group_id, ticker in sorted(all_keys):
            close_pair = self._get_close_pair(ticker, report_date)
            if not close_pair:
                continue

            prev_close = close_pair["prev_close"]
            close_today = close_pair["close_today"]
            end_qty = int(end_qty_by_key.get((group_id, ticker), 0))
            buy_qty = int(buy_qty_by_key.get((group_id, ticker), 0))
            sell_qty = int(sell_qty_by_key.get((group_id, ticker), 0))
            opening_qty = end_qty - buy_qty + sell_qty

            holding_pnl = opening_qty * (close_today - prev_close)
            trade_pnl = (
                sell_notional_by_key.get((group_id, ticker), 0.0) - (sell_qty * prev_close)
            ) + (
                (buy_qty * close_today) - buy_notional_by_key.get((group_id, ticker), 0.0)
            )
            daily_pnl = holding_pnl + trade_pnl

            total_holding_pnl += holding_pnl
            total_trade_pnl += trade_pnl
            ticker_rows.append(
                {
                    "group_id": group_id,
                    "ticker": ticker,
                    "prev_close": prev_close,
                    "close_today": close_today,
                    "opening_qty": opening_qty,
                    "buy_qty": buy_qty,
                    "sell_qty": sell_qty,
                    "holding_pnl": holding_pnl,
                    "trade_pnl": trade_pnl,
                    "daily_pnl": daily_pnl,
                }
            )

        return {
            "ticker_rows": ticker_rows,
            "total_holding_pnl": total_holding_pnl,
            "total_trade_pnl": total_trade_pnl,
            "total_daily_pnl": total_holding_pnl + total_trade_pnl,
        }

    def _calculate_realized_performance(self, report_date: Optional[str] = None) -> Dict:
        if not self.trade_history_manager:
            return {"ticker_rows": [], "realized_pnl": 0.0, "realized_return_pct": 0.0}

        trades = list(self.trade_history_manager.trades)
        if report_date:
            trades = [
                t
                for t in trades
                if getattr(t, "date", None)
                and self._is_on_or_before(t.date, report_date)
            ]
        if not trades:
            return {"ticker_rows": [], "realized_pnl": 0.0, "realized_return_pct": 0.0}

        lots_by_key: Dict[tuple, deque] = defaultdict(deque)
        stats: Dict[tuple, Dict[str, float]] = defaultdict(
            lambda: {
                "buy_amount": 0.0,
                "sell_amount": 0.0,
                "realized_pnl": 0.0,
                "sell_trades": 0,
                "winning_sells": 0,
            }
        )

        for trade in trades:
            key = (trade.group_id, trade.ticker)
            action = (trade.action or "").upper()
            qty = int(trade.quantity or 0)
            price = float(trade.price or 0.0)
            if qty <= 0 or price <= 0:
                continue

            if action == "BUY":
                lots_by_key[key].append({"qty": qty, "price": price})
                stats[key]["buy_amount"] += qty * price
                continue

            if action != "SELL":
                continue

            stats[key]["sell_amount"] += qty * price
            stats[key]["sell_trades"] += 1

            remaining = qty
            matched_cost = 0.0
            while remaining > 0 and lots_by_key[key]:
                lot = lots_by_key[key][0]
                matched = min(remaining, int(lot["qty"]))
                matched_cost += matched * float(lot["price"])
                lot["qty"] -= matched
                remaining -= matched
                if lot["qty"] <= 0:
                    lots_by_key[key].popleft()

            matched_qty = qty - remaining
            matched_proceeds = matched_qty * price
            sell_realized = matched_proceeds - matched_cost
            stats[key]["realized_pnl"] += sell_realized
            if matched_qty > 0 and sell_realized > 0:
                stats[key]["winning_sells"] += 1

        ticker_rows = []
        total_realized = 0.0
        total_buy_amount = 0.0
        for (group_id, ticker), item in stats.items():
            buy_amount = float(item["buy_amount"])
            sell_amount = float(item["sell_amount"])
            realized_pnl = float(item["realized_pnl"])
            sell_trades = int(item["sell_trades"])
            winning_sells = int(item["winning_sells"])
            if buy_amount <= 0 or sell_amount <= 0:
                continue
            realized_return_pct = (realized_pnl / buy_amount * 100) if buy_amount > 0 else 0.0
            win_rate = (winning_sells / sell_trades * 100) if sell_trades > 0 else None
            ticker_rows.append(
                {
                    "group_id": group_id,
                    "ticker": ticker,
                    "buy_amount": buy_amount,
                    "sell_amount": sell_amount,
                    "realized_pnl": realized_pnl,
                    "realized_return_pct": realized_return_pct,
                    "sell_trades": sell_trades,
                    "win_rate": win_rate,
                }
            )
            total_realized += realized_pnl
            total_buy_amount += buy_amount

        ticker_rows.sort(key=lambda x: (x["group_id"], x["ticker"]))
        realized_return_pct = (
            (total_realized / total_buy_amount * 100) if total_buy_amount > 0 else 0.0
        )
        return {
            "ticker_rows": ticker_rows,
            "realized_pnl": total_realized,
            "realized_return_pct": realized_return_pct,
        }

    def _calculate_unrealized_performance(self, current_prices: Dict[str, float]) -> Dict:
        position_rows = []
        total_unrealized = 0.0
        total_cost_basis = 0.0

        for group in self.state_manager.get_all_groups():
            for pos in group.positions:
                if pos.quantity <= 0:
                    continue
                current_price = current_prices.get(pos.ticker, pos.entry_price)
                cost_basis = float(pos.quantity * pos.entry_price)
                market_value = float(pos.quantity * current_price)
                unrealized_pnl = market_value - cost_basis
                unrealized_return_pct = (
                    (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
                )

                position_rows.append(
                    {
                        "group_id": group.id,
                        "ticker": pos.ticker,
                        "quantity": int(pos.quantity),
                        "cost_basis": cost_basis,
                        "market_value": market_value,
                        "unrealized_pnl": unrealized_pnl,
                        "unrealized_return_pct": unrealized_return_pct,
                    }
                )

                total_unrealized += unrealized_pnl
                total_cost_basis += cost_basis

        position_rows.sort(key=lambda x: (x["group_id"], x["ticker"]))
        unrealized_return_pct = (
            (total_unrealized / total_cost_basis * 100) if total_cost_basis > 0 else 0.0
        )
        return {
            "position_rows": position_rows,
            "unrealized_pnl": total_unrealized,
            "unrealized_return_pct": unrealized_return_pct,
        }

    def _get_latest_close(self, ticker: str, report_date: Optional[str] = None) -> Optional[float]:
        df = self.data_manager.load_stock_features(ticker)
        if df is None or df.empty:
            return None

        import pandas as pd

        if "Date" in df.columns:
            frame = df.copy()
            frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
            frame = frame.dropna(subset=["Date"]).sort_values("Date")
        else:
            frame = df.copy()
            frame = frame.reset_index()
            idx_col = frame.columns[0]
            frame = frame.rename(columns={idx_col: "Date"})
            frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
            frame = frame.dropna(subset=["Date"]).sort_values("Date")

        if frame.empty:
            return None

        if report_date:
            cutoff = pd.Timestamp(report_date)
            frame = frame[frame["Date"] <= cutoff]
            if frame.empty:
                return None

        last_row = frame.iloc[-1]
        close_val = last_row.get("Close")
        if close_val is None:
            return None
        return float(close_val)

    @staticmethod
    def _is_on_or_before(date_text: str, cutoff_text: str) -> bool:
        try:
            return datetime.strptime(date_text, "%Y-%m-%d").date() <= datetime.strptime(
                cutoff_text, "%Y-%m-%d"
            ).date()
        except Exception:
            return False

    def _build_execution_summary_section(
        self, execution_results: List[ExecutionResult]
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
            "",
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
            lines.append(
                "| Ticker | Type | Qty | Price | Capital/Proceeds | Strategy |"
            )
            lines.append(
                "|--------|------|-----|-------|------------------|----------|"
            )

            for result in successful:
                signal = result.signal
                qty_str = (
                    str(signal.suggested_qty)
                    if signal.signal_type == "BUY"
                    else str(signal.position_qty)
                )
                qty_str = qty_str if qty_str and qty_str != "None" else "N/A"

                if signal.signal_type == "BUY":
                    amount = signal.required_capital
                    amount_str = f"¥{amount:,.0f}" if amount else "N/A"
                else:  # SELL
                    # Extract proceeds from message if available
                    amount_str = "N/A"
                    if result.reason and "Proceeds:" in result.reason:
                        try:
                            amount_str = (
                                result.reason.split("Proceeds:")[1]
                                .split(",")[0]
                                .strip()
                            )
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
                lines.append(
                    f"- **{signal.ticker}** ({signal.signal_type}): {result.reason}"
                )

            lines.append("")

        return "\n".join(lines)

    def _build_footer(self) -> str:
        """Build report footer."""
        return """---

**Report generated by J-Stock-Analyzer Production System**  
*For internal use only. Not financial advice.*"""

    def save_report(self, report_content: str, filepath: str) -> str:
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
        with open(filepath, "w", encoding="utf-8") as f:
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
    with open(signals_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    signals = []
    for item in data.get("signals", []):
        signal = Signal(
            group_id=item["group_id"],
            ticker=item["ticker"],
            ticker_name=item.get("ticker_name", ""),
            signal_type=item["signal_type"],
            action=item["action"],
            confidence=item["confidence"],
            score=item["score"],
            reason=item["reason"],
            current_price=item["current_price"],
            close_price=item.get("close_price"),
            planned_price=item.get("planned_price"),
            planning_price_factor=item.get("planning_price_factor"),
            sell_price_factor=item.get("sell_price_factor"),
            position_qty=item.get("position_qty"),
            entry_price=item.get("entry_price"),
            entry_date=item.get("entry_date"),
            holding_days=item.get("holding_days"),
            unrealized_pl_pct=item.get("unrealized_pl_pct"),
            suggested_qty=item.get("suggested_qty"),
            required_capital=item.get("required_capital"),
            strategy_name=item.get("strategy_name", ""),
            timestamp=item.get("timestamp", datetime.now().isoformat()),
        )
        signals.append(signal)

    return signals
