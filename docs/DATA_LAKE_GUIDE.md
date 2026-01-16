# Data Lake Architecture Guide

## Overview

The J-Stock-Analyzer now implements a production-grade **Data Lake** architecture for systematic data organization and ETL processing.

## Folder Structure

```
./data/
├── raw_prices/          # Daily OHLCV data (Incremental updates)
│   ├── 6758.parquet
│   ├── 7203.parquet
│   └── ...
├── raw_financials/      # Quarterly financial summaries
│   ├── 6758_financials.parquet
│   └── ...
├── raw_trades/          # Weekly investor trading data
│   ├── 6758_trades.parquet
│   └── ...
├── features/            # Computed technical indicators (The Transform Layer)
│   ├── 6758_features.parquet
│   └── ...
└── metadata/            # Earnings calendar, sector info (JSON)
    ├── 6758_metadata.json
    ├── reports/         # ETL pipeline summaries
    │   └── etl_summary_20260108_143052.json
    └── ...
```

## Data Flow

```
┌─────────────────┐
│  J-Quants API   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│  raw_prices/    │────▶│   features/      │  (Transform)
└─────────────────┘     └──────────────────┘
         │
         ├─────▶ raw_financials/  (Context)
         ├─────▶ raw_trades/      (Context)
         └─────▶ metadata/        (Catalog)
```

## ETL Strategy

### 1. Stock Prices (OHLC)

**Strategy:** Incremental Update with 5-year history

- **Cold Start:** Fetch full 5 years
- **Daily Update:** Only fetch new data since `last_date`
- **Safety:** Atomic writes (temp file → rename)

### 2. Financial Data

**Strategy:** Fetch Latest & Append

- Quarterly updates (less frequent)
- Stored separately to avoid normalization issues

### 3. Investor Trading Data

**Strategy:** Fetch Latest 90 days

- Weekly data from J-Quants
- Shows Foreign/Retail buy/sell patterns

### 4. Features (Technical Indicators)

**Strategy:** Computed from raw_prices

Using the `ta` library:

- **Trend:** EMA (20, 50, 200)
- **Momentum:** RSI (14), MACD
- **Volatility:** ATR (14)
- **Volume:** SMA (20)

## Usage

### Basic ETL for a Single Stock

```python
from src.data.stock_data_manager import StockDataManager

manager = StockDataManager(api_key='your_key')

# Full ETL pipeline
result = manager.run_full_etl('6758')

# Or step-by-step
df_prices = manager.fetch_and_update_ohlc('6758')
df_features = manager.compute_features('6758')
df_financials = manager.fetch_and_save_financials('6758')
```

### Batch Processing

```python
from src.data.pipeline import StockETLPipeline

pipeline = StockETLPipeline(api_key='your_key')

tickers = ['6758', '7203', '9984']

# Run batch with progress bar
summary = pipeline.run_batch(tickers, fetch_aux_data=True)

# Print results
pipeline.print_summary()

# Retry failed ones
pipeline.retry_failed()
```

### Convenience Functions

```python
from src.data.pipeline import run_daily_update, run_weekly_full_sync

# For daily cron jobs (fast - only OHLC + features)
run_daily_update(api_key, tickers)

# For weekly jobs (full sync including financials)
run_weekly_full_sync(api_key, tickers)
```

## Key Features

### 1. Atomic Writes

All saves use temporary files + rename to prevent corruption:

```python
# Write to temp
df.to_parquet('/tmp/xyz123.parquet')

# Atomic rename (POSIX guarantee)
shutil.move('/tmp/xyz123.parquet', 'data/raw_prices/6758.parquet')
```

### 2. Progress Tracking

Uses `tqdm` for real-time progress:

```
Processing stocks: 60%|██████    | 3/5 [00:15<00:10, 5.2s/stock]
```

### 3. Error Isolation

If one stock fails, others continue:

```python
ETL Pipeline Summary
====================
Total:      5
Successful: 4 (80.0%)
Failed:     1 (20.0%)

Failed Tickers:
  - 6861: No data returned from API
```

### 4. Detailed Reports

Every batch run generates a JSON summary:

```json
{
  "total": 5,
  "successful": 4,
  "failed": 1,
  "timestamp": "2026-01-08T14:30:52",
  "results": [...]
}
```

## Migration from Old Structure

If you have existing data in `./data/{code}_ohlc.parquet`:

```python
from pathlib import Path
import shutil

old_files = Path('./data').glob('*_ohlc.parquet')
new_dir = Path('./data/raw_prices')
new_dir.mkdir(exist_ok=True)

for old_file in old_files:
    # Rename 6758_ohlc.parquet → 6758.parquet
    new_name = old_file.stem.replace('_ohlc', '') + '.parquet'
    shutil.move(old_file, new_dir / new_name)
```

## Performance Tips

1. **Rate Limiting:** System automatically respects 60 req/min limit
2. **Parallel Processing:** NOT recommended (would exceed rate limit)
3. **Cold Start:** First run takes ~1 min per stock (5 years of data)
4. **Incremental:** Daily updates take ~2 seconds per stock

## Troubleshooting

### "No data returned from API"

- Stock code might be delisted
- API might not have history for that ticker
- Check J-Quants dashboard for ticker availability

### "Insufficient data for indicators"

- Need minimum 200 rows for EMA-200
- Wait for more data accumulation or reduce EMA periods

### Files corrupted after crash

- Shouldn't happen! Atomic writes prevent this
- If it does, delete the corrupt file and re-run

## Next Steps

1. **Cloud Migration:** Replace `pathlib` with `boto3` for S3 storage
2. **Scheduling:** Add cron jobs for daily/weekly updates
3. **Monitoring:** Integrate with Datadog/Prometheus
4. **Data Quality:** Add validation checks (missing dates, outliers)
