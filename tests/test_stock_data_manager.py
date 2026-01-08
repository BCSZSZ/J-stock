import unittest
from src.data.stock_data_manager import StockDataManager
import pandas as pd
from unittest.mock import patch, MagicMock

class TestStockDataManager(unittest.TestCase):

    @patch('src.data.stock_data_manager.Path')
    def setUp(self, mock_path):
        self.manager = StockDataManager(email='test@example.com', password='password')
        self.mock_path = mock_path

    @patch('src.data.stock_data_manager.StockDataManager.authenticate')
    def test_authenticate(self, mock_authenticate):
        mock_authenticate.return_value = True
        self.assertTrue(self.manager.client)

    @patch('src.data.stock_data_manager.StockDataManager.fetch_initial_data')
    def test_fetch_data_initial(self, mock_fetch_initial):
        mock_fetch_initial.return_value = pd.DataFrame({'date': [], 'price': []})
        data = self.manager.fetch_data('6758')
        self.assertTrue(isinstance(data, pd.DataFrame))

    @patch('src.data.stock_data_manager.StockDataManager.fetch_incremental_data')
    def test_fetch_data_incremental(self, mock_fetch_incremental):
        mock_fetch_incremental.return_value = pd.DataFrame({'date': [], 'price': []})
        self.mock_path.return_value.exists.return_value = True
        data = self.manager.fetch_data('7203')
        self.assertTrue(isinstance(data, pd.DataFrame))

    @patch('src.data.stock_data_manager.StockDataManager.save_data')
    def test_save_data(self, mock_save):
        df = pd.DataFrame({'date': ['2023-01-01'], 'price': [100]})
        self.manager.save_data(df, '6758')
        mock_save.assert_called_once()

    @patch('src.data.stock_data_manager.StockDataManager.add_indicators')
    def test_add_indicators(self, mock_add_indicators):
        df = pd.DataFrame({'date': ['2023-01-01'], 'price': [100]})
        self.manager.add_indicators(df)
        mock_add_indicators.assert_called_once()

if __name__ == '__main__':
    unittest.main()