from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import pandas as pd

from src.data.stock_data_manager import StockDataManager


class TestTechnicalIndicators(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = StockDataManager(data_root=self.temp_dir.name)

    def test_compute_features_adds_sbi_rsi_columns(self):
        code = "9999"
        raw_path = Path(self.temp_dir.name) / "raw_prices" / f"{code}.parquet"

        periods = 260
        dates = pd.date_range(start="2024-01-01", periods=periods, freq="B")
        closes = pd.Series(range(periods), dtype=float) * 0.8 + 100.0
        raw_df = pd.DataFrame(
            {
                "Date": dates,
                "Open": closes + 0.2,
                "High": closes + 1.0,
                "Low": closes - 1.0,
                "Close": closes,
                "Volume": 100000 + pd.Series(range(periods)) * 100,
            }
        )
        raw_df.to_parquet(raw_path, index=False)

        df_with_indicators = self.manager.compute_features(code, force_recompute=True)

        self.assertIn("EMA_20", df_with_indicators.columns)
        self.assertIn("RSI_9", df_with_indicators.columns)
        self.assertIn("RSI_14", df_with_indicators.columns)
        self.assertIn("RSI_22", df_with_indicators.columns)
        self.assertIn("RSI", df_with_indicators.columns)
        self.assertIn("MACD", df_with_indicators.columns)
        self.assertIn("ATR", df_with_indicators.columns)

        latest = df_with_indicators.iloc[-1]
        self.assertAlmostEqual(float(latest["RSI"]), float(latest["RSI_14"]), places=8)
