import os
import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

from src.capacity import compute_order_capacity, resolve_capacity_tier
from src.cli.production_utils import load_monitor_tickers
from src.config.runtime import (
    CONFIG_ENV_VAR,
    GDRIVE_DEFAULT_CONFIG_FILE,
    get_config_file_path,
    is_local_path,
)
from src.config.service import load_config
from src.data.fetch_universe_builder import build_fetch_universe_file
from src.data.sector_metrics_updater import update_sector_metrics
from src.utils.signal_sizing import extract_buy_size_multiplier


@dataclass(frozen=True)
class SignalDateDecision:
    signal_date: Optional[date]
    ready_ticker_count: int
    total_ticker_count: int
    coverage_ratio: float
    latest_observed_date: Optional[date]
    abnormal_tickers: tuple[str, ...]


@dataclass(frozen=True)
class SignalSemanticMetadata:
    momentum_rank: Optional[int]
    momentum_value: Optional[float]
    is_executable: bool
    is_executable_buy: bool
    is_executable_sell: bool


@dataclass(frozen=True)
class SellExecutionGuidance:
    exit_trigger: Optional[str]
    execution_intent: str
    execution_method: str
    execution_summary: str
    execution_period: str
    broker_order_type: str
    oco1_price: Optional[float]
    oco1_condition: Optional[str]
    oco2_trigger_price: Optional[float]
    oco2_limit_price: Optional[float]
    oco2_order_mode: Optional[str]
    formula_basis: str
    guidance_notes: str


def _select_signal_date_from_latest_dates(
    latest_dates_by_ticker: Dict[str, Optional[date]],
    minimum_ratio: float = 0.9,
) -> SignalDateDecision:
    total_ticker_count = len(latest_dates_by_ticker)
    observed_dates = sorted(
        {
            latest_date
            for latest_date in latest_dates_by_ticker.values()
            if latest_date is not None
        },
        reverse=True,
    )

    if total_ticker_count == 0 or not observed_dates:
        return SignalDateDecision(
            signal_date=None,
            ready_ticker_count=0,
            total_ticker_count=total_ticker_count,
            coverage_ratio=0.0,
            latest_observed_date=None,
            abnormal_tickers=tuple(sorted(latest_dates_by_ticker.keys())),
        )

    latest_observed_date = observed_dates[0]
    for candidate_date in observed_dates:
        ready_tickers = sorted(
            ticker
            for ticker, latest_date in latest_dates_by_ticker.items()
            if latest_date is not None and latest_date >= candidate_date
        )
        coverage_ratio = len(ready_tickers) / total_ticker_count
        if coverage_ratio > minimum_ratio:
            abnormal_tickers = tuple(
                sorted(
                    ticker
                    for ticker in latest_dates_by_ticker.keys()
                    if ticker not in ready_tickers
                )
            )
            return SignalDateDecision(
                signal_date=candidate_date,
                ready_ticker_count=len(ready_tickers),
                total_ticker_count=total_ticker_count,
                coverage_ratio=coverage_ratio,
                latest_observed_date=latest_observed_date,
                abnormal_tickers=abnormal_tickers,
            )

    ready_tickers = sorted(
        ticker
        for ticker, latest_date in latest_dates_by_ticker.items()
        if latest_date is not None
    )
    return SignalDateDecision(
        signal_date=None,
        ready_ticker_count=len(ready_tickers),
        total_ticker_count=total_ticker_count,
        coverage_ratio=(len(ready_tickers) / total_ticker_count),
        latest_observed_date=latest_observed_date,
        abnormal_tickers=tuple(
            sorted(
                ticker
                for ticker in latest_dates_by_ticker.keys()
                if ticker not in ready_tickers
            )
        ),
    )


def _derive_signal_semantic_metadata(signal) -> SignalSemanticMetadata:
    is_executable_buy = bool(
        signal.signal_type == "BUY" and (signal.suggested_qty or 0) > 0
    )
    is_executable_sell = bool(
        signal.signal_type == "SELL" and (signal.planned_sell_qty or 0) > 0
    )
    return SignalSemanticMetadata(
        momentum_rank=signal.rank if signal.signal_type == "BUY" else None,
        momentum_value=(
            float(signal.rank_score) if signal.signal_type == "BUY" and signal.rank_score is not None else None
        ),
        is_executable=bool(is_executable_buy or is_executable_sell),
        is_executable_buy=is_executable_buy,
        is_executable_sell=is_executable_sell,
    )


def _apply_signal_semantic_metadata(signals: List) -> List:
    return [
        replace(
            signal,
            momentum_rank=semantics.momentum_rank,
            momentum_value=semantics.momentum_value,
            is_executable=semantics.is_executable,
            is_executable_buy=semantics.is_executable_buy,
            is_executable_sell=semantics.is_executable_sell,
        )
        for signal in signals
        for semantics in [_derive_signal_semantic_metadata(signal)]
    ]


def _coerce_positive_float(value: Optional[float]) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    numeric_value = float(value)
    return numeric_value if numeric_value > 0 else None


def _round_order_price(value: float) -> float:
    return round(max(float(value), 1.0), 2)


def _build_sell_execution_guidance(
    action: str,
    trigger: Optional[str],
    reason: Optional[str],
    close_price: float,
    atr_value: Optional[float],
    sell_price_factor: float,
) -> SellExecutionGuidance:
    normalized_trigger = (trigger or "").strip() or None
    intent_source = " ".join(
        part.upper() for part in [trigger or "", reason or ""] if part
    )

    take_profit_keywords = (
        "TP1",
        "TP2",
        "BIASOVERHEAT",
        "RSIOVERHEATPULLBACK",
        "MOMENTUMEXHAUSTION",
    )
    time_keywords = ("TIMESTOP", "TIMEREVIEW", "TIME-COST", "TIME COST")
    immediate_risk_keywords = ("HARDSTOP", "GAPPANIC", "EMERGENCY")

    if any(keyword in intent_source for keyword in take_profit_keywords):
        execution_intent = "止盈兑现"
    elif any(keyword in intent_source for keyword in time_keywords):
        execution_intent = "时间/管理退出"
    else:
        execution_intent = "风险退出"

    safe_close_price = max(float(close_price or 0.0), 1.0)
    sell_pct = 0.5 if "50" in (action or "") else 1.0
    atr = _coerce_positive_float(atr_value)
    used_atr_fallback = False
    if atr is None:
        atr = max(safe_close_price * 0.03, 1.0)
        used_atr_fallback = True

    planned_limit_price = _round_order_price(
        max(safe_close_price * 0.985, safe_close_price * sell_price_factor)
    )

    if execution_intent == "止盈兑现":
        if sell_pct <= 0.55:
            oco1_price = _round_order_price(
                max(safe_close_price * 0.990, safe_close_price - 0.5 * atr)
            )
            oco2_trigger_price = _round_order_price(safe_close_price - 1.6 * atr)
            oco2_limit_price = _round_order_price(safe_close_price - 1.8 * atr)
            formula_basis = (
                f"TP1: OCO1=max(0.990C, C-0.5A), "
                f"OCO2 trigger=C-1.6A, limit=C-1.8A; "
                f"C={safe_close_price:.2f}, A={atr:.2f}"
            )
            guidance_notes = "先兑现一半；若价格走弱，则由逆指値指値保护剩余仓位。"
        else:
            oco1_price = _round_order_price(
                max(safe_close_price * 0.985, safe_close_price - 0.7 * atr)
            )
            oco2_trigger_price = _round_order_price(safe_close_price - 1.05 * atr)
            oco2_limit_price = _round_order_price(safe_close_price - 1.2 * atr)
            formula_basis = (
                f"TP2/Overheat: OCO1=max(0.985C, C-0.7A), "
                f"OCO2 trigger=C-1.05A, limit=C-1.2A; "
                f"C={safe_close_price:.2f}, A={atr:.2f}"
            )
            guidance_notes = "优先在强势或反弹里完成止盈；若回落失守，则用逆指値指値退出。"

        if used_atr_fallback:
            guidance_notes = f"{guidance_notes} ATR缺失，临时用收盘价的3%代替。"

        return SellExecutionGuidance(
            exit_trigger=normalized_trigger,
            execution_intent=execution_intent,
            execution_method="OCO（利確優先）",
            execution_summary=(
                f"OCO1 指値 ¥{oco1_price:,.2f} + 不成 / "
                f"OCO2 ¥{oco2_trigger_price:,.2f} 触发后指値 ¥{oco2_limit_price:,.2f}"
            ),
            execution_period="当日中",
            broker_order_type="OCO",
            oco1_price=oco1_price,
            oco1_condition="不成",
            oco2_trigger_price=oco2_trigger_price,
            oco2_limit_price=oco2_limit_price,
            oco2_order_mode="逆指値指値",
            formula_basis=formula_basis,
            guidance_notes=guidance_notes,
        )

    if execution_intent == "时间/管理退出":
        return SellExecutionGuidance(
            exit_trigger=normalized_trigger,
            execution_intent=execution_intent,
            execution_method="当日処理",
            execution_summary=f"指値 ¥{planned_limit_price:,.2f} + 不成で当日中に処理",
            execution_period="当日中",
            broker_order_type="通常注文",
            oco1_price=planned_limit_price,
            oco1_condition="不成",
            oco2_trigger_price=None,
            oco2_limit_price=None,
            oco2_order_mode=None,
            formula_basis=(
                f"TimeExit: limit=max(0.985C, C*{sell_price_factor:.2f}); "
                f"C={safe_close_price:.2f}"
            ),
            guidance_notes="重点不是搏反弹，而是今天把仓位处理完。",
        )

    is_immediate_risk = any(
        keyword in intent_source for keyword in immediate_risk_keywords
    )
    return SellExecutionGuidance(
        exit_trigger=normalized_trigger,
        execution_intent=execution_intent,
        execution_method="Immediate Exit" if is_immediate_risk else "Risk Exit",
        execution_summary=(
            "成行 / 引成で当日退出を优先"
            if is_immediate_risk
            else "引成または成行で当日退出を优先"
        ),
        execution_period="当日中",
        broker_order_type="通常注文",
        oco1_price=None,
        oco1_condition=None,
        oco2_trigger_price=None,
        oco2_limit_price=None,
        oco2_order_mode=None,
        formula_basis="Risk exit: prioritize same-day liquidation over rebound-first OCO.",
        guidance_notes=(
            "反弹待ちをしない。寄付前なら寄成、場中なら成行を优先。"
            if is_immediate_risk
            else "下方保護优先。价格改善よりも持ち越し回避を优先。"
        ),
    )


def run_daily_workflow(args, prod_cfg, state) -> None:
    from src.analysis.signals import Position, SignalAction
    from src.data.market_data_builder import MarketDataBuilder
    from src.data.stock_data_manager import StockDataManager
    from src.overlays import OverlayContext, OverlayManager
    from src.production import ReportBuilder
    from src.production.report_builder import AbnormalSignalTicker
    from src.production.state_manager import build_state_as_of
    from src.production.comprehensive_evaluator import ComprehensiveEvaluator
    from src.production.signal_generator import Signal
    from src.utils.strategy_loader import load_exit_strategy, load_strategy_pair

    load_dotenv()
    api_key = os.getenv("JQUANTS_API_KEY")
    raw_config = getattr(prod_cfg, "raw_config", None)
    if raw_config is None:
        raw_config = load_config()
    lot_sizes = raw_config.get("lot_sizes", {})
    default_lot_size = int(lot_sizes.get("default", 100) or 100)
    prod_runtime_cfg = raw_config.get("production", {})
    runtime_data_root = str(getattr(prod_cfg, "data_dir", raw_config.get("data", {}).get("data_dir", "data")) or "data")
    buy_price_buffer_pct = float(
        prod_runtime_cfg.get("report_buy_price_buffer_pct", 0.02)
    )
    sell_price_buffer_pct = float(
        prod_runtime_cfg.get("report_sell_price_buffer_pct", 0.02)
    )
    buy_price_buffer_pct = min(max(buy_price_buffer_pct, 0.0), 0.20)
    sell_price_buffer_pct = min(max(sell_price_buffer_pct, 0.0), 0.20)

    monitor_tickers = load_monitor_tickers(prod_cfg.monitor_list_file)

    def _collect_latest_feature_dates(
        tickers: List[str],
    ) -> Dict[str, Optional[date]]:
        latest_dates: Dict[str, Optional[date]] = {}
        for ticker in tickers:
            try:
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=data_manager,
                    ticker=ticker,
                    current_date=pd.Timestamp.now(),
                )
                if market_data is not None and not market_data.df_features.empty:
                    latest_feature_date = market_data.df_features.index.max()
                    if pd.notna(latest_feature_date):
                        latest_dates[ticker] = latest_feature_date.date()
                        continue
            except Exception:
                pass
            latest_dates[ticker] = None
        return latest_dates

    if not args.skip_fetch:
        print("\n[Data Update] Fetching latest market data...")
        from src.data_fetch_manager import run_fetch

        # Production daily path is optimized for price/features only.
        # Auxiliary datasets (financials/trades/earnings) are fetched via explicit fetch-all runs.
        daily_fetch_aux_data = False

        fetch_universe_file, merged_count, sector_count = build_fetch_universe_file(
            monitor_list_file=prod_cfg.monitor_list_file,
            output_file=prod_cfg.fetch_universe_file,
            sector_pool_file=prod_cfg.sector_pool_file,
        )
        print(
            "  Fetch universe prepared: "
            f"{merged_count} tickers (sector pool contribution: {sector_count})"
        )

        summary = run_fetch(
            monitor_list_file=fetch_universe_file,
            fetch_aux_data=daily_fetch_aux_data,
        )
        if summary:
            print(f"  Updated {summary['successful']}/{summary['total']} stocks")

        lookback_days = int(prod_runtime_cfg.get("sector_metrics_lookback_days", 90))
        min_names = int(prod_runtime_cfg.get("sector_metrics_min_names", 5))
        metrics_summary = update_sector_metrics(
            sector_pool_file=prod_cfg.sector_pool_file,
            data_root=runtime_data_root,
            lookback_days=lookback_days,
            min_names_per_sector=min_names,
        )
        if metrics_summary.get("status") == "ok":
            print("  Sector metrics updated")
            print(
                "    "
                f"Pool={metrics_summary.get('pool_size')} "
                f"Sectors={metrics_summary.get('sector_count')} "
                f"Rows={metrics_summary.get('rows_written')}"
            )
        else:
            print("  [WARN] Sector metrics update skipped (non-blocking)")
            print(f"    Reason: {metrics_summary.get('message', 'unknown')}")
    else:
        print("\n[Data Update] Skipped (--skip-fetch flag)")

    print("\n[Signal] Generating end-of-day signals...")
    for pattern in [prod_cfg.signal_file_pattern, prod_cfg.report_file_pattern]:
        if not is_local_path(pattern):
            continue
        sample_path = pattern.replace("{date}", "1970-01-01")
        Path(sample_path).parent.mkdir(parents=True, exist_ok=True)

    data_manager = StockDataManager(api_key=api_key, data_root=runtime_data_root)

    # Load ticker name lookup from jpx_final_list.csv (Code -> 銘柄名)
    import csv as _csv
    _ticker_name_map: Dict[str, str] = {}
    try:
        _jpx_csv = Path(runtime_data_root) / "jpx_final_list.csv"
        if _jpx_csv.exists():
            with open(_jpx_csv, encoding="utf-8-sig") as _f:
                for _row in _csv.DictReader(_f):
                    _ticker_name_map[_row["Code"]] = _row["銘柄名"]
    except Exception:
        pass
    overlay_runtime_config = dict(raw_config)
    overlay_cfg = dict(overlay_runtime_config.get("overlays", {}))
    # PROJECT POLICY: overlay defaults to OFF (see instruction.md "全局策略：Overlay 默认 OFF").
    # config.overlays.enabled is a normalized bool; missing/non-bool => False.
    overlay_enabled_in_config = bool(overlay_cfg.get("enabled", False))
    overlay_override = getattr(args, "production_overlay", None)
    overlay_enabled_effective = (
        bool(overlay_override)
        if overlay_override is not None
        else overlay_enabled_in_config
    )
    overlay_cfg["enabled"] = overlay_enabled_effective
    overlay_runtime_config["overlays"] = overlay_cfg
    overlay_manager = OverlayManager.from_config(
        overlay_runtime_config,
        data_root=runtime_data_root,
    )
    overlay_source = "cli" if overlay_override is not None else "config"
    print(
        "  Overlay signal integration: "
        f"{'enabled' if overlay_enabled_effective else 'disabled'}"
        f" (source: {overlay_source})"
    )
    print(f"  Monitoring {len(monitor_tickers)} stocks for signal evaluation")

    # 自动检测全市场最新可用数据日
    latest_dates_by_ticker = _collect_latest_feature_dates(monitor_tickers)
    signal_date_decision = _select_signal_date_from_latest_dates(
        latest_dates_by_ticker,
        minimum_ratio=0.9,
    )
    if signal_date_decision.signal_date is None:
        latest_txt = (
            signal_date_decision.latest_observed_date.strftime("%Y-%m-%d")
            if signal_date_decision.latest_observed_date is not None
            else "N/A"
        )
        print("\n[WARN] Majority market data threshold not met for signal generation.")
        print(f"  Latest observed date: {latest_txt}")
        print(
            "  Ready tickers: "
            f"{signal_date_decision.ready_ticker_count}/"
            f"{signal_date_decision.total_ticker_count} "
            f"({signal_date_decision.coverage_ratio:.1%})"
        )
        print("  Workflow aborted.")
        return

    # 如果今天还没开盘，API只能拿到前一日数据，信号生成日应为latest_data_date
    today_str = datetime.now().strftime("%Y-%m-%d")
    signal_date = signal_date_decision.signal_date.strftime("%Y-%m-%d")
    if signal_date != today_str:
        print(
            f"\n[INFO] Using majority-available data date for signal generation: {signal_date}"
        )
    else:
        print(f"\n[INFO] Using today as signal date: {signal_date}")
    print(
        "  Signal date coverage: "
        f"{signal_date_decision.ready_ticker_count}/"
        f"{signal_date_decision.total_ticker_count} "
        f"({signal_date_decision.coverage_ratio:.1%})"
    )

    abnormal_ticker_set = set(signal_date_decision.abnormal_tickers)
    signal_tickers = [
        ticker for ticker in monitor_tickers if ticker not in abnormal_ticker_set
    ]
    if abnormal_ticker_set:
        print(
            "  Excluding abnormal tickers from signal generation: "
            + ", ".join(sorted(abnormal_ticker_set))
        )

    effective_state = build_state_as_of(
        base_state=state,
        history_file=prod_cfg.history_file,
        cash_history_file=prod_cfg.cash_history_file,
        as_of_date=signal_date,
    )
    capacity_mode = str(getattr(prod_cfg, "capacity_regime_mode", "off") or "off")
    capacity_regime = getattr(prod_cfg, "capacity_regime", None)
    state_as_of_cache: Dict[str, object] = {signal_date: effective_state}
    price_cache: Dict[tuple[str, str], float | None] = {}

    def _resolve_config_source() -> str:
        if os.getenv(CONFIG_ENV_VAR):
            return "env"
        if get_config_file_path() == GDRIVE_DEFAULT_CONFIG_FILE:
            return "gdrive"
        return "local"

    def _get_recent_trading_dates(end_date: str, window_size: int) -> List[str]:
        target_ts = pd.Timestamp(end_date)
        for ticker in signal_tickers:
            try:
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=data_manager,
                    ticker=ticker,
                    current_date=target_ts,
                )
            except Exception:
                continue
            if market_data is None or market_data.df_features.empty:
                continue
            date_index = market_data.df_features.index
            eligible = date_index[date_index <= target_ts]
            if len(eligible) == 0:
                continue
            return [ts.strftime("%Y-%m-%d") for ts in eligible[-window_size:]]
        return [end_date]

    def _get_state_as_of_date(as_of_date: str):
        if as_of_date not in state_as_of_cache:
            state_as_of_cache[as_of_date] = build_state_as_of(
                base_state=state,
                history_file=prod_cfg.history_file,
                cash_history_file=prod_cfg.cash_history_file,
                as_of_date=as_of_date,
            )
        return state_as_of_cache[as_of_date]

    def _get_close_price_for_date(ticker: str, as_of_date: str) -> float | None:
        cache_key = (ticker, as_of_date)
        if cache_key in price_cache:
            return price_cache[cache_key]
        try:
            market_data = MarketDataBuilder.build_from_manager(
                data_manager=data_manager,
                ticker=ticker,
                current_date=pd.Timestamp(as_of_date),
            )
        except Exception:
            price_cache[cache_key] = None
            return None
        if market_data is None or market_data.df_features.empty:
            price_cache[cache_key] = None
            return None
        latest_row = market_data.df_features.iloc[-1]
        close_value = latest_row.get("Close")
        if close_value is None or pd.isna(close_value):
            price_cache[cache_key] = None
            return None
        price_cache[cache_key] = float(close_value)
        return price_cache[cache_key]

    def _get_group_prices_as_of(group_state, as_of_date: str) -> Dict[str, float]:
        prices: Dict[str, float] = {}
        for position in group_state.positions:
            if position.quantity <= 0:
                continue
            close_price = _get_close_price_for_date(position.ticker, as_of_date)
            if close_price is not None:
                prices[position.ticker] = close_price
        return prices

    def _build_group_equity_history(group_id: str, as_of_date: str) -> List[float]:
        if capacity_regime is None:
            return []
        trading_dates = _get_recent_trading_dates(
            as_of_date,
            max(1, int(capacity_regime.equity_window_days)),
        )
        equity_values: List[float] = []
        for history_date in trading_dates:
            snapshot_state = _get_state_as_of_date(history_date)
            snapshot_group = snapshot_state.get_group(group_id)
            if snapshot_group is None:
                continue
            history_prices = _get_group_prices_as_of(snapshot_group, history_date)
            equity_values.append(float(snapshot_group.total_value(history_prices)))
        return equity_values

    def _extract_turnover_value(ticker: str, as_of_date: str) -> float | None:
        if capacity_regime is None:
            return None
        try:
            market_data = MarketDataBuilder.build_from_manager(
                data_manager=data_manager,
                ticker=ticker,
                current_date=pd.Timestamp(as_of_date),
            )
        except Exception:
            return None
        if market_data is None or market_data.df_features.empty:
            return None
        latest_row = market_data.df_features.iloc[-1]
        value = latest_row.get(capacity_regime.turnover_field)
        if value is None or pd.isna(value):
            return None
        return float(value)

    def _apply_capacity_fields(signal, snapshot, decision) -> None:
        signal.capacity_regime_mode = capacity_mode
        signal.capacity_regime_version = snapshot.regime_version
        signal.capacity_tier_name = snapshot.tier_name
        signal.capacity_effective_equity_jpy = snapshot.effective_equity_jpy
        signal.capacity_effective_max_positions = snapshot.max_positions
        signal.capacity_effective_max_position_pct = snapshot.max_position_pct
        signal.capacity_participation_cap_pct = snapshot.participation_cap_pct
        signal.capacity_min_turnover_20_jpy = snapshot.min_turnover_20_jpy
        if decision is not None:
            signal.capacity_order_cap_jpy = decision.order_cap_jpy
            signal.capacity_turnover_jpy = decision.turnover_jpy
            signal.capacity_participation_pct = decision.participation_pct
            signal.capacity_blocking_reason = decision.blocking_reason

    all_signals = []
    groups = effective_state.get_all_groups()
    group_configs = {g["id"]: g for g in (prod_cfg.strategy_groups or [])}
    group_entry_eval_keys: Dict[str, str] = {}
    pair_configs: Dict[tuple[str, str], Dict[str, str]] = {}
    for group in groups:
        cfg = group_configs.get(group.id, {})
        entry_strategy_name = cfg.get(
            "entry_strategy", prod_cfg.default_entry_strategy
        )
        exit_strategy_name = cfg.get(
            "exit_strategy", prod_cfg.default_exit_strategy
        )
        eval_key = f"{entry_strategy_name}__PAIR__{exit_strategy_name}"
        group_entry_eval_keys[group.id] = eval_key
        pair_configs.setdefault(
            (entry_strategy_name, exit_strategy_name),
            {
                "name": entry_strategy_name,
                "key": eval_key,
                "exit_name": exit_strategy_name,
            },
        )

    strategies_config = list(pair_configs.values())
    evaluator = ComprehensiveEvaluator(data_manager, strategies_config)

    abnormal_signal_tickers: List[AbnormalSignalTicker] = []
    if abnormal_ticker_set:
        held_groups_by_ticker: Dict[str, List[str]] = {}
        for group in groups:
            for position in group.positions:
                if position.quantity <= 0 or position.ticker not in abnormal_ticker_set:
                    continue
                held_groups_by_ticker.setdefault(position.ticker, []).append(group.name)

        for ticker in signal_date_decision.abnormal_tickers:
            latest_date = latest_dates_by_ticker.get(ticker)
            abnormal_signal_tickers.append(
                AbnormalSignalTicker(
                    ticker=ticker,
                    ticker_name=_ticker_name_map.get(ticker, ticker),
                    latest_data_date=(
                        latest_date.strftime("%Y-%m-%d")
                        if latest_date is not None
                        else "N/A"
                    ),
                    expected_date=signal_date,
                    lag_days=(
                        (signal_date_decision.signal_date - latest_date).days
                        if latest_date is not None
                        else None
                    ),
                    exclusion_reason="Missing feature data for selected signal date",
                    held_by_groups=tuple(sorted(held_groups_by_ticker.get(ticker, []))),
                )
            )

    print(f"  Evaluating all {len(signal_tickers)} stocks...")
    comprehensive_evals = evaluator.evaluate_all_stocks(
        tickers=signal_tickers,
        current_date=signal_date,
        verbose=False,
    )
    print(f"  ✅ Evaluated {len(comprehensive_evals)} stocks")

    total_buy_signals = 0
    total_sell_signals = 0

    def _calc_suggested_qty(
        ticker: str,
        current_price: float,
        available_cash: float,
        total_portfolio_value: float,
        max_position_pct: float,
    ):
        lot_size = int(lot_sizes.get(ticker, default_lot_size) or default_lot_size)
        if current_price <= 0 or lot_size <= 0:
            return 0, 0.0, lot_size

        target_position_value = total_portfolio_value * max_position_pct
        max_position_value = min(target_position_value, available_cash)
        lot_value = current_price * lot_size
        lots = int(max_position_value // lot_value)
        qty = lots * lot_size
        required_capital = qty * current_price
        return qty, required_capital, lot_size

    def _estimate_buy_price(close_price: float) -> float:
        return float(close_price) * (1.0 + buy_price_buffer_pct)

    def _estimate_sell_price(close_price: float) -> float:
        return float(close_price) * (1.0 - sell_price_buffer_pct)

    def _parse_sell_pct(action: str) -> float:
        normalized = (action or "").upper()
        if "25" in normalized:
            return 0.25
        if "50" in normalized:
            return 0.5
        if "75" in normalized:
            return 0.75
        return 1.0

    def _calculate_sell_quantity(ticker: str, total_qty: int, sell_pct: float) -> int:
        lot_size = int(lot_sizes.get(ticker, default_lot_size) or default_lot_size)
        if total_qty <= 0:
            return 0
        if sell_pct >= 0.999:
            return total_qty
        raw_qty = total_qty * max(sell_pct, 0.0)
        lots = int((raw_qty + lot_size - 1) // lot_size)
        qty = lots * lot_size
        return min(total_qty, qty)

    def _build_buy_diagnostics_markdown(
        groups,
        group_cfg_map,
        group_entry_eval_keys,
        evals,
        runtime_cfg,
    ) -> str:
        lines = [
            "## 🧠 Buy Signal Diagnostics",
            "",
            (
                f"- 配置分数阈值 `production.buy_threshold`: {float(runtime_cfg.buy_threshold):.1f}"
                "（仅对带 score 的策略有效）"
            ),
            "- 说明：当前生产流程在 `production_daily` 中以 `signal_action == BUY` 为主门槛；"
            "若策略无 score（如纯技术信号策略），不会被 `buy_threshold` 二次过滤。",
            "",
        ]

        for group in groups:
            cfg = group_cfg_map.get(group.id, {})
            entry_strategy_name = cfg.get(
                "entry_strategy", runtime_cfg.default_entry_strategy
            )
            exit_strategy_name = cfg.get(
                "exit_strategy", runtime_cfg.default_exit_strategy
            )
            entry_eval_key = group_entry_eval_keys.get(group.id, entry_strategy_name)
            current_tickers = {
                pos.ticker for pos in group.positions if int(getattr(pos, "quantity", 0) or 0) > 0
            }

            strategy_inst = None
            strategy_threshold_desc = "N/A"
            try:
                strategy_inst, _ = load_strategy_pair(
                    entry_strategy_name,
                    exit_strategy_name,
                )
                if getattr(strategy_inst, "max_bias_pct", None) is not None:
                    source = getattr(strategy_inst, "bias_threshold_source", None)
                    source_suffix = f" ({source})" if source else ""
                    strategy_threshold_desc = (
                        f"max_bias_pct={float(getattr(strategy_inst, 'max_bias_pct')):.2f}%{source_suffix}"
                    )
                elif hasattr(strategy_inst, "min_confidence"):
                    strategy_threshold_desc = (
                        f"min_confidence={float(getattr(strategy_inst, 'min_confidence')):.2f}"
                    )
                elif hasattr(strategy_inst, "threshold"):
                    strategy_threshold_desc = (
                        f"threshold={float(getattr(strategy_inst, 'threshold')):.1f}"
                    )
            except Exception:
                strategy_threshold_desc = "(strategy load failed)"

            candidates = []
            for ticker, eval_obj in evals.items():
                if ticker in current_tickers:
                    continue
                strategy_eval = eval_obj.evaluations.get(entry_eval_key)
                if strategy_eval is None:
                    continue
                candidates.append(strategy_eval)

            buy_actions = [e for e in candidates if e.signal_action == "BUY"]
            scored_candidates = [e for e in candidates if float(getattr(e, "score", 0.0) or 0.0) > 0]
            scored_above_threshold = [
                e
                for e in scored_candidates
                if float(getattr(e, "score", 0.0) or 0.0) >= float(runtime_cfg.buy_threshold)
            ]

            reason_counts = {}
            for e in candidates:
                reason = (getattr(e, "reason", "") or "").strip()
                reason_key = reason.split(";")[0].strip() if reason else "(no reason)"
                reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1

            top_reasons = sorted(reason_counts.items(), key=lambda x: (-x[1], x[0]))[:3]
            near_miss = sorted(
                [e for e in candidates if e.signal_action != "BUY"],
                key=lambda x: float(getattr(x, "confidence", 0.0) or 0.0),
                reverse=True,
            )[:5]

            lines.append(f"### {group.name} ({group.id})")
            lines.append("")
            lines.append(f"- 入场策略: `{entry_strategy_name}`")
            lines.append(f"- 策略内部阈值: {strategy_threshold_desc}")
            lines.append(f"- 非持仓候选数: {len(candidates)}")
            lines.append(f"- 策略返回 BUY 数: {len(buy_actions)}")
            lines.append(
                f"- 候选中有 score 的数量: {len(scored_candidates)} | score >= {float(runtime_cfg.buy_threshold):.1f} 的数量: {len(scored_above_threshold)}"
            )

            if top_reasons:
                lines.append("- 未触发BUY的主要原因(top3):")
                for reason, count in top_reasons:
                    lines.append(f"  - {reason}: {count}")

            if near_miss:
                lines.append("- 接近触发但未买入的候选(按confidence):")
                for e in near_miss:
                    lines.append(
                        f"  - {e.ticker}: confidence={float(getattr(e, 'confidence', 0.0) or 0.0):.2f}, "
                        f"score={float(getattr(e, 'score', 0.0) or 0.0):.1f}, reason={getattr(e, 'reason', '') or '(no reason)'}"
                    )

            if len(buy_actions) == 0:
                lines.append(
                    "- 结论: 本组今日无BUY触发，核心原因是策略条件未满足（而非overlay阻断或仓位资金约束）。"
                )

            lines.append("")

        return "\n".join(lines)

    def _build_macd_hist_snapshot_markdown(
        tickers: List[str],
        target_date: str,
        lookback_days: int = 5,
    ) -> str:
        lookback_days = max(2, int(lookback_days))
        headers = [f"Hist[-{i}]" for i in range(lookback_days - 1, 0, -1)] + ["Hist[0]"]

        lines = [
            "## 📉 MACD Hist Recent Snapshot",
            "",
            (
                f"- 口径：展示每只股票最近 {lookback_days} 个交易日的 `MACD_Hist`（`Hist[0]` 为今日 {target_date}）"
            ),
            "- 金叉判定：`Hist[-1] < 0` 且 `Hist[0] > 0`",
            "",
            "| Ticker | Name | " + " | ".join(headers) + " | GoldCrossToday |",
            "|---|---|" + "---|" * (len(headers) + 1),
        ]

        for ticker in sorted(tickers):
            hist_vals = []
            try:
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=data_manager,
                    ticker=ticker,
                    current_date=pd.Timestamp(target_date),
                )
                if market_data is not None and not market_data.df_features.empty:
                    series = market_data.df_features["MACD_Hist"].dropna().tail(lookback_days)
                    hist_vals = [float(v) for v in series.tolist()]
            except Exception:
                hist_vals = []

            if len(hist_vals) < lookback_days:
                hist_vals = ([None] * (lookback_days - len(hist_vals))) + hist_vals

            formatted = [
                (f"{v:.4f}" if isinstance(v, float) else "N/A")
                for v in hist_vals
            ]

            prev_hist = hist_vals[-2] if len(hist_vals) >= 2 else None
            now_hist = hist_vals[-1] if len(hist_vals) >= 1 else None
            is_cross = (
                isinstance(prev_hist, float)
                and isinstance(now_hist, float)
                and prev_hist < 0
                and now_hist > 0
            )

            lines.append(
                f"| {ticker} | {_ticker_name_map.get(ticker, ticker)} | "
                + " | ".join(formatted)
                + f" | {'YES' if is_cross else 'NO'} |"
            )

        return "\n".join(lines)

    overlay_summaries = []

    def _get_group_current_prices(group):
        prices = {}
        for pos in group.positions:
            if pos.quantity <= 0:
                continue
            try:
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=data_manager,
                    ticker=pos.ticker,
                    current_date=pd.Timestamp(signal_date),
                )
            except Exception:
                continue
            if market_data is None or market_data.df_features.empty:
                continue
            latest_row = market_data.df_features.iloc[-1]
            prices[pos.ticker] = float(latest_row.get("Close", 0.0))
        return prices

    _group_buy_contexts: Dict[str, dict] = {}

    for group in groups:
        group_cfg = group_configs.get(group.id, {})
        entry_strategy_name = group_cfg.get(
            "entry_strategy", prod_cfg.default_entry_strategy
        )
        exit_strategy_name = group_cfg.get(
            "exit_strategy", prod_cfg.default_exit_strategy
        )

        print(f"    Group: {group.name} ({entry_strategy_name} + {exit_strategy_name})")

        try:
            exit_strategy = load_exit_strategy(exit_strategy_name)
        except Exception as e:
            print(f"      ⚠️ Exit strategy load error: {e}")
            continue

        current_tickers = {pos.ticker for pos in group.positions if pos.quantity > 0}
        current_prices = _get_group_current_prices(group)
        total_value = group.cash + sum(
            pos.quantity * current_prices.get(pos.ticker, pos.entry_price)
            for pos in group.positions
            if pos.quantity > 0
        )
        capacity_snapshot = None
        if capacity_mode != "off" and capacity_regime is not None:
            equity_history = _build_group_equity_history(group.id, signal_date)
            observed_total_value = (
                equity_history[-1] if equity_history else float(total_value)
            )
            prior_equity = equity_history[:-1] if len(equity_history) > 1 else []
            capacity_snapshot = resolve_capacity_tier(
                capacity_regime,
                prior_equity,
                float(observed_total_value),
            )

        overlay_decision = None
        if overlay_manager.overlays:
            overlay_context = OverlayContext(
                current_date=pd.Timestamp(signal_date),
                portfolio_cash=group.cash,
                portfolio_value=total_value,
                positions={pos.ticker: pos for pos in group.positions},
                current_prices=current_prices,
                group_id=group.id,
            )
            overlay_decision, per_overlay = overlay_manager.evaluate(overlay_context)
            overlay_summaries.append(
                {
                    "group_id": group.id,
                    "group_name": group.name,
                    **overlay_manager.summarize(overlay_decision, per_overlay),
                }
            )

        buy_count = 0
        new_positions_opened = 0
        max_new_positions = (
            overlay_decision.max_new_positions if overlay_decision else None
        )

        # Step 1) Build SELL/HOLD signals first (for projected cash release)
        sell_count = 0
        projected_sell_proceeds = 0.0
        projected_position_count = len(current_tickers)
        for position in group.positions:
            if position.quantity <= 0:
                continue

            ticker = position.ticker
            try:
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=data_manager,
                    ticker=ticker,
                    current_date=pd.Timestamp(signal_date),
                )
                if market_data is None:
                    continue

                latest_row = (
                    market_data.df_features.iloc[-1]
                    if not market_data.df_features.empty
                    else None
                )
                current_price = latest_row["Close"] if latest_row is not None else None
                if current_price is None:
                    continue

                entry_date_ts = pd.Timestamp(position.entry_date)
                unrealized_pl = (
                    (current_price - position.entry_price) / position.entry_price
                ) * 100
                md = market_data.metadata if market_data else {}

                overlay_reason = None
                if overlay_decision and overlay_decision.force_exit:
                    overlay_reason = "Overlay force exit"
                elif (
                    overlay_decision
                    and overlay_decision.exit_overrides
                    and ticker in overlay_decision.exit_overrides
                ):
                    overlay_reason = overlay_decision.exit_overrides[ticker]

                if overlay_reason:
                    estimated_sell_price = _estimate_sell_price(float(current_price))
                    planned_sell_qty = int(position.quantity)
                    planned_sell_value = planned_sell_qty * estimated_sell_price
                    signal = Signal(
                        group_id=group.id,
                        ticker=ticker,
                        ticker_name=md.get("company_name", ticker) if md else ticker,
                        signal_type="SELL",
                        action="SELL",
                        confidence=1.0,
                        score=0,
                        reason=overlay_reason,
                        current_price=float(current_price),
                        close_price=float(current_price),
                        planned_price=float(estimated_sell_price),
                        planning_price_factor=float(1.0 + buy_price_buffer_pct),
                        sell_price_factor=float(1.0 - sell_price_buffer_pct),
                        position_qty=position.quantity,
                        entry_price=position.entry_price,
                        entry_date=position.entry_date,
                        holding_days=(pd.Timestamp(signal_date) - entry_date_ts).days,
                        unrealized_pl_pct=float(unrealized_pl),
                        planned_sell_qty=planned_sell_qty,
                        planned_sell_value=planned_sell_value,
                        strategy_name="Overlay",
                    )
                    all_signals.append(signal)
                    projected_sell_proceeds += planned_sell_value
                    projected_position_count -= 1
                    sell_count += 1
                    total_sell_signals += 1
                    continue

                signals_position = Position(
                    ticker=ticker,
                    entry_price=position.entry_price,
                    signal_entry_price=position.signal_entry_price,
                    entry_date=entry_date_ts,
                    quantity=position.quantity,
                    entry_signal=None,
                    peak_price_since_entry=(
                        position.peak_price
                        or position.signal_entry_price
                        or position.entry_price
                    ),
                )

                if current_price > signals_position.peak_price_since_entry:
                    signals_position.peak_price_since_entry = current_price
                    position.peak_price = current_price

                exit_signal = exit_strategy.generate_exit_signal(
                    position=signals_position,
                    market_data=market_data,
                )

                # Get evaluation details for reporting (for both SELL and HOLD)
                evaluation_details = None
                if hasattr(exit_strategy, "get_evaluation_details"):
                    try:
                        evaluation_details = exit_strategy.get_evaluation_details(
                            signals_position, market_data
                        )
                    except Exception as e:
                        if args.verbose:
                            print(f"        Evaluation details error for {ticker}: {e}")

                # Process SELL signals
                if exit_signal.action == SignalAction.SELL:
                    action_str = (
                        exit_signal.action.value
                        if hasattr(exit_signal.action, "value")
                        else "SELL"
                    )
                    signal_type = "SELL"
                elif exit_signal.action == SignalAction.HOLD:
                    # Generate HOLD signal for reporting
                    action_str = "HOLD"
                    signal_type = "HOLD"
                else:
                    action_str = (
                        exit_signal.action.value
                        if hasattr(exit_signal.action, "value")
                        else str(exit_signal.action)
                    )
                    signal_type = "SELL"

                holding_days = (pd.Timestamp(signal_date) - entry_date_ts).days
                unrealized_pl = (
                    (current_price - position.entry_price) / position.entry_price
                ) * 100
                md = market_data.metadata if market_data else {}

                planned_sell_qty = None
                planned_sell_price = None
                planned_sell_value = None
                exit_trigger = None
                execution_guidance = None
                if signal_type == "SELL":
                    sell_pct = 1.0
                    if exit_signal.metadata:
                        trigger_value = exit_signal.metadata.get("trigger")
                        if trigger_value is not None:
                            exit_trigger = str(trigger_value)
                        sell_pct = float(
                            exit_signal.metadata.get("sell_percentage", 1.0)
                        )
                    if action_str and action_str != "SELL":
                        sell_pct = _parse_sell_pct(action_str)
                    planned_sell_qty = _calculate_sell_quantity(
                        ticker=ticker,
                        total_qty=position.quantity,
                        sell_pct=sell_pct,
                    )
                    estimated_sell_price = _estimate_sell_price(float(current_price))
                    latest_atr = None
                    if (
                        market_data is not None
                        and market_data.df_features is not None
                        and not market_data.df_features.empty
                    ):
                        latest_atr = _coerce_positive_float(
                            market_data.df_features.iloc[-1].get("ATR")
                        )
                    execution_guidance = _build_sell_execution_guidance(
                        action=action_str,
                        trigger=exit_trigger,
                        reason=(
                            "; ".join(exit_signal.reasons)
                            if exit_signal.reasons
                            else exit_signal.action.name
                        ),
                        close_price=float(current_price),
                        atr_value=latest_atr,
                        sell_price_factor=float(1.0 - sell_price_buffer_pct),
                    )
                    planned_sell_price = estimated_sell_price
                    if (
                        execution_guidance is not None
                        and execution_guidance.oco1_price is not None
                    ):
                        planned_sell_price = float(execution_guidance.oco1_price)
                    planned_sell_value = planned_sell_qty * planned_sell_price

                signal = Signal(
                    group_id=group.id,
                    ticker=ticker,
                    ticker_name=md.get("company_name", ticker) if md else ticker,
                    signal_type=signal_type,
                    action=action_str,
                    confidence=exit_signal.confidence,
                    score=0,
                    reason=(
                        "; ".join(exit_signal.reasons)
                        if exit_signal.reasons
                        else exit_signal.action.name
                    ),
                    current_price=float(current_price),
                    close_price=float(current_price),
                    planned_price=(
                        float(planned_sell_price)
                        if signal_type == "SELL"
                        and planned_sell_qty
                        and planned_sell_price is not None
                        else None
                    ),
                    planning_price_factor=float(1.0 + buy_price_buffer_pct),
                    sell_price_factor=float(1.0 - sell_price_buffer_pct),
                    position_qty=position.quantity,
                    entry_price=position.entry_price,
                    entry_date=position.entry_date,
                    holding_days=holding_days,
                    unrealized_pl_pct=float(unrealized_pl),
                    planned_sell_qty=planned_sell_qty,
                    planned_sell_value=planned_sell_value,
                    strategy_name=exit_strategy_name,
                    evaluation_details=evaluation_details,
                    exit_trigger=(
                        execution_guidance.exit_trigger if execution_guidance else None
                    ),
                    execution_intent=(
                        execution_guidance.execution_intent
                        if execution_guidance
                        else None
                    ),
                    execution_method=(
                        execution_guidance.execution_method
                        if execution_guidance
                        else None
                    ),
                    execution_summary=(
                        execution_guidance.execution_summary
                        if execution_guidance
                        else None
                    ),
                    execution_period=(
                        execution_guidance.execution_period
                        if execution_guidance
                        else None
                    ),
                    broker_order_type=(
                        execution_guidance.broker_order_type
                        if execution_guidance
                        else None
                    ),
                    oco1_price=(
                        execution_guidance.oco1_price if execution_guidance else None
                    ),
                    oco1_condition=(
                        execution_guidance.oco1_condition
                        if execution_guidance
                        else None
                    ),
                    oco2_trigger_price=(
                        execution_guidance.oco2_trigger_price
                        if execution_guidance
                        else None
                    ),
                    oco2_limit_price=(
                        execution_guidance.oco2_limit_price
                        if execution_guidance
                        else None
                    ),
                    oco2_order_mode=(
                        execution_guidance.oco2_order_mode
                        if execution_guidance
                        else None
                    ),
                    formula_basis=(
                        execution_guidance.formula_basis
                        if execution_guidance
                        else None
                    ),
                    guidance_notes=(
                        execution_guidance.guidance_notes
                        if execution_guidance
                        else None
                    ),
                )
                all_signals.append(signal)

                # Count only SELL signals for statistics
                if signal_type == "SELL":
                    projected_sell_proceeds += float(planned_sell_value or 0.0)
                    if (planned_sell_qty or 0) >= position.quantity:
                        projected_position_count -= 1
                    sell_count += 1
                    total_sell_signals += 1
            except Exception:
                continue

        # Step 2) Build ALL BUY signals (no position-limit break).
        #   Capital allocation is deferred to post-ranking step so that
        #   the ranking strategy (e.g. momentum) decides buy priority,
        #   consistent with the evaluation (portfolio_engine) flow.
        invested_value = sum(
            pos.quantity * current_prices.get(pos.ticker, pos.entry_price)
            for pos in group.positions
            if pos.quantity > 0
        )

        for ticker, eval_obj in comprehensive_evals.items():
            if ticker in current_tickers:
                continue
            entry_eval_key = group_entry_eval_keys.get(group.id, entry_strategy_name)
            strategy_eval = eval_obj.evaluations.get(entry_eval_key)
            if not strategy_eval or strategy_eval.signal_action != "BUY":
                continue

            estimated_buy_price = _estimate_buy_price(float(eval_obj.current_price))

            signal = Signal(
                group_id=group.id,
                ticker=ticker,
                ticker_name=eval_obj.ticker_name,
                signal_type="BUY",
                action="BUY",
                confidence=strategy_eval.confidence,
                score=strategy_eval.score,
                reason=strategy_eval.reason,
                current_price=estimated_buy_price,
                close_price=float(eval_obj.current_price),
                planned_price=float(estimated_buy_price),
                planning_price_factor=float(1.0 + buy_price_buffer_pct),
                sell_price_factor=float(1.0 - sell_price_buffer_pct),
                suggested_qty=0,
                required_capital=0.0,
                strategy_name=entry_strategy_name,
            )
            all_signals.append(signal)
            buy_count += 1
            total_buy_signals += 1

        # Store per-group context for post-ranking capital allocation
        _group_buy_contexts[group.id] = {
            "group": group,
            "overlay_decision": overlay_decision,
            "projected_sell_proceeds": projected_sell_proceeds,
            "projected_position_count": projected_position_count,
            "invested_value": invested_value,
            "total_value": total_value,
            "max_new_positions": max_new_positions,
            "capacity_snapshot": capacity_snapshot,
            "capacity_blocked_buys": 0,
            "capacity_liquidity_blocked_buys": 0,
            "capacity_trimmed_buys": 0,
        }

        print(f"      BUY: {buy_count}, SELL: {sell_count}")

    # ------- Optional: Rank BUY signals -------
    # Default to "momentum" so production matches the evaluation flow's
    # capacity-allocation behavior (PortfolioBacktestEngine applies a ranker
    # when capital/positions are constrained). Set to empty string in config
    # to opt out.
    ranking_strategy_name = raw_config.get("production", {}).get(
        "signal_ranking_strategy", "momentum"
    )
    if ranking_strategy_name:
        try:
            from src.utils.strategy_loader import load_ranking_strategy

            ranker = load_ranking_strategy(ranking_strategy_name)
            buy_signals = [s for s in all_signals if s.signal_type == "BUY"]
            if buy_signals:
                from src.analysis.signals import (
                    MarketData as _MD,
                    SignalAction as _SA,
                    TradingSignal as _TS,
                )

                # Convert production Signals → TradingSignal dict for ranker
                ts_dict = {}
                for s in buy_signals:
                    ts_dict[s.ticker] = _TS(
                        action=_SA.BUY,
                        confidence=s.confidence,
                        reasons=[s.reason],
                        metadata={"score": s.score},
                        strategy_name=s.strategy_name,
                    )

                # Build market data for BUY tickers (needed by MomentumRanker)
                md_dict: Dict[str, _MD] = {}
                if ranker.requires_market_data():
                    for ticker in ts_dict:
                        md = MarketDataBuilder.build_from_manager(
                            data_manager=data_manager,
                            ticker=ticker,
                            current_date=pd.Timestamp(signal_date),
                        )
                        if md is not None:
                            md_dict[ticker] = md

                ranked = ranker.rank_buy_signals(ts_dict, md_dict)
                rank_map = {
                    ticker: (idx + 1, priority)
                    for idx, (ticker, _, priority) in enumerate(ranked)
                }
                for s in all_signals:
                    if s.signal_type == "BUY" and s.ticker in rank_map:
                        s.rank, s.rank_score = rank_map[s.ticker]
                print(
                    f"\n[Ranking] Applied '{ranking_strategy_name}' to "
                    f"{len(buy_signals)} BUY signals"
                )
        except Exception as e:
            print(f"\n[Ranking] Warning: ranking failed ({e}), skipping")

    # ------- Post-ranking capital allocation (evaluation-consistent) -------
    # Allocate qty/capital to BUY signals in rank order, respecting
    # max_positions, overlay limits, and available cash — just like
    # portfolio_engine does in the evaluation flow.
    buy_signals_all = [s for s in all_signals if s.signal_type == "BUY"]
    buy_signals_all.sort(
        key=lambda s: (s.rank if s.rank is not None else 999999,)
    )

    for group_id, ctx in _group_buy_contexts.items():
        group = ctx["group"]
        overlay_decision = ctx["overlay_decision"]
        total_value = ctx["total_value"]
        projected_sell_proceeds = ctx["projected_sell_proceeds"]
        invested_value = ctx["invested_value"]
        max_new_positions = ctx["max_new_positions"]
        projected_position_count = ctx["projected_position_count"]
        capacity_snapshot = ctx.get("capacity_snapshot")

        planning_cash = float(group.cash) + projected_sell_proceeds
        planning_invested_value = max(0.0, invested_value - projected_sell_proceeds)
        new_positions_opened = 0

        group_buys = [s for s in buy_signals_all if s.group_id == group_id]

        for sig in group_buys:
            if capacity_snapshot is not None:
                _apply_capacity_fields(sig, capacity_snapshot, None)

            execution_max_positions = int(prod_cfg.max_positions_per_group)
            if capacity_snapshot is not None and capacity_mode == "enforce":
                execution_max_positions = capacity_snapshot.max_positions

            # Position limit check (same as evaluation's can_open_new_position)
            if (
                projected_position_count + new_positions_opened
                >= execution_max_positions
            ):
                sig.reason = (
                    f"{sig.reason}; Skipped: max positions ({execution_max_positions}) reached"
                )
                if capacity_snapshot is not None and capacity_mode == "enforce":
                    sig.capacity_blocking_reason = "max_positions"
                    ctx["capacity_blocked_buys"] += 1
                continue

            if max_new_positions is not None and new_positions_opened >= max_new_positions:
                sig.reason = f"{sig.reason}; Skipped: max new positions ({max_new_positions}) reached"
                continue

            if overlay_decision and overlay_decision.block_new_entries:
                sig.reason = f"{sig.reason}; Overlay blocked new entries"
                continue

            signal_buy_scale = extract_buy_size_multiplier({})
            if overlay_decision and overlay_decision.position_scale is not None:
                signal_buy_scale *= overlay_decision.position_scale

            available_cash = planning_cash
            available_exposure = None
            if overlay_decision and overlay_decision.target_exposure is not None:
                max_invested = total_value * overlay_decision.target_exposure
                available_exposure = max(0.0, max_invested - planning_invested_value)
                available_cash = min(available_cash, available_exposure)

            capacity_decision = None
            if capacity_snapshot is not None:
                capacity_decision = compute_order_capacity(
                    tier=capacity_snapshot,
                    turnover_jpy=_extract_turnover_value(sig.ticker, signal_date),
                    available_cash_jpy=planning_cash,
                    available_exposure_jpy=available_exposure,
                    signal_scale=signal_buy_scale,
                )
                _apply_capacity_fields(sig, capacity_snapshot, capacity_decision)
                if capacity_decision.blocking_reason is not None:
                    ctx["capacity_blocked_buys"] += 1
                    if capacity_decision.blocking_reason in {
                        "missing_turnover",
                        "liquidity_floor",
                    }:
                        ctx["capacity_liquidity_blocked_buys"] += 1
                    if capacity_mode == "enforce":
                        sig.reason = (
                            f"{sig.reason}; Capacity blocked: {capacity_decision.blocking_reason}"
                        )
                        continue
                elif capacity_decision.is_trimmed:
                    ctx["capacity_trimmed_buys"] += 1

            if capacity_snapshot is not None and capacity_mode == "enforce" and capacity_decision is not None:
                lot_size = int(lot_sizes.get(sig.ticker, default_lot_size) or default_lot_size)
                lot_value = float(sig.current_price) * lot_size
                lots = int(capacity_decision.order_cap_jpy // lot_value) if lot_value > 0 else 0
                suggested_qty = lots * lot_size
                required_capital = suggested_qty * float(sig.current_price)
            else:
                max_position_pct = float(prod_cfg.max_position_pct)
                if overlay_decision and overlay_decision.position_scale is not None:
                    max_position_pct *= overlay_decision.position_scale
                max_position_pct *= extract_buy_size_multiplier({})
                suggested_qty, required_capital, lot_size = _calc_suggested_qty(
                    ticker=sig.ticker,
                    current_price=sig.current_price,
                    available_cash=available_cash,
                    total_portfolio_value=total_value,
                    max_position_pct=max_position_pct,
                )

            if suggested_qty > 0:
                sig.suggested_qty = suggested_qty
                sig.required_capital = required_capital
                new_positions_opened += 1
                planning_cash = max(0.0, planning_cash - required_capital)
                planning_invested_value += required_capital
            else:
                if capacity_snapshot is not None and capacity_mode == "enforce":
                    sig.capacity_blocking_reason = sig.capacity_blocking_reason or "lot_size"
                    ctx["capacity_blocked_buys"] += 1
                sig.reason = (
                    f"{sig.reason}; SuggestedQty=0: projected cash/exposure "
                    f"insufficient for lot size {lot_size}"
                )

    capacity_summary = None
    if capacity_mode != "off" and capacity_regime is not None:
        capacity_summary = {
            "config_path": str(get_config_file_path()),
            "config_source": _resolve_config_source(),
            "capacity_regime_mode": capacity_mode,
            "capacity_regime_version": capacity_regime.version,
            "groups": [],
        }
        for group in groups:
            ctx = _group_buy_contexts.get(group.id, {})
            snapshot = ctx.get("capacity_snapshot")
            if snapshot is None:
                continue
            capacity_summary["groups"].append(
                {
                    "group_id": group.id,
                    "group_name": group.name,
                    "effective_equity_jpy": snapshot.effective_equity_jpy,
                    "tier_name": snapshot.tier_name,
                    "max_positions": snapshot.max_positions,
                    "max_position_pct": snapshot.max_position_pct,
                    "participation_cap_pct": snapshot.participation_cap_pct,
                    "min_turnover_20_jpy": snapshot.min_turnover_20_jpy,
                    "blocked_buys": int(ctx.get("capacity_blocked_buys", 0)),
                    "liquidity_blocked_buys": int(
                        ctx.get("capacity_liquidity_blocked_buys", 0)
                    ),
                    "trimmed_buys": int(ctx.get("capacity_trimmed_buys", 0)),
                }
            )

    signal_file = prod_cfg.signal_file_pattern.replace("{date}", signal_date)
    Path(signal_file).parent.mkdir(parents=True, exist_ok=True)

    # Custom JSON encoder to handle numpy/pandas types
    class CustomJSONEncoder(json.JSONEncoder):
        def default(self, obj):
            import numpy as np
            import pandas as pd

            if isinstance(obj, (np.integer, np.floating)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, (pd.Timestamp, datetime)):
                return obj.isoformat()
            elif isinstance(obj, np.bool_):
                return bool(obj)
            return super().default(obj)

    filtered_signals = [
        signal for signal in all_signals if signal.ticker not in abnormal_ticker_set
    ]
    filtered_signals = _apply_signal_semantic_metadata(filtered_signals)
    excluded_signal_count = len(all_signals) - len(filtered_signals)
    buy_signal_count = len(
        [signal for signal in filtered_signals if signal.signal_type == "BUY"]
    )
    sell_signal_count = len(
        [signal for signal in filtered_signals if signal.signal_type == "SELL"]
    )

    with open(signal_file, "w", encoding="utf-8") as f:
        json.dump(
            [s.__dict__ for s in filtered_signals],
            f,
            indent=2,
            ensure_ascii=False,
            cls=CustomJSONEncoder,
        )

    print(f"\n[Output] Total signals: {len(filtered_signals)}")
    print(f"  BUY: {buy_signal_count}, SELL: {sell_signal_count}")
    if excluded_signal_count > 0:
        print(f"  Excluded abnormal ticker signals: {excluded_signal_count}")
    print(f"  Signals saved: {signal_file}")

    initial_capital_override = (
        raw_config.get("portfolio", {}).get("starting_capital_jpy")
    )
    builder = ReportBuilder(
        effective_state,
        data_manager,
        history_file=prod_cfg.history_file,
        cash_history_file=prod_cfg.cash_history_file,
        initial_capital_override=initial_capital_override,
        strategy_groups=prod_cfg.strategy_groups,
        default_entry_strategy=prod_cfg.default_entry_strategy,
        default_exit_strategy=prod_cfg.default_exit_strategy,
    )
    report_md = builder.generate_daily_report(
        signals=filtered_signals,
        report_date=signal_date,
        comprehensive_evaluations=comprehensive_evals,
        overlay_summary=overlay_summaries,
        capacity_summary=capacity_summary,
        abnormal_tickers=abnormal_signal_tickers,
    )
    report_md += "\n\n" + _build_buy_diagnostics_markdown(
        groups=groups,
        group_cfg_map=group_configs,
        group_entry_eval_keys=group_entry_eval_keys,
        evals=comprehensive_evals,
        runtime_cfg=prod_cfg,
    )
    report_md += "\n\n" + _build_macd_hist_snapshot_markdown(
        tickers=signal_tickers,
        target_date=signal_date,
        lookback_days=5,
    )
    report_file = prod_cfg.report_file_pattern.replace("{date}", signal_date)
    builder.save_report(report_md, report_file)
    print(f"  Report saved: {report_file}")
