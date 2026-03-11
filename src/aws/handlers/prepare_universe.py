from datetime import datetime
from typing import Any, Dict, List


def _split_shards(tickers: List[str], shard_count: int = 8) -> List[Dict[str, Any]]:
    if not tickers:
        return []
    shards: List[Dict[str, Any]] = []
    for idx in range(shard_count):
        subset = tickers[idx::shard_count]
        if subset:
            shards.append({"shard_id": idx, "tickers": subset})
    return shards


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    # Phase2: replace with S3 monitor list loading + fetch universe merge logic.
    tickers = event.get("tickers", [])
    shards = _split_shards(tickers=tickers, shard_count=int(event.get("shard_count", 8)))
    return {
        "run_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "shards": shards,
        "meta": {"prepared_at": datetime.utcnow().isoformat(), "ticker_count": len(tickers)},
    }
