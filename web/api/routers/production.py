"""Production endpoints: daily run, status, set-cash, input trades."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
from datetime import date, timedelta
from pathlib import Path
from queue import Queue, Empty
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.aws.jpx_holidays import next_trading_day as _next_trading_day
from src.cli.production_utils import find_latest_signal_file, parse_signal_payload
from src.production.input_trade_import_preview import (
    AggregatedSbiTrade,
    aggregate_sbi_trades_for_date,
    find_latest_sbi_history_csv,
    format_sbi_history_mtime,
    parse_sbi_trade_history_csv,
)
from src.utils.momentum_exhaustion import (
    DEFAULT_PRODUCTION_MOMENTUM_EXHAUSTION_MODE,
    resolve_momentum_exhaustion_config,
)
from src.utils.industry_filter import (
    DEFAULT_INDUSTRY_FILTER_MODE,
    resolve_industry_filter_config,
)
from src.utils.atr_position_sizing import (
    DEFAULT_ATR_RISK_PER_TRADE_PCT,
    DEFAULT_ATR_STOP_MULTIPLE,
)
from web.api.dependencies import get_config_manager, get_production_config, get_project_root
from web.api.schemas import (
    InputTradeRequest,
    InputTradeImportPreviewResponse,
    InputTradeImportPreviewRow,
    ProductionDailyRequest,
    SetCashRequest,
)

router = APIRouter(prefix="/api/production", tags=["production"])

TradeAction = Literal["BUY", "SELL"]


def _append_atr_runtime_flags(args: list[str], req: ProductionDailyRequest) -> None:
    fields_set = getattr(req, "model_fields_set", set())
    if req.position_sizing_mode:
        args.extend(["--position-sizing-mode", req.position_sizing_mode])
    if req.position_sizing_mode != "fixed":
        if req.risk_per_trade_pct is not None:
            args.extend(["--risk-per-trade-pct", str(req.risk_per_trade_pct)])
        if req.atr_stop_multiple is not None:
            args.extend(["--atr-stop-multiple", str(req.atr_stop_multiple)])
    if req.atr_ratio_min is not None:
        args.extend(["--atr-ratio-min", str(req.atr_ratio_min)])
    elif "atr_ratio_min" in fields_set:
        args.extend(["--atr-ratio-min", "none"])
    if req.atr_ratio_max is not None:
        args.extend(["--atr-ratio-max", str(req.atr_ratio_max)])
    elif "atr_ratio_max" in fields_set:
        args.extend(["--atr-ratio-max", "none"])


def _append_momentum_exhaustion_flags(args: list[str], req: ProductionDailyRequest) -> None:
    if req.momentum_exhaustion_mode:
        args.extend(["--momentum-exhaustion-mode", req.momentum_exhaustion_mode])
    if req.momentum_exhaustion_max_score is not None:
        args.extend(["--momentum-exhaustion-max-score", str(req.momentum_exhaustion_max_score)])
    if req.momentum_exhaustion_threshold_method:
        args.extend(
            [
                "--momentum-exhaustion-threshold-method",
                req.momentum_exhaustion_threshold_method,
            ]
        )


def _append_industry_filter_flags(args: list[str], req: ProductionDailyRequest) -> None:
    if req.industry_filter_mode:
        args.extend(["--industry-filter-mode", req.industry_filter_mode])
    if req.max_buy_per_industry_per_day is not None:
        args.extend([
            "--max-buy-per-industry-per-day",
            str(req.max_buy_per_industry_per_day),
        ])
    if req.max_total_positions_per_industry is not None:
        args.extend([
            "--max-total-positions-per-industry",
            str(req.max_total_positions_per_industry),
        ])
    if req.industry_reference_file:
        args.extend(["--industry-reference-file", req.industry_reference_file])


def _append_held_position_buy_flags(args: list[str], req: ProductionDailyRequest) -> None:
    if req.allow_held_position_buys:
        args.append("--allow-held-position-buys")


def _resolve_production_atr_defaults(cfg) -> dict[str, object]:
    raw_config = getattr(cfg, "raw_config", {}) or {}
    entry_filter = raw_config.get("production", {}).get("entry_filter")
    if not isinstance(entry_filter, dict):
        entry_filter = {}
    return {
        "position_sizing_mode": str(getattr(cfg, "position_sizing_mode", "fixed") or "fixed"),
        "risk_per_trade_pct": float(
            getattr(
                cfg.atr_position_sizing,
                "risk_per_trade_pct",
                DEFAULT_ATR_RISK_PER_TRADE_PCT,
            )
        ),
        "atr_stop_multiple": float(
            getattr(
                cfg.atr_position_sizing,
                "atr_stop_multiple",
                DEFAULT_ATR_STOP_MULTIPLE,
            )
        ),
        "atr_ratio_min": entry_filter.get("atr_price_min"),
        "atr_ratio_max": entry_filter.get("atr_price_max"),
    }


def _resolve_production_momentum_exhaustion_defaults(cfg) -> dict[str, object]:
    raw_config = getattr(cfg, "raw_config", {}) or {}
    cfg_filter = resolve_momentum_exhaustion_config(
        raw_config,
        default_mode=DEFAULT_PRODUCTION_MOMENTUM_EXHAUSTION_MODE,
    )
    return {
        "momentum_exhaustion_mode": cfg_filter.mode,
        "momentum_exhaustion_max_score": cfg_filter.max_score,
        "momentum_exhaustion_threshold_method": cfg_filter.threshold_method,
    }


def _resolve_production_industry_filter_defaults(cfg) -> dict[str, object]:
    raw_config = getattr(cfg, "raw_config", {}) or {}
    cfg_filter = resolve_industry_filter_config(
        raw_config,
        default_mode=DEFAULT_INDUSTRY_FILTER_MODE,
    )
    return {
        "industry_filter_mode": cfg_filter.mode,
        "max_buy_per_industry_per_day": cfg_filter.max_buy_per_industry_per_day,
        "max_total_positions_per_industry": (
            cfg_filter.max_total_positions_per_industry
        ),
        "industry_reference_file": cfg_filter.reference_file,
    }


def _resolve_import_trade_date(signal_date: str) -> str:
    signal_day = date.fromisoformat(signal_date)
    return _next_trading_day(signal_day + timedelta(days=1)).isoformat()


def _signal_int(value: object) -> int:
    if value is None:
        return 0
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _signal_trade_action(signal: dict[str, object]) -> TradeAction | None:
    signal_type = str(signal.get("signal_type", "") or "").upper()
    executable_sell = signal.get("is_executable_sell")
    if isinstance(executable_sell, bool):
        if executable_sell:
            return "SELL"
    elif signal_type == "SELL" and _signal_int(signal.get("planned_sell_qty")) > 0:
        return "SELL"

    executable_buy = signal.get("is_executable_buy")
    if isinstance(executable_buy, bool):
        if executable_buy:
            return "BUY"
    elif signal_type == "BUY" and _signal_int(signal.get("suggested_qty")) > 0:
        return "BUY"

    return None


def _signal_trade_quantity(signal: dict[str, object]) -> int:
    action = _signal_trade_action(signal)
    if action == "SELL":
        return _signal_int(signal.get("planned_sell_qty"))
    if action == "BUY":
        return _signal_int(signal.get("suggested_qty"))
    return 0


def _build_signal_preview_rows(
    signals: list[dict[str, object]],
    trade_date: str,
) -> list[InputTradeImportPreviewRow]:
    rows: list[InputTradeImportPreviewRow] = []
    for signal in signals:
        ticker = str(signal.get("ticker", "") or "").strip()
        action = _signal_trade_action(signal)
        quantity = _signal_trade_quantity(signal)
        if not ticker or action is None or quantity <= 0:
            continue
        rows.append(
            InputTradeImportPreviewRow(
                ticker=ticker,
                action=action,
                quantity=quantity,
                price=None,
                date=trade_date,
                source="signal",
                fill_count=None,
            )
        )
    return sorted(rows, key=lambda row: (0 if row.action == "SELL" else 1, row.ticker))


def _build_broker_preview_row(trade: AggregatedSbiTrade) -> InputTradeImportPreviewRow:
    return InputTradeImportPreviewRow(
        ticker=trade.ticker,
        action=trade.action,
        quantity=trade.quantity,
        price=trade.price,
        date=trade.trade_date,
        source="sbi_csv",
        fill_count=trade.fill_count,
    )


def _append_warning_once(warnings: list[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


@router.get("/input-trades/import-preview", response_model=InputTradeImportPreviewResponse)
def input_trade_import_preview(
    signal_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> InputTradeImportPreviewResponse:
    cfg = get_production_config()
    signal_path = find_latest_signal_file(cfg.signal_file_pattern, signal_date)
    if not signal_path:
        raise HTTPException(status_code=404, detail=f"Signal file not found for {signal_date}")

    trade_date = _resolve_import_trade_date(signal_date)
    signals = parse_signal_payload(signal_path)
    signal_rows = _build_signal_preview_rows(signals, trade_date)
    warnings: list[str] = []
    if not signal_rows:
        _append_warning_once(
            warnings,
            f"No executable signal rows found for {signal_date}.",
        )

    latest_csv_path = find_latest_sbi_history_csv(getattr(cfg, "sbi_history_dir", None))
    latest_csv_mtime = format_sbi_history_mtime(latest_csv_path)
    broker_rows: list[AggregatedSbiTrade] = []

    if latest_csv_path is None:
        _append_warning_once(
            warnings,
            "No SBI history CSV files were found; kept signal-derived rows.",
        )
    else:
        try:
            broker_records = parse_sbi_trade_history_csv(latest_csv_path)
            broker_rows = aggregate_sbi_trades_for_date(broker_records, trade_date)
        except (OSError, UnicodeError, ValueError) as exc:
            _append_warning_once(
                warnings,
                f"Failed to read latest SBI CSV {latest_csv_path.name}: {exc}. Kept signal-derived rows.",
            )
            broker_rows = []

    if not broker_rows:
        if latest_csv_path is not None:
            _append_warning_once(
                warnings,
                f"No rows for trade date {trade_date} were found in latest SBI CSV {latest_csv_path.name}; kept signal-derived rows.",
            )
        return InputTradeImportPreviewResponse(
            signal_date=signal_date,
            trade_date=trade_date,
            latest_csv_file=str(latest_csv_path) if latest_csv_path else None,
            latest_csv_mtime=latest_csv_mtime,
            rows=signal_rows,
            warnings=warnings,
            matched_count=0,
            csv_only_count=0,
            signal_only_count=0,
            mode="signal_fallback",
        )

    broker_map = {(row.ticker, row.action): row for row in broker_rows}
    signal_tickers = {row.ticker for row in signal_rows}
    used_broker_keys: set[tuple[str, str]] = set()
    final_rows: list[InputTradeImportPreviewRow] = []
    matched_count = 0
    csv_only_count = 0
    signal_only_count = 0
    action_mismatch_tickers: set[str] = set()

    for signal_row in signal_rows:
        key = (signal_row.ticker, signal_row.action)
        broker_row = broker_map.get(key)
        if broker_row is not None:
            final_rows.append(_build_broker_preview_row(broker_row))
            used_broker_keys.add(key)
            matched_count += 1
            if broker_row.quantity != signal_row.quantity:
                _append_warning_once(
                    warnings,
                    f"{signal_row.ticker}: signal qty {signal_row.quantity} differs from SBI CSV qty {broker_row.quantity}; using CSV.",
                )
            continue

        broker_same_ticker = [row for row in broker_rows if row.ticker == signal_row.ticker]
        if broker_same_ticker:
            if signal_row.ticker not in action_mismatch_tickers:
                actual_actions = ", ".join(sorted({row.action for row in broker_same_ticker}))
                _append_warning_once(
                    warnings,
                    f"{signal_row.ticker}: signal action {signal_row.action} differs from SBI CSV action {actual_actions}; using CSV.",
                )
                action_mismatch_tickers.add(signal_row.ticker)
            continue

        signal_only_count += 1
        _append_warning_once(
            warnings,
            f"{signal_row.ticker}: signal row was not found in the latest SBI CSV and was excluded because CSV is authoritative.",
        )

    for broker_row in broker_rows:
        key = (broker_row.ticker, broker_row.action)
        if key in used_broker_keys:
            continue
        final_rows.append(_build_broker_preview_row(broker_row))
        if broker_row.ticker not in signal_tickers:
            csv_only_count += 1
            _append_warning_once(
                warnings,
                f"{broker_row.ticker}: present in the latest SBI CSV but missing from signals; included because CSV is authoritative.",
            )

    return InputTradeImportPreviewResponse(
        signal_date=signal_date,
        trade_date=trade_date,
        latest_csv_file=str(latest_csv_path) if latest_csv_path else None,
        latest_csv_mtime=latest_csv_mtime,
        rows=final_rows,
        warnings=warnings,
        matched_count=matched_count,
        csv_only_count=csv_only_count,
        signal_only_count=signal_only_count,
        mode="csv_authoritative",
    )


async def _run_cli_streaming(args: list[str]) -> StreamingResponse:
    """Run a CLI command and stream stdout/stderr as SSE.

    Uses subprocess.Popen in a thread to avoid Windows asyncio subprocess limitations.
    """
    root = get_project_root()

    async def event_stream():  # type: ignore[return]
        q: Queue[str | None] = Queue()

        def _reader() -> None:
            proc = subprocess.Popen(
                ["uv", "run", "python", "main.py", *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(root),
            )
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                text = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                q.put(f"data: {json.dumps({'line': text})}\n\n")
            code = proc.wait()
            q.put(f"data: {json.dumps({'done': True, 'exit_code': code})}\n\n")
            q.put(None)  # sentinel

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

        while True:
            # Yield control back to event loop while waiting for output
            try:
                chunk = await asyncio.get_event_loop().run_in_executor(None, lambda: q.get(timeout=0.1))
            except Empty:
                continue
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status")
def production_status() -> dict[str, object]:
    cfg = get_production_config()
    state_path = Path(cfg.state_file)
    if not state_path.exists():
        raise HTTPException(status_code=404, detail="State file not found")
    state_data = json.loads(state_path.read_text(encoding="utf-8"))

    groups_summary: list[dict[str, object]] = []
    raw_groups = state_data.get("strategy_groups", [])
    items: list[tuple[str, dict]] = []
    if isinstance(raw_groups, list):
        items = [(g.get("id", f"group_{i}"), g) for i, g in enumerate(raw_groups)]
    elif isinstance(raw_groups, dict):
        items = list(raw_groups.items())
    for gid, g in items:
        positions = g.get("positions", [])
        groups_summary.append({
            "id": gid,
            "name": g.get("name", gid),
            "cash": g.get("cash", 0),
            "position_count": len(positions),
            "tickers": [p["ticker"] for p in positions],
        })

    return {
        "last_updated": state_data.get("last_updated", ""),
        "groups": groups_summary,
    }


@router.get("/options")
def production_options() -> dict[str, object]:
    cfg = get_production_config()
    cm = get_config_manager()
    stock_pools = [pool.to_api_dict() for pool in cm.list_stock_pools()]
    return {
        "production": {
            "monitor_list_file": str(getattr(cfg, "monitor_list_file", "") or ""),
            "sector_pool_file": str(getattr(cfg, "sector_pool_file", "") or ""),
            "stock_pool_catalog_file": str(getattr(cfg, "stock_pool_catalog_file", "") or ""),
        },
        "defaults": {
            "pool_id": "",
            **_resolve_production_atr_defaults(cfg),
            **_resolve_production_momentum_exhaustion_defaults(cfg),
            **_resolve_production_industry_filter_defaults(cfg),
        },
        "stock_pools": stock_pools,
    }


@router.post("/daily")
async def run_daily(req: ProductionDailyRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    args = ["production", "--daily"]
    if req.no_fetch:
        args.append("--no-fetch")
    if req.pool_id:
        args.extend(["--pool-id", req.pool_id])
    _append_atr_runtime_flags(args, req)
    _append_momentum_exhaustion_flags(args, req)
    _append_industry_filter_flags(args, req)
    _append_held_position_buy_flags(args, req)
    return await _run_cli_streaming(args)


@router.post("/check-price-all")
async def run_check_price_all(req: ConfirmRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    return await _run_cli_streaming(["production", "--check-price", "all"])


@router.post("/check-price-today")
async def run_check_price_today(req: ConfirmRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    return await _run_cli_streaming(["production", "--check-price", "today"])


@router.post("/set-cash")
async def set_cash(req: SetCashRequest) -> dict[str, str]:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    root = get_project_root()
    proc = subprocess.run(
        [
            "uv", "run", "python", "main.py",
            "production", "--set-cash", str(req.amount),
            "--group-id", req.group_id,
        ],
        capture_output=True,
        cwd=str(root),
    )
    output = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        output += proc.stderr.decode("utf-8", errors="replace")
        raise HTTPException(status_code=500, detail=output)
    return {"status": "ok", "output": output}


@router.post("/input-trades")
async def input_trades(req: InputTradeRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")

    # Write trades to a temp CSV
    root = get_project_root()
    csv_path = root / "web" / "_temp_trades.csv"
    lines = ["ticker,action,qty,price,date"]
    for t in req.trades:
        lines.append(f"{t.ticker},{t.action},{t.quantity},{t.price},{t.date}")
    csv_path.write_text("\n".join(lines), encoding="utf-8")

    args = [
        "production", "--input", "--manual",
        "--manual-file", str(csv_path),
        "--yes",
    ]
    if req.aws_profile:
        args.extend(["--aws-profile", req.aws_profile])
    return await _run_cli_streaming(args)


class ConfirmRequest(BaseModel):
    confirm: bool = False


@router.post("/fetch")
async def run_fetch(req: ConfirmRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    return await _run_cli_streaming(["fetch", "--all"])


@router.post("/universe")
async def run_universe(req: ConfirmRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    return await _run_cli_streaming([
        "universe-sector", "--score-model", "v2",
        "--size-balance", "--no-fetch", "--resume",
    ])
