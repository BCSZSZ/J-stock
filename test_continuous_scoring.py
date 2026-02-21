#!/usr/bin/env python
"""Test the new continuous scoring logic"""

import pandas as pd
import numpy as np
from src.data.stock_data_manager import StockDataManager
from src.analysis.strategies.entry.macd_enhanced_fundamental import MACDEnhancedFundamentalStrategy
from src.analysis.signals import MarketData

# 选择一个监控股票
manager = StockDataManager()
stocks = ['1662', '1801', '3103']  # 几个测试股票

for stock_code in stocks:
    print(f'\n=== Testing {stock_code} ===')
    try:
        df = manager.load_stock_features(stock_code)
        if df is None or len(df) < 40:
            print(f'{stock_code}: Insufficient data ({len(df) if df is not None else 0} rows)')
            continue
        
        # Check if MACD_Hist is in columns
        if 'MACD_Hist' not in df.columns:
            print(f'{stock_code}: MACD_Hist not in columns')
            print(f'Columns: {list(df.columns)}')
            continue
        
        # 创建 MarketData 对象
        market_data = MarketData(
            ticker=stock_code,
            current_date=pd.to_datetime(df.iloc[-1].get('Date', pd.Timestamp.now())),
            df_features=df,
            df_trades=pd.DataFrame(),  # Not needed for this test
            df_financials=pd.DataFrame(),  # Not needed for this test
            metadata={'code': stock_code}
        )
        
        # 生成信号
        strategy = MACDEnhancedFundamentalStrategy()
        signal = strategy.generate_entry_signal(market_data)
        
        print(f'Signal: {signal.action}')
        print(f'Confidence: {signal.confidence:.3f}')
        print(f'Reasons (first 3):')
        for reason in signal.reasons[:3]:
            print(f'  - {reason}')
        if signal.metadata:
            print(f'Metadata: {signal.metadata}')
    except Exception as e:
        import traceback
        print(f'{stock_code}: Error - {str(e)[:100]}')
        traceback.print_exc()
