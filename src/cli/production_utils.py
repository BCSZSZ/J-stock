import json
from pathlib import Path
from typing import Dict, List, Optional


def load_monitor_tickers(monitor_list_file: str) -> List[str]:
    """Load monitor tickers from JSON/TXT file."""
    path = Path(monitor_list_file)
    if not path.exists():
        raise FileNotFoundError(f"Monitor list not found: {monitor_list_file}")

    if path.suffix.lower() == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("tickers", []) if isinstance(data, dict) else data
        tickers = [
            item.get("code") if isinstance(item, dict) else str(item) for item in raw
        ]
        return [ticker for ticker in tickers if ticker]

    tickers = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                tickers.append(line)
    return tickers


def ensure_groups(state, config_mgr, prod_cfg) -> None:
    """Ensure strategy groups exist in state."""
    if len(state.get_all_groups()) > 0:
        return

    print("  No strategy groups found. Creating default groups...")
    if prod_cfg.strategy_groups:
        for group_cfg in prod_cfg.strategy_groups:
            state.add_group(
                group_id=group_cfg["id"],
                name=group_cfg["name"],
                initial_capital=group_cfg["initial_capital"],
            )
            print(
                f"    Created: {group_cfg['name']} (¥{group_cfg['initial_capital']:,})"
            )
    else:
        initial_capital = config_mgr.get_initial_capital()
        state.add_group(
            group_id="default",
            name="Default Strategy",
            initial_capital=initial_capital,
        )
        print(f"    Created: Default Strategy (¥{initial_capital:,})")
    state.save()


def get_signal_date_from_path(path: Path) -> Optional[str]:
    stem = path.stem
    if stem.startswith("signals_"):
        return stem.replace("signals_", "")
    return stem


def find_latest_signal_file(pattern: str, signal_date: Optional[str]) -> Optional[Path]:
    if signal_date:
        candidate = Path(pattern.replace("{date}", signal_date))
        return candidate if candidate.exists() else None

    pattern_path = Path(pattern)
    parent = (
        pattern_path.parent if str(pattern_path.parent) not in ["", "."] else Path(".")
    )
    if not parent.exists():
        return None

    files = sorted(parent.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def parse_signal_payload(filepath: Path) -> List[Dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and "signals" in payload:
        flattened = []
        signal_dict = payload.get("signals", {})
        for group_id, group_signals in signal_dict.items():
            for sig in group_signals:
                sig = dict(sig)
                sig.setdefault("group_id", group_id)
                flattened.append(sig)
        return flattened

    return []
