"""
indicators.py
-------------
Technical indicators in PURE PYTHON (no pandas / no numpy) so the bot installs
and runs anywhere with zero heavy dependencies — including a phone or tablet via
Termux, where pandas/numpy are painful to install.

Candle data is a plain dict of equal-length lists ("columns"):
    {"open_time": [...], "open": [...], "high": [...], "low": [...],
     "close": [...], "volume": [...]}
Indicator functions add more columns of the same length. Missing/warm-up values
are float('nan'), exactly like the previous pandas version produced.

Formulas match the standard definitions (and the earlier pandas implementation):
  - EMA / SMA
  - RSI (Wilder's smoothing)
  - MACD (12/26/9)
  - ATR (Wilder's smoothing)  -> used to size stop-losses to real volatility
  - Bollinger Bands (20, 2)
"""

import math

NAN = float("nan")


def _isnan(x):
    """True for None or a float NaN — our two 'missing value' markers."""
    return x is None or (isinstance(x, float) and math.isnan(x))


def ema(values, period):
    """Exponential moving average, matching pandas ewm(span=period,
    adjust=False).mean(): alpha = 2/(period+1), seeded at the first real value.
    Leading NaNs are carried until the first number appears."""
    alpha = 2.0 / (period + 1.0)
    out = []
    prev = None
    for v in values:
        if _isnan(v):
            out.append(NAN if prev is None else prev)
            continue
        v = float(v)
        prev = v if prev is None else (alpha * v + (1.0 - alpha) * prev)
        out.append(prev)
    return out


def sma(values, period):
    """Simple moving average, matching pandas rolling(window=period).mean():
    NaN until there are `period` values in the window."""
    out = []
    n = len(values)
    for i in range(n):
        if i < period - 1:
            out.append(NAN)
            continue
        window = values[i - period + 1:i + 1]
        if any(_isnan(w) for w in window):
            out.append(NAN)
        else:
            out.append(sum(float(w) for w in window) / period)
    return out


def _rolling_std(values, period, ddof=0):
    """Rolling population/sample standard deviation.
    Bollinger uses ddof=0 (divide by period), matching pandas .std(ddof=0)."""
    out = []
    n = len(values)
    for i in range(n):
        if i < period - 1:
            out.append(NAN)
            continue
        window = values[i - period + 1:i + 1]
        if any(_isnan(w) for w in window):
            out.append(NAN)
            continue
        window = [float(w) for w in window]
        m = sum(window) / period
        var = sum((w - m) ** 2 for w in window) / (period - ddof)
        out.append(math.sqrt(var))
    return out


def _wilder(values, period):
    """Wilder's smoothing == pandas ewm(alpha=1/period, min_periods=period,
    adjust=False).mean(). Seeds at the first real value; output stays NaN until
    `period` real observations have been seen."""
    alpha = 1.0 / period
    out = []
    state = None
    count = 0
    for v in values:
        if _isnan(v):
            out.append(NAN)
            continue
        v = float(v)
        state = v if state is None else ((1.0 - alpha) * state + alpha * v)
        count += 1
        out.append(state if count >= period else NAN)
    return out


def rsi(close, period=14):
    """Relative Strength Index using Wilder's smoothing (the classic RSI)."""
    n = len(close)
    if n == 0:
        return []
    delta = [NAN] + [float(close[i]) - float(close[i - 1]) for i in range(1, n)]
    gain = [NAN if _isnan(d) else max(d, 0.0) for d in delta]
    loss = [NAN if _isnan(d) else max(-d, 0.0) for d in delta]
    avg_gain = _wilder(gain, period)
    avg_loss = _wilder(loss, period)
    out = []
    for g, l in zip(avg_gain, avg_loss):
        if _isnan(g) or _isnan(l):
            out.append(NAN)
        elif l == 0.0:
            # No losses over the window -> RSI is defined as 100.
            out.append(100.0)
        else:
            rs = g / l
            out.append(100.0 - (100.0 / (1.0 + rs)))
    return out


def macd(close, fast=12, slow=26, signal=9):
    """Return (macd_line, signal_line, histogram)."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = [a - b for a, b in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal)
    hist = [a - b for a, b in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def atr(candles, period=14):
    """Average True Range (Wilder). Expects columns: high, low, close."""
    high, low, close = candles["high"], candles["low"], candles["close"]
    n = len(close)
    tr = []
    for i in range(n):
        h, l = float(high[i]), float(low[i])
        if i == 0:
            tr.append(abs(h - l))
        else:
            pc = float(close[i - 1])
            tr.append(max(abs(h - l), abs(h - pc), abs(l - pc)))
    return _wilder(tr, period)


def bollinger(close, period=20, mult=2.0):
    """Return (upper, middle, lower) Bollinger Bands."""
    mid = sma(close, period)
    std = _rolling_std(close, period, ddof=0)
    upper, lower = [], []
    for m, s in zip(mid, std):
        if _isnan(m) or _isnan(s):
            upper.append(NAN)
            lower.append(NAN)
        else:
            upper.append(m + mult * s)
            lower.append(m - mult * s)
    return upper, mid, lower


def add_indicators(candles):
    """Return a NEW candle dict (columns copied) with every indicator attached."""
    out = {k: list(v) for k, v in candles.items()}
    close = out["close"]
    out["ema20"] = ema(close, 20)
    out["ema50"] = ema(close, 50)
    out["ema200"] = ema(close, 200)
    out["rsi"] = rsi(close, 14)
    macd_line, signal_line, hist = macd(close)
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist
    out["atr"] = atr(out, 14)
    up, mid, low = bollinger(close, 20, 2.0)
    out["bb_upper"], out["bb_mid"], out["bb_lower"] = up, mid, low
    out["vol_sma20"] = sma(out["volume"], 20)
    return out
