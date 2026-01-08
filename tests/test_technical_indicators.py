from unittest import TestCase
import pandas as pd
from src.data.stock_data_manager import StockDataManager

class TestTechnicalIndicators(TestCase):
    def setUp(self):
        self.manager = StockDataManager(email='test@example.com', password='password')

    def test_add_indicators(self):
        # Create a sample DataFrame
        data = {
            'date': pd.date_range(start='2022-01-01', periods=5),
            'close': [100, 102, 101, 105, 107]
        }
        df = pd.DataFrame(data)

        # Add indicators
        df_with_indicators = self.manager.add_indicators(df)

        # Check if indicators are added (this will depend on the actual implementation)
        self.assertIn('EMA', df_with_indicators.columns)
        self.assertIn('RSI', df_with_indicators.columns)
        self.assertIn('MACD', df_with_indicators.columns)
        self.assertIn('ATR', df_with_indicators.columns)

    def test_merge_data(self):
        # Create two sample DataFrames
        existing_data = pd.DataFrame({
            'date': pd.date_range(start='2022-01-01', periods=3),
            'close': [100, 102, 101]
        })
        new_data = pd.DataFrame({
            'date': pd.date_range(start='2022-01-02', periods=3),
            'close': [102, 105, 107]
        })

        # Merge data
        merged_data = self.manager.merge_data(new_data, existing_data)

        # Check if the merged data is correct
        self.assertEqual(len(merged_data), 5)  # Should have 5 unique entries
        self.assertTrue((merged_data['date'].is_unique))  # Dates should be unique

    # Additional tests can be added here for other functionalities
