from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Sequence


TradeAction = Literal["BUY", "SELL"]

_SBI_CSV_ENCODING = "cp932"
_DETAIL_HEADER = "約定日"
_TRADE_KIND_BUY = "現物買"
_TRADE_KIND_SELL = "現物売"
_REQUIRED_COLUMNS = (
    "約定日",
    "銘柄",
    "銘柄コード",
    "市場",
    "取引",
    "約定数量",
    "約定単価",
    "受渡日",
)


@dataclass(frozen=True)
class SbiTradeRecord:
    trade_date: str
    ticker: str
    ticker_name: str
    action: TradeAction
    quantity: int
    price: float
    market: str
    settlement_date: str
    source_file: str
    source_row: int


@dataclass(frozen=True)
class AggregatedSbiTrade:
    trade_date: str
    ticker: str
    ticker_name: str
    action: TradeAction
    quantity: int
    price: float
    fill_count: int
    markets: tuple[str, ...]
    source_file: str


@dataclass
class _AggregateBucket:
    trade_date: str
    ticker: str
    ticker_name: str
    action: TradeAction
    quantity: int = 0
    notional: float = 0.0
    fill_count: int = 0
    markets: set[str] = field(default_factory=set)
    source_file: str = ""


def find_latest_sbi_history_csv(history_dir: str | None) -> Path | None:
    if not history_dir:
        return None

    root = Path(history_dir)
    if not root.exists() or not root.is_dir():
        return None

    files = sorted(
        (path for path in root.glob("*.csv") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def format_sbi_history_mtime(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def parse_sbi_trade_history_csv(csv_path: Path) -> list[SbiTradeRecord]:
    if not csv_path.exists():
        raise FileNotFoundError(f"SBI history CSV not found: {csv_path}")

    records: list[SbiTradeRecord] = []
    header_map: dict[str, int] | None = None

    with csv_path.open("r", encoding=_SBI_CSV_ENCODING, newline="") as handle:
        reader = csv.reader(handle)
        for row_index, raw_row in enumerate(reader, start=1):
            row = [cell.strip() for cell in raw_row]
            if not row or all(not cell for cell in row):
                continue

            if header_map is None:
                if row[0] != _DETAIL_HEADER:
                    continue
                header_map = _build_header_map(row)
                continue

            trade_date_raw = row[header_map[_DETAIL_HEADER]].strip()
            if not trade_date_raw:
                continue

            if len(trade_date_raw) != 10 or trade_date_raw[4] != "/" or trade_date_raw[7] != "/":
                continue

            action = _parse_trade_action(row[header_map["取引"]])
            if action is None:
                continue

            records.append(
                SbiTradeRecord(
                    trade_date=_normalize_date(trade_date_raw),
                    ticker=row[header_map["銘柄コード"]].strip(),
                    ticker_name=row[header_map["銘柄"]].strip(),
                    action=action,
                    quantity=_parse_int(row[header_map["約定数量"]]),
                    price=_parse_float(row[header_map["約定単価"]]),
                    market=row[header_map["市場"]].strip(),
                    settlement_date=_normalize_date(row[header_map["受渡日"]]),
                    source_file=str(csv_path),
                    source_row=row_index,
                )
            )

    if header_map is None:
        raise ValueError(f"SBI detail header not found in {csv_path}")

    return records


def aggregate_sbi_trades_for_date(
    trades: Sequence[SbiTradeRecord],
    trade_date: str,
) -> list[AggregatedSbiTrade]:
    buckets: dict[tuple[str, str, TradeAction], _AggregateBucket] = {}

    for trade in trades:
        if trade.trade_date != trade_date:
            continue

        key = (trade.trade_date, trade.ticker, trade.action)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = _AggregateBucket(
                trade_date=trade.trade_date,
                ticker=trade.ticker,
                ticker_name=trade.ticker_name,
                action=trade.action,
                source_file=trade.source_file,
            )
            buckets[key] = bucket

        bucket.quantity += trade.quantity
        bucket.notional += trade.quantity * trade.price
        bucket.fill_count += 1
        if trade.market:
            bucket.markets.add(trade.market)

    aggregated = [
        AggregatedSbiTrade(
            trade_date=bucket.trade_date,
            ticker=bucket.ticker,
            ticker_name=bucket.ticker_name,
            action=bucket.action,
            quantity=bucket.quantity,
            price=round(bucket.notional / bucket.quantity, 6),
            fill_count=bucket.fill_count,
            markets=tuple(sorted(bucket.markets)),
            source_file=bucket.source_file,
        )
        for bucket in buckets.values()
        if bucket.quantity > 0
    ]
    return sorted(aggregated, key=lambda trade: (0 if trade.action == "SELL" else 1, trade.ticker))


def _build_header_map(header_row: Sequence[str]) -> dict[str, int]:
    header_map = {
        column.strip(): index
        for index, column in enumerate(header_row)
        if column.strip()
    }
    missing = [column for column in _REQUIRED_COLUMNS if column not in header_map]
    if missing:
        raise ValueError(f"SBI detail header missing columns: {', '.join(missing)}")
    return header_map


def _normalize_date(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    return normalized.replace("/", "-")


def _parse_trade_action(value: str) -> TradeAction | None:
    normalized = value.strip()
    if _TRADE_KIND_BUY in normalized:
        return "BUY"
    if _TRADE_KIND_SELL in normalized:
        return "SELL"
    return None


def _parse_int(value: str) -> int:
    normalized = value.strip().replace(",", "")
    return int(normalized)


def _parse_float(value: str) -> float:
    normalized = value.strip().replace(",", "")
    return float(normalized)