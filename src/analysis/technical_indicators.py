def calculate_ema(df, period):
    """Calculate Exponential Moving Average (EMA)."""
    return df['close'].ewm(span=period, adjust=False).mean()

def calculate_rsi(df, period=14):
    """Calculate Relative Strength Index (RSI)."""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(df, short_window=12, long_window=26, signal_window=9):
    """Calculate Moving Average Convergence Divergence (MACD)."""
    short_ema = calculate_ema(df, short_window)
    long_ema = calculate_ema(df, long_window)
    macd = short_ema - long_ema
    signal = calculate_ema(pd.DataFrame(macd), signal_window)
    return macd, signal

def calculate_atr(df, period=14):
    """Calculate Average True Range (ATR)."""
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()