from typing import Dict, List


def build_fetch_jobs(tickers: List[str], tickers_per_job: int = 100) -> List[Dict]:
    """Split ticker list into fetch jobs with fixed max tickers per job."""
    if tickers_per_job <= 0:
        raise ValueError("tickers_per_job must be > 0")

    normalized = [str(t).strip() for t in tickers if str(t).strip()]
    jobs: List[Dict] = []

    for start in range(0, len(normalized), tickers_per_job):
        chunk = normalized[start : start + tickers_per_job]
        jobs.append(
            {
                "job_index": len(jobs),
                "ticker_count": len(chunk),
                "tickers": chunk,
            }
        )

    return jobs
