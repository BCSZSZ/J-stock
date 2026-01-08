# J-Stock-Analyzer

## Overview

J-Stock-Analyzer is a production-grade Python application for analyzing Japanese stocks using the J-Quants API V2. It implements:

- **Incremental Data Updates**: Smart caching with Parquet files to minimize API usage
- **Technical Analysis**: EMA, RSI, MACD, ATR indicators via `pandas_ta`
- **Market Context**: Foreign investor flows, TOPIX correlation, earnings calendar
- **LLM-Ready Output**: Structured prompts for Gemini/GPT trading decisions

## Architecture

### Design Pattern

```
Client Layer (API) → Data Manager (Business Logic) → Storage (Parquet)
```

### Tech Stack

- **Language**: Python 3.10+
- **API**: J-Quants API V2 (via `requests`)
- **Data Processing**: `pandas`, `pandas_ta`
- **Storage**: Local Parquet files (S3-ready design)
- **Rate Limiting**: 60 req/min (Light Plan compliance)

## Project Structure

```
j-stock-analyzer/
├── src/
│   ├── client/
│   │   ├── __init__.py
│   │   └── jquants_client.py      # J-Quants API V2 wrapper
│   ├── data/
│   │   ├── __init__.py
│   │   └── stock_data_manager.py  # Core business logic
│   ├── analysis/
│   │   ├── __init__.py
│   │   └── technical_indicators.py
│   ├── utils/
│   │   ├── __init__.py
│   │   └── helpers.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   └── main.py                     # Entry point
├── data/                           # Auto-created Parquet storage
├── tests/
│   ├── __init__.py
│   ├── test_stock_data_manager.py
│   └── test_technical_indicators.py
├── .env.example
├── requirements.txt
├── setup.py
└── README.md
```

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/j-stock-analyzer.git
cd j-stock-analyzer
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API Key

Create a `.env` file in the root directory:

```bash
cp .env.example .env
```

Edit `.env` and add your J-Quants API key:

```
JQUANTS_API_KEY=your_actual_api_key_here
```

**Get your API key**: Sign up at [JPX J-Quants](https://jpx-jquants.com/)

## Usage

### Basic Example

```bash
python src/main.py
```

This will:

1. Fetch/update data for Sony (6758) and Toyota (7203)
2. Calculate technical indicators
3. Generate structured analysis prompts

### Programmatic Usage

```python
from src.data.stock_data_manager import StockDataManager
import os

# Initialize
manager = StockDataManager(api_key=os.getenv('JQUANTS_API_KEY'))

# Generate analysis prompt
prompt = manager.generate_llm_prompt('6758')  # Sony
print(prompt)
```

### Sample Output

```
# Input Data
- **Ticker:** 6758
- **Price:** ¥12,450.00
- **Trend:** Above EMA200 (Price: 12450.00, EMA200: 11800.00)

## 1. Market Context (The Dice)
- **Foreign Investors (Weekly):** ¥1,234,567,890 (Buying)
- **TOPIX Correlation:** Strong (0.78)
- **Next Earnings Date:** 2026-02-10 (WARNING: 33 days left)

## 2. Technicals
- **RSI:** 62.34
- **MACD:** 0.0123

## 3. Fundamentals
- **Op. Profit:** ¥890,000M
```

## Key Features

### 1. Incremental Updates

- **Cold Start**: Fetches 2 years of historical data
- **Incremental**: Only fetches new data since last update
- **Deduplication**: Automatic handling of overlapping data

### 2. Five Critical Datasets

| Dataset           | Endpoint                         | Purpose              |
| ----------------- | -------------------------------- | -------------------- |
| Daily Bars        | `/v2/equities/bars/daily`        | OHLC price data      |
| Investor Types    | `/v2/equities/investor-types`    | Foreign/Retail flows |
| Earnings Calendar | `/v2/equities/earnings-calendar` | Risk event dates     |
| TOPIX Index       | `/v2/indices/bars/daily/topix`   | Market correlation   |
| Financial Summary | `/v2/fins/summary`               | Fundamentals check   |

### 3. Technical Indicators

- **EMA**: 20, 50, 200-period
- **RSI**: 14-period
- **MACD**: 12/26/9 configuration
- **ATR**: 14-period volatility

### 4. Rate Limiting

- Automatic 1-second delays between requests
- Retry logic for 429 (Too Many Requests) errors
- Graceful degradation on missing data

## Data Storage

### Parquet Files

Data is stored in `./data/` with naming convention:

- OHLC: `{code}_ohlc.parquet`
- Columns: `Date`, `Open`, `High`, `Low`, `Close`, `Volume`

### Why Parquet?

- **Fast**: Columnar format optimized for analytics
- **Compact**: 10x smaller than CSV
- **S3-Ready**: Can easily migrate to cloud storage

## Development

### Running Tests

```bash
pytest tests/
```

### Code Standards

- ✅ Type hints on all methods
- ✅ Docstrings explaining logic
- ✅ Error handling with logging
- ✅ PEP 8 compliant

### Extending the System

To add new indicators:

```python
# In stock_data_manager.py -> add_indicators()
df['YOUR_INDICATOR'] = ta.your_function(df['Close'])
```

To add new data sources:

```python
# In jquants_client.py
def get_new_endpoint(self, params):
    return self._make_request('/v2/new/endpoint', params)
```

## Troubleshooting

### "No data returned for {code}"

- Check if stock code is correct (e.g., '6758' not 'SONY')
- Verify API key is valid
- Check if market is open (data lags by 1 day)

### "Rate limit hit (429)"

- System will auto-retry after 5 seconds
- Consider reducing number of concurrent tickers

### "Investor data not available"

- This is normal - data is weekly and may lag
- System handles gracefully with "N/A" fallback

## Roadmap

- [ ] Add Bollinger Bands indicator
- [ ] Implement screener for multiple stocks
- [ ] Add S3 storage backend
- [ ] Create Streamlit dashboard
- [ ] Integrate Gemini API for automated trading signals

## License

MIT License

## Contributing

Pull requests welcome! Please ensure tests pass and follow PEP 8.

## Contact

For questions about J-Quants API: https://jpx-jquants.com/

```
python src/main.py
```

This will initialize the `StockDataManager`, fetch data for the specified tickers, add technical indicators, and print the formatted prompts.

## Contributing

Contributions are welcome! Please submit a pull request or open an issue for any enhancements or bug fixes.

## License

This project is licensed under the MIT License. See the LICENSE file for details.
