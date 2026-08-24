"""
patterns.py
-----------
Reads chart *structure* from candle data:
  - swing highs / lows
  - nearest support & resistance to the current price
  - trend classification (uptrend / downtrend / range)
  - common candlestick patterns on the most recent candle(s)
  - breakouts of support / resistance

These are heuristics. They describe what the chart is doing right now; they do
NOT predict the future. They feed the signal engine in strategy.py.
"""

import pandas as pd


def find_swings(df: pd.DataFrame, left: int = 3, right: int = 3):
    """Return (swing_high_indices, swing_low_indices)."""
    highs, lows = [], []
    h, l = df["high"].values, df["low"].values
    n = len(df)
    for i in range(left, n - right):
        window_h = h[i - left:i + right + 1]
        window_l = l[i - left:i + right + 1]
        if h[i] == window_h.max() and (window_h == h[i]).sum() == 1:
            highs.append(i)
        if l[i] == window_l.min() and (window_l == l[i]).sum() == 1:
            lows.append(i)
    return highs, lows


def support_resistance(df: pd.DataFrame, lookback: int = 150):
    """
    Find the nearest support (below price) and resistance (above price)
    from recent swing points. Returns a dict; values may be None.
    """
    recent = df.tail(lookback).reset_index(drop=True)
    highs, lows = find_swings(recent)
    price = float(recent["close"].iloc[-1])

    swing_high_prices = [float(recent["high"].iloc[i]) for i in highs]
    swing_low_prices = [float(recent["low"].iloc[i]) for i in lows]

    resistances = sorted(p for p in swing_high_prices if p > price)
    supports = sorted((p for p in swing_low_prices if p < price), reverse=True)

    return {
        "price": price,
        "nearest_resistance": resistances[0] if resistances else None,
        "nearest_support": supports[0] if supports else None,
        "all_resistances": resistances[:5],
        "all_supports": supports[:5],
    }


def detect_trend(df: pd.DataFrame) -> str:
    """Classify the trend using EMA alignment and slope."""
    last = df.iloc[-1]
    if any(pd.isna(last.get(c)) for c in ("ema50", "ema200")):
        return "unknown"
    ema50_now = last["ema50"]
    ema50_prev = df["ema50"].iloc[-10] if len(df) >= 10 else ema50_now
    rising = ema50_now > ema50_prev
    falling = ema50_now < ema50_prev

    if last["ema50"] > last["ema200"] and last["close"] > last["ema200"] and rising:
        return "uptrend"
    if last["ema50"] < last["ema200"] and last["close"] < last["ema200"] and falling:
        return "downtrend"
    return "range"


def candlestick_patterns(df: pd.DataFrame):
    """
    Inspect the most recent candle(s). Returns a list of (name, bias) tuples,
    bias in {"bullish", "bearish", "neutral"}.
    """
    out = []
    if len(df) < 2:
        return out
    c = df.iloc[-1]
    p = df.iloc[-2]

    o, cl, hi, lo = c["open"], c["close"], c["high"], c["low"]
    body = abs(cl - o)
    rng = hi - lo
    if rng <= 0:
        return out
    upper_wick = hi - max(o, cl)
    lower_wick = min(o, cl) - lo

    # Doji - indecision
    if body <= 0.1 * rng:
        out.append(("Doji", "neutral"))

    # Hammer - potential bullish reversal
    if lower_wick >= 2 * body and upper_wick <= body and body > 0:
        out.append(("Hammer", "bullish"))

    # Shooting star - potential bearish reversal
    if upper_wick >= 2 * body and lower_wick <= body and body > 0:
        out.append(("Shooting Star", "bearish"))

    # Engulfing - momentum reversal (compare with previous candle body)
    p_bull = p["close"] > p["open"]
    p_bear = p["close"] < p["open"]
    c_bull = cl > o
    c_bear = cl < o
    if c_bull and p_bear and cl >= p["open"] and o <= p["close"]:
        out.append(("Bullish Engulfing", "bullish"))
    if c_bear and p_bull and o >= p["close"] and cl <= p["open"]:
        out.append(("Bearish Engulfing", "bearish"))

    return out


def detect_breakout(df: pd.DataFrame, lookback: int = 150):
    """
    Detect a fresh breakout/breakdown on the latest candle: did price close
    across a prior swing level this candle? Returns "breakout_up",
    "breakdown", or None.

    Note: levels are derived from confirmed swing points (not the price-relative
    nearest S/R), because the instant price breaks a resistance that level would
    otherwise be re-classified as support and the check would never fire.
    """
    if len(df) < 12:
        return None
    recent = df.tail(lookback).reset_index(drop=True)
    highs, lows = find_swings(recent)
    res_levels = [float(recent["high"].iloc[i]) for i in highs]
    sup_levels = [float(recent["low"].iloc[i]) for i in lows]
    last_close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])
    for r in res_levels:
        if prev_close <= r < last_close:
            return "breakout_up"
    for s in sup_levels:
        if prev_close >= s > last_close:
            return "breakdown"
    return None
