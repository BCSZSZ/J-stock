import json
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from .base import BaseOverlay, OverlayContext, OverlayDecision


class SectorBreadthOverlay(BaseOverlay):
    name = "SectorBreadthOverlay"
    priority = 20
    requires_benchmark_data = False

    def __init__(self, config: Optional[Dict[str, Any]] = None, data_root: str = "data"):
        super().__init__(config=config)
        self.data_root = data_root

    def evaluate(self, context: OverlayContext) -> OverlayDecision:
        if not self.enabled:
            return OverlayDecision(source=self.name, metadata={"status": "disabled"})

        metrics_path = Path(
            self.config.get(
                "metrics_file",
                str(Path(self.data_root) / "features" / "sector_daily_metrics.parquet"),
            )
        )
        snapshot_dir = Path(
            self.config.get(
                "snapshot_dir",
                str(Path(self.data_root) / "metadata" / "sector_overlay"),
            )
        )

        if not metrics_path.exists():
            return OverlayDecision(
                source=self.name,
                metadata={
                    "status": "no_sector_metrics",
                    "metrics_file": str(metrics_path),
                },
            )

        try:
            metrics = pd.read_parquet(metrics_path)
        except Exception as exc:
            return OverlayDecision(
                source=self.name,
                metadata={
                    "status": "metrics_read_error",
                    "error": str(exc),
                    "metrics_file": str(metrics_path),
                },
            )

        required = {"Date", "sector", "sector_score", "is_low_coverage"}
        if not required.issubset(metrics.columns):
            return OverlayDecision(
                source=self.name,
                metadata={
                    "status": "metrics_schema_error",
                    "missing_columns": sorted(list(required - set(metrics.columns))),
                },
            )

        metrics = metrics.copy()
        metrics["Date"] = pd.to_datetime(metrics["Date"], errors="coerce")
        metrics = metrics.dropna(subset=["Date", "sector", "sector_score"])
        if metrics.empty:
            return OverlayDecision(
                source=self.name,
                metadata={"status": "metrics_empty"},
            )

        latest_date = metrics["Date"].max()
        latest = metrics[metrics["Date"] == latest_date].copy()
        if latest.empty:
            return OverlayDecision(
                source=self.name,
                metadata={"status": "latest_metrics_empty"},
            )

        sector_score_strong = float(self.config.get("sector_score_strong", 60.0))
        sector_score_weak = float(self.config.get("sector_score_weak", 45.0))
        low_coverage_block_ratio = float(self.config.get("low_coverage_block_ratio", 0.40))

        valid = latest[~latest["is_low_coverage"].astype(bool)]
        if valid.empty:
            return OverlayDecision(
                source=self.name,
                block_new_entries=True,
                max_new_positions=0,
                metadata={
                    "status": "all_low_coverage",
                    "latest_date": latest_date.strftime("%Y-%m-%d"),
                    "sector_count": int(len(latest)),
                },
            )

        median_score = float(valid["sector_score"].median())
        strong_ratio = float((valid["sector_score"] >= sector_score_strong).mean())
        weak_ratio = float((valid["sector_score"] < sector_score_weak).mean())
        low_cov_ratio = float(latest["is_low_coverage"].astype(bool).mean())

        risk_on_target = float(self.config.get("risk_on_target_exposure", 1.00))
        neutral_target = float(self.config.get("neutral_target_exposure", 0.80))
        risk_off_target = float(self.config.get("risk_off_target_exposure", 0.55))

        risk_on_max_new = int(self.config.get("risk_on_max_new_positions", 3))
        neutral_max_new = int(self.config.get("neutral_max_new_positions", 1))
        risk_off_max_new = int(self.config.get("risk_off_max_new_positions", 0))

        risk_on_min_score = float(self.config.get("risk_on_min_score", 58.0))
        risk_on_min_strong_ratio = float(self.config.get("risk_on_min_strong_ratio", 0.45))
        risk_on_max_weak_ratio = float(self.config.get("risk_on_max_weak_ratio", 0.25))

        neutral_min_score = float(self.config.get("neutral_min_score", 52.0))
        neutral_min_strong_ratio = float(self.config.get("neutral_min_strong_ratio", 0.30))
        block_when_risk_off = bool(self.config.get("block_new_entries_when_risk_off", True))

        regime = "RISK_OFF"
        target_exposure = risk_off_target
        max_new_positions = risk_off_max_new
        block_new_entries = block_when_risk_off

        if low_cov_ratio >= low_coverage_block_ratio:
            regime = "DATA_GUARD"
            target_exposure = None
            max_new_positions = 0
            block_new_entries = True
        elif (
            median_score >= risk_on_min_score
            and strong_ratio >= risk_on_min_strong_ratio
            and weak_ratio <= risk_on_max_weak_ratio
        ):
            regime = "RISK_ON"
            target_exposure = risk_on_target
            max_new_positions = risk_on_max_new
            block_new_entries = False
        elif median_score >= neutral_min_score and strong_ratio >= neutral_min_strong_ratio:
            regime = "NEUTRAL"
            target_exposure = neutral_target
            max_new_positions = neutral_max_new
            block_new_entries = False

        exit_overrides: Dict[str, str] = {}
        if regime != "DATA_GUARD" and bool(self.config.get("enable_exit_overrides", True)):
            exit_sector_score_threshold = float(self.config.get("exit_sector_score_threshold", 42.0))
            exit_min_pnl_pct = float(self.config.get("exit_min_pnl_pct", -2.0))
            max_daily_overlay_exits = int(self.config.get("max_daily_overlay_exits", 2))

            sector_score_map = {
                str(row["sector"]): float(row["sector_score"])
                for _, row in valid.iterrows()
            }
            ticker_sector_map = self._load_latest_ticker_sector_map(snapshot_dir)

            candidates = []
            for ticker, position in (context.positions or {}).items():
                sector = ticker_sector_map.get(str(ticker).zfill(4))
                if not sector:
                    continue
                sector_score = sector_score_map.get(sector)
                if sector_score is None or sector_score >= exit_sector_score_threshold:
                    continue

                current_price = context.current_prices.get(ticker)
                entry_price = getattr(position, "entry_price", None)
                if entry_price is None and isinstance(position, dict):
                    entry_price = position.get("entry_price")

                pnl_pct = None
                if current_price is not None and entry_price:
                    pnl_pct = (float(current_price) - float(entry_price)) / float(entry_price) * 100.0

                if pnl_pct is not None and pnl_pct > exit_min_pnl_pct:
                    continue

                candidates.append((ticker, sector, sector_score, pnl_pct))

            candidates.sort(key=lambda x: (x[2], x[3] if x[3] is not None else 0.0))
            for ticker, sector, sector_score, pnl_pct in candidates[:max_daily_overlay_exits]:
                pnl_txt = f", pnl={pnl_pct:.2f}%" if pnl_pct is not None else ""
                exit_overrides[ticker] = (
                    f"Sector overlay exit: {sector} score {sector_score:.1f} < {exit_sector_score_threshold:.1f}{pnl_txt}"
                )

        metadata = {
            "status": "ok",
            "regime": regime,
            "latest_date": latest_date.strftime("%Y-%m-%d"),
            "sector_count": int(len(latest)),
            "valid_sector_count": int(len(valid)),
            "median_sector_score": round(median_score, 3),
            "strong_ratio": round(strong_ratio, 3),
            "weak_ratio": round(weak_ratio, 3),
            "low_coverage_ratio": round(low_cov_ratio, 3),
            "metrics_file": str(metrics_path),
            "snapshot_dir": str(snapshot_dir),
        }

        return OverlayDecision(
            source=self.name,
            target_exposure=target_exposure,
            max_new_positions=max_new_positions,
            block_new_entries=block_new_entries,
            exit_overrides=exit_overrides,
            metadata=metadata,
        )

    @staticmethod
    def _load_latest_ticker_sector_map(snapshot_dir: Path) -> Dict[str, str]:
        if not snapshot_dir.exists() or not snapshot_dir.is_dir():
            return {}

        snapshots = sorted(snapshot_dir.glob("universe_snapshot_*.json"))
        if not snapshots:
            return {}

        latest = snapshots[-1]
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
        except Exception:
            return {}

        members = payload.get("members", [])
        result: Dict[str, str] = {}
        for item in members:
            ticker = str(item.get("ticker", "")).strip().zfill(4)
            sector = str(item.get("sector", "")).strip()
            if ticker and sector:
                result[ticker] = sector
        return result
