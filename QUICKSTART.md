# Quick Start Guide

## Setup (3 minutes)

### Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 2: Get J-Quants API Key

1. Sign up at https://jpx-jquants.com/
2. Navigate to your profile → API Key
3. Copy your API key

### Step 3: Configure Environment

```bash
# Create .env file
cp .env.example .env

# Edit .env and paste your API key
# JQUANTS_API_KEY=your_actual_key_here
```

### Step 4: Run Test

```bash
python src/main.py
```

## Expected Output

```
2026-01-08 - root - INFO - Initializing Stock Data Manager...
============================================================
Processing 6758
============================================================
2026-01-08 - root - INFO - Cold start: Fetching 2 years of data for 6758
2026-01-08 - root - INFO - Saved 500 rows to data/6758_ohlc.parquet

# Input Data
- **Ticker:** 6758
- **Price:** ¥12,450.00
- **Trend:** Above EMA200 (Price: 12450.00, EMA200: 11800.00)
...
```

## Verify Installation

```python
# test_setup.py
import pandas as pd
import pandas_ta as ta
import requests
from dotenv import load_dotenv
print("✅ All dependencies installed!")
```

## Troubleshooting

### ModuleNotFoundError

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### API Key Error

- Check `.env` file exists in project root
- Verify no extra spaces around the key
- Test key at https://jpx-jquants.com/

### No Data Returned

- Stock codes must be 4-digit strings (e.g., '6758', not '6758.T')
- Market data has ~1 day lag
- Check J-Quants system status

## Next Steps

1. Modify `tickers` list in `main.py`
2. Explore generated prompts
3. Integrate with Gemini API for automated decisions
