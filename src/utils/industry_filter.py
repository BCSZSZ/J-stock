from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence


DEFAULT_INDUSTRY_FILTER_MODE = "enforce"
DEFAULT_MAX_BUY_PER_INDUSTRY_PER_DAY = 3
DEFAULT_MAX_TOTAL_POSITIONS_PER_INDUSTRY = 4
DEFAULT_INDUSTRY_REFERENCE_FILE = "data/jpx_final_list.csv"
UNKNOWN_INDUSTRY = "Unknown"

INDUSTRY_FILTER_MODES = {"off", "shadow", "enforce"}

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class IndustryFilterConfig:
    mode: str = DEFAULT_INDUSTRY_FILTER_MODE
    max_buy_per_industry_per_day: int = DEFAULT_MAX_BUY_PER_INDUSTRY_PER_DAY
    max_total_positions_per_industry: int = DEFAULT_MAX_TOTAL_POSITIONS_PER_INDUSTRY
    reference_file: str = DEFAULT_INDUSTRY_REFERENCE_FILE

    @property
    def enabled(self) -> bool:
        return self.mode != "off"


@dataclass(frozen=True)
class IndustryFilterDecision:
    ticker: str
    industry_name: str
    mode: str
    max_buy_per_industry_per_day: int
    max_total_positions_per_industry: int
    industry_filter_rank: int | None
    industry_existing_positions: int | None
    industry_total_positions_after_buy: int | None
    industry_filter_daily_cap_blocked: bool
    industry_filter_total_position_blocked: bool
    blocked: bool
    filtered: bool
    reason: str | None = None

    @property
    def shadowed(self) -> bool:
        return self.blocked and self.mode == "shadow"

    def to_metadata(self) -> dict[str, object]:
        return {
            "industry_name": self.industry_name,
            "industry_filter_mode": self.mode,
            "industry_filter_max_buy_per_day": self.max_buy_per_industry_per_day,
            "industry_filter_max_total_positions": self.max_total_positions_per_industry,
            "industry_filter_rank": self.industry_filter_rank,
            "industry_existing_positions": self.industry_existing_positions,
            "industry_total_positions_after_buy": self.industry_total_positions_after_buy,
            "industry_filter_daily_cap_blocked": self.industry_filter_daily_cap_blocked,
            "industry_filter_total_position_blocked": self.industry_filter_total_position_blocked,
            "industry_filter_blocked": self.blocked,
            "industry_filter_filtered": self.filtered,
            "industry_filter_reason": self.reason,
        }


