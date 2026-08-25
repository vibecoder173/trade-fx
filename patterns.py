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

Candles are a dict of equal-length lists (see indicators.py). No pandas/numpy.
"""

import math


def _isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def _tail(candles, n):
    """Return a new candle dict with only the last n rows of every column."""
    return {k: v[-n:] for k, v in candles.items()}


def find_swings(candles, left: int = 3, right: int = 3):
    """Return (swing_high_indices, swing_low_indices)."""
    highs, lows = [], []
    h, l = candles["high"], candles["low"]
    n = len(h)
    for i in range(left, n - right):
        window_h = h[i - left:i + right + 1]
        window_l = l[i - left:i + right + 1]
        if h[i] == max(window_h) and sum(1 for x in window_h if x == h[i]) == 1:
            highs.append(i)
        if l[i] == min(window_l) and sum(1 for x in window_l if x == l[i]) == 1:
            lows.append(i)
    return highs, lows


def support_resistance(candles, lookback: int = 150):
    """
    Find the nearest support (below price) and resistance (above price)
    from recent swing points. Returns a dict; values may be None.
    """
    recent = _tail(candles, lookback)
    highs, lows = find_swings(recent)
    price = float(recent["close"][-1])

    swing_high_prices = [float(recent["high"][i]) for i in highs]
    swing_low_prices = [float(recent["low"][i]) for i in lows]

    resistances = sorted(p for p in swing_high_prices if p > price)
    supports = sorted((p for p in swing_low_prices if p < price), reverse=True)

    return {
        "price": price,
        "nearest_resistance": resistances[0] if resistances else None,
        "nearest_support": supports[0] if supports else None,
        "all_resistances": resistances[:5],
        "all_supports": supports[:5],
    }


def detect_trend(candles) -> str:
    """Classify the trend using EMA alignment and slope."""
    close = candles["close"]
    ema50 = candles.get("ema50")
    ema200 = candles.get("ema200")
    if not close or ema50 is None or ema200 is None:
        return "unknown"
    if _isnan(ema50[-1]) or _isnan(ema200[-1]):
        return "unknown"

    ema50_now = ema50[-1]
    ema50_prev = ema50[-10] if len(ema50) >= 10 else ema50_now
    rising = ema50_now > ema50_prev
    falling = ema50_now < ema50_prev

    if ema50[-1] > ema200[-1] and close[-1] > ema200[-1] and rising:
        return "uptrend"
    if ema50[-1] < ema200[-1] and close[-1] < ema200[-1] and falling:
        return "downtrend"
    return "range"


def candlestick_patterns(candles):
    """
    Inspect the most recent candle(s). Returns a list of (name, bias) tuples,
    bias in {"bullish", "bearish", "neutral"}.
    """
    out = []
    close = candles["close"]
    if len(close) < 2:
        return out

    o, cl = candles["open"][-1], close[-1]
    hi, lo = candles["high"][-1], candles["low"][-1]
    prev_o, prev_cl = candles["open"][-2], close[-2]

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
    p_bull = prev_cl > prev_o
    p_bear = prev_cl < prev_o
    c_bull = cl > o
    c_bear = cl < o
    if c_bull and p_bear and cl >= prev_o and o <= prev_cl:
        out.append(("Bullish Engulfing", "bullish"))
    if c_bear and p_bull and o >= prev_cl and cl <= prev_o:
        out.append(("Bearish Engulfing", "bearish"))

    return out


def detect_breakout(candles, lookback: int = 150):
    """
    Detect a fresh breakout/breakdown on the latest candle: did price close
    across a prior swing level this candle? Returns "breakout_up",
    "breakdown", or None.

    Note: levels are derived from confirmed swing points (not the price-relative
    nearest S/R), because the instant price breaks a resistance that level would
    otherwise be re-classified as support and the check would never fire.
    """
    close = candles["close"]
    if len(close) < 12:
        return None
    recent = _tail(candles, lookback)
    highs, lows = find_swings(recent)
    res_levels = [float(recent["high"][i]) for i in highs]
    sup_levels = [float(recent["low"][i]) for i in lows]
    last_close = float(close[-1])
    prev_close = float(close[-2])
    for r in res_levels:
        if prev_close <= r < last_close:
            return "breakout_up"
    for s in sup_levels:
        if prev_close >= s > last_close:
            return "breakdown"
    return None
