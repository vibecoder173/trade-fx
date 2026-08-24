"""
indicators.py
-------------
Technical indicators, implemented with standard, widely-agreed formulas:
  - EMA / SMA
  - RSI (Wilder's smoothing)
  - MACD (12/26/9)
  - ATR (Wilder's smoothing)  -> used to size stop-losses to real volatility
  - Bollinger Bands (20, 2)

Each function takes a pandas Series/DataFrame and returns Series so they are
easy to test in isolation.
"""

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing (the classic RSI)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    out = 100.0 - (100.0 / (1.0 + rs))
    # When there are no losses, RSI is defined as 100.
    out = out.where(avg_loss != 0.0, 100.0)
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (macd_line, signal_line, histogram)."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder). Expects columns: high, low, close."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def bollinger(close: pd.Series, period: int = 20, mult: float = 2.0):
    """Return (upper, middle, lower) Bollinger Bands."""
    mid = sma(close, period)
    std = close.rolling(window=period).std(ddof=0)
    upper = mid + mult * std
    lower = mid - mult * std
    return upper, mid, lower


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Attach all indicator columns to a copy of the candle DataFrame."""
    out = df.copy()
    out["ema20"] = ema(out["close"], 20)
    out["ema50"] = ema(out["close"], 50)
    out["ema200"] = ema(out["close"], 200)
    out["rsi"] = rsi(out["close"], 14)
    macd_line, signal_line, hist = macd(out["close"])
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist
    out["atr"] = atr(out, 14)
    up, mid, low = bollinger(out["close"], 20, 2.0)
    out["bb_upper"], out["bb_mid"], out["bb_lower"] = up, mid, low
    out["vol_sma20"] = sma(out["volume"], 20)
    return out