def normalize_ticker_code(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.upper().endswith(".T"):
        raw = raw[:-2]
    if "." in raw:
        head, tail = raw.split(".", 1)
        if not tail or set(tail) <= {"0"}:
            raw = head
    raw = raw.strip()
    return raw.zfill(4) if raw.isdigit() and len(raw) <= 4 else raw


def _resolve_reference_file(path_value: object) -> Path:
    raw = str(path_value or DEFAULT_INDUSTRY_REFERENCE_FILE).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path.resolve()


def _normalize_industry_name(value: object) -> str:
    name = str(value or "").strip()
    return name if name and name != "-" else UNKNOWN_INDUSTRY


@lru_cache(maxsize=16)
def load_industry_by_ticker(reference_file: str) -> dict[str, str]:
    path = _resolve_reference_file(reference_file)
    if not path.exists():
        return {}

    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            code = normalize_ticker_code(row.get("Code") or row.get("コード"))
            if not code:
                continue
            mapping[code] = _normalize_industry_name(row.get("33業種区分"))
    return mapping


def get_industry_name(ticker: object, reference_file: str) -> str:
    code = normalize_ticker_code(ticker)
    if not code:
        return UNKNOWN_INDUSTRY
    return load_industry_by_ticker(reference_file).get(code, UNKNOWN_INDUSTRY)


def _coerce_mode(value: object, default_mode: str) -> str:
    mode = str(value if value is not None else default_mode).strip().lower()
    if mode not in INDUSTRY_FILTER_MODES:
        raise ValueError(
            f"Unsupported industry filter mode: {value}. "
            "Expected off, shadow, or enforce."
        )
    return mode


def _coerce_positive_int(value: object, default_value: int, field_name: str) -> int:
    try:
        parsed = int(default_value if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def normalize_industry_filter_config(
    raw_config: Mapping[str, object] | None,
    *,
    default_mode: str = DEFAULT_INDUSTRY_FILTER_MODE,
    mode_override: str | None = None,
    max_buy_per_industry_per_day_override: int | None = None,
    max_total_positions_per_industry_override: int | None = None,
    reference_file_override: str | None = None,
    use_configured_mode: bool = True,
) -> IndustryFilterConfig:
    raw = dict(raw_config or {})
    enabled = raw.get("enabled") if use_configured_mode else None
    configured_mode = raw.get("mode") if use_configured_mode else None
    if configured_mode is None and enabled is False:
        configured_mode = "off"

    mode = _coerce_mode(
        mode_override if mode_override is not None else configured_mode,
        default_mode,
    )
    max_buy = _coerce_positive_int(
        (
            max_buy_per_industry_per_day_override
            if max_buy_per_industry_per_day_override is not None
            else raw.get("max_buy_per_industry_per_day")
        ),
        DEFAULT_MAX_BUY_PER_INDUSTRY_PER_DAY,
        "max_buy_per_industry_per_day",
    )
    max_total = _coerce_positive_int(
        (
            max_total_positions_per_industry_override
            if max_total_positions_per_industry_override is not None
            else raw.get("max_total_positions_per_industry")
        ),
        DEFAULT_MAX_TOTAL_POSITIONS_PER_INDUSTRY,
        "max_total_positions_per_industry",
    )
    reference_file = str(
        reference_file_override
        if reference_file_override is not None
        else raw.get("reference_file", DEFAULT_INDUSTRY_REFERENCE_FILE)
    )
    return IndustryFilterConfig(
        mode=mode,
        max_buy_per_industry_per_day=max_buy,
        max_total_positions_per_industry=max_total,
        reference_file=reference_file,
    )


def resolve_industry_filter_config(
    root_config: Mapping[str, object] | None,
    *,
    default_mode: str = DEFAULT_INDUSTRY_FILTER_MODE,
    mode_override: str | None = None,
    max_buy_per_industry_per_day_override: int | None = None,
    max_total_positions_per_industry_override: int | None = None,
    reference_file_override: str | None = None,
    use_configured_mode: bool = True,
) -> IndustryFilterConfig:
    production_cfg = {}
    if isinstance(root_config, Mapping):
        production_raw = root_config.get("production", {})
        if isinstance(production_raw, Mapping):
            production_cfg = production_raw
    raw_filter = production_cfg.get("industry_filter", {})
    if not isinstance(raw_filter, Mapping):
        raw_filter = {}
    return normalize_industry_filter_config(
        raw_filter,
        default_mode=default_mode,
        mode_override=mode_override,
        max_buy_per_industry_per_day_override=max_buy_per_industry_per_day_override,
        max_total_positions_per_industry_override=max_total_positions_per_industry_override,
        reference_file_override=reference_file_override,
        use_configured_mode=use_configured_mode,
    )


def _count_existing_by_industry(
    tickers: Sequence[object] | None,
    reference_file: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for ticker in tickers or []:
        code = normalize_ticker_code(ticker)
        if not code or code in seen:
            continue
        seen.add(code)
        industry = get_industry_name(code, reference_file)
        if industry == UNKNOWN_INDUSTRY:
            continue
        counts[industry] = counts.get(industry, 0) + 1
    return counts


def _reason_prefix(filtered: bool) -> str:
    return "Filtered" if filtered else "Shadow blocked"


def evaluate_industry_filter_for_ranked_tickers(
    ranked_tickers: Sequence[object],
    config: IndustryFilterConfig | Mapping[str, object] | None,
    *,
    existing_position_tickers: Sequence[object] | None = None,
    add_on_tickers: Sequence[object] | None = None,
) -> dict[str, IndustryFilterDecision]:
    normalized = (
        config
        if isinstance(config, IndustryFilterConfig)
        else normalize_industry_filter_config(config, default_mode="off")
    )
    existing_counts = _count_existing_by_industry(
        existing_position_tickers,
        normalized.reference_file,
    )
    add_on_codes = {
        code
        for code in (normalize_ticker_code(ticker) for ticker in add_on_tickers or [])
        if code
    }
    seen_new_counts: dict[str, int] = {}
    accepted_new_counts: dict[str, int] = {}
    decisions: dict[str, IndustryFilterDecision] = {}

    for raw_ticker in ranked_tickers:
        ticker = normalize_ticker_code(raw_ticker)
        if not ticker:
            continue

        industry = get_industry_name(ticker, normalized.reference_file)
        enforceable = industry != UNKNOWN_INDUSTRY and normalized.enabled
        industry_rank: int | None = None
        existing_count: int | None = None
        total_after_buy: int | None = None
        daily_blocked = False
        total_blocked = False
        is_add_on_buy = ticker in add_on_codes

        if enforceable:
            industry_rank = seen_new_counts.get(industry, 0) + 1
            seen_new_counts[industry] = industry_rank
            existing_count = existing_counts.get(industry, 0)
            accepted_count = accepted_new_counts.get(industry, 0)
            total_after_buy = existing_count + accepted_count + (
                0 if is_add_on_buy else 1
            )
            daily_blocked = industry_rank > normalized.max_buy_per_industry_per_day
            total_blocked = (
                (not is_add_on_buy)
                and existing_count + accepted_count
                >= normalized.max_total_positions_per_industry
            )

        blocked = bool(daily_blocked or total_blocked)
        filtered = bool(blocked and normalized.mode == "enforce")
        if enforceable and not filtered and not is_add_on_buy:
            accepted_new_counts[industry] = accepted_new_counts.get(industry, 0) + 1

        reason = None
        if blocked:
            prefix = _reason_prefix(filtered)
            parts: list[str] = []
            if daily_blocked:
                parts.append(
                    "daily industry BUY cap "
                    f"{industry} rank {industry_rank} > "
                    f"{normalized.max_buy_per_industry_per_day}"
                )
            if total_blocked:
                current_total = (existing_count or 0) + accepted_new_counts.get(industry, 0)
                parts.append(
                    "industry total position cap "
                    f"{industry} {current_total}/"
                    f"{normalized.max_total_positions_per_industry} reached"
                )
            reason = f"{prefix}: " + "; ".join(parts)

        decisions[ticker] = IndustryFilterDecision(
            ticker=ticker,
            industry_name=industry,
            mode=normalized.mode,
            max_buy_per_industry_per_day=normalized.max_buy_per_industry_per_day,
            max_total_positions_per_industry=normalized.max_total_positions_per_industry,
            industry_filter_rank=industry_rank,
            industry_existing_positions=existing_count,
            industry_total_positions_after_buy=total_after_buy,
            industry_filter_daily_cap_blocked=daily_blocked,
            industry_filter_total_position_blocked=total_blocked,
            blocked=blocked,
            filtered=filtered,
            reason=reason,
        )

    return decisions
