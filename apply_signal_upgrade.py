import re

def patch(path, old, new, label):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    count = content.count(old)
    if count != 1:
        print(f"SKIP [{path}] {label}: found {count} matches, expected 1")
        return content, False
    content = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"OK   [{path}] {label}")
    return content, True

# ---------------------------------------------------------------- indicators.py
old_ind = '''def add_indicators(candles):
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
    return out'''

new_ind = '''def adx(candles, period=14):
    """Average Directional Index (Wilder). Returns (adx, plus_di, minus_di).
    ADX measures trend STRENGTH, not direction. High ADX = a real trend worth
    trusting momentum/breakout signals on. Low ADX = choppy/sideways, where
    those same signals are much less reliable."""
    high, low, close = candles["high"], candles["low"], candles["close"]
    n = len(close)
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    for i in range(n):
        if i == 0:
            tr[i] = float(high[i]) - float(low[i])
            continue
        up_move = float(high[i]) - float(high[i - 1])
        down_move = float(low[i - 1]) - float(low[i])
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
        h, l, pc = float(high[i]), float(low[i]), float(close[i - 1])
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr_s = _wilder(tr, period)
    plus_dm_s = _wilder(plus_dm, period)
    minus_dm_s = _wilder(minus_dm, period)
    plus_di, minus_di, dx = [], [], []
    for a, pdm, mdm in zip(atr_s, plus_dm_s, minus_dm_s):
        if _isnan(a) or a == 0:
            plus_di.append(NAN); minus_di.append(NAN); dx.append(NAN)
            continue
        pdi = 100.0 * pdm / a
        mdi = 100.0 * mdm / a
        plus_di.append(pdi); minus_di.append(mdi)
        denom = pdi + mdi
        dx.append(0.0 if denom == 0 else 100.0 * abs(pdi - mdi) / denom)
    adx_line = _wilder(dx, period)
    return adx_line, plus_di, minus_di


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
    adx_line, plus_di, minus_di = adx(out, 14)
    out["adx"] = adx_line
    out["plus_di"] = plus_di
    out["minus_di"] = minus_di
    return out'''

patch("indicators.py", old_ind, new_ind, "add ADX")

# ------------------------------------------------------------------ strategy.py
old_top = '''import math

import config
import data as market
import indicators as ind
import patterns as pat


def _isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))'''

new_top = '''import math

import config
import data as market
import indicators as ind
import patterns as pat


def _isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


_HTF_MAP = {
    "1m": "1h", "3m": "1h", "5m": "4h", "15m": "4h", "30m": "4h",
    "1h": "4h", "2h": "1d", "4h": "1d", "6h": "1d", "12h": "1d", "1d": "1w",
}


def _htf_trend(coin, timeframe):
    """Lightweight trend check on the next timeframe up, for confluence.
    Returns (trend, higher_timeframe_label) or (None, None) if unavailable."""
    htf = _HTF_MAP.get(timeframe)
    if not htf:
        return None, None
    try:
        c = market.get_klines(coin, interval=htf, limit=220)
        c = ind.add_indicators(c)
        return pat.detect_trend(c), htf
    except Exception:
        return None, None'''

patch("strategy.py", old_top, new_top, "add HTF confluence helper")

old_trend = '''    trend = pat.detect_trend(c)
    if trend == "uptrend":
        bull += 2; rationale.append("Uptrend: price above 200 EMA, 50 EMA rising")
    elif trend == "downtrend":
        bear += 2; rationale.append("Downtrend: price below 200 EMA, 50 EMA falling")
    else:
        rationale.append("No clear trend (range) - signals are lower confidence")'''

new_trend = '''    trend = pat.detect_trend(c)
    adx_val = c["adx"][-1]
    adx_threshold = getattr(config, "ADX_TREND_THRESHOLD", 20)
    strong_trend = (not _isnan(adx_val)) and adx_val >= adx_threshold
    if trend == "uptrend":
        pts = 2 if strong_trend else 1
        bull += pts
        note = "Uptrend: price above 200 EMA, 50 EMA rising"
        if not strong_trend:
            note += f" (ADX {adx_val:.0f} < {adx_threshold} - weak/choppy, discounted)"
        rationale.append(note)
    elif trend == "downtrend":
        pts = 2 if strong_trend else 1
        bear += pts
        note = "Downtrend: price below 200 EMA, 50 EMA falling"
        if not strong_trend:
            note += f" (ADX {adx_val:.0f} < {adx_threshold} - weak/choppy, discounted)"
        rationale.append(note)
    else:
        rationale.append("No clear trend (range) - signals are lower confidence")'''

patch("strategy.py", old_trend, new_trend, "gate trend score by ADX")

old_net = '''    bull, bear, rationale, trend = _score(c, sr, patterns, breakout)
    net = bull - bear
    price = float(c["close"][-1])'''

new_net = '''    bull, bear, rationale, trend = _score(c, sr, patterns, breakout)

    base_net = bull - bear
    htf_trend, htf_label = _htf_trend(coin, timeframe)
    if htf_trend and htf_label:
        if htf_trend == "uptrend" and base_net > 0:
            bull += 2; rationale.append(f"Higher timeframe ({htf_label}) confirms uptrend - confluence")
        elif htf_trend == "downtrend" and base_net < 0:
            bear += 2; rationale.append(f"Higher timeframe ({htf_label}) confirms downtrend - confluence")
        elif htf_trend == "uptrend" and base_net < 0:
            bear = max(0, bear - 2); rationale.append(f"Higher timeframe ({htf_label}) is uptrend - fighting the bigger trend, lower conviction")
        elif htf_trend == "downtrend" and base_net > 0:
            bull = max(0, bull - 2); rationale.append(f"Higher timeframe ({htf_label}) is downtrend - fighting the bigger trend, lower conviction")
        elif htf_trend == "range":
            rationale.append(f"Higher timeframe ({htf_label}) is ranging - no extra confluence")

    net = bull - bear
    price = float(c["close"][-1])'''

patch("strategy.py", old_net, new_net, "add HTF confluence to scoring")

old_ret = '''        "bull": bull,
        "bear": bear,
        "score": net,
        "direction": direction,'''

new_ret = '''        "bull": bull,
        "bear": bear,
        "htf_trend": htf_trend,
        "htf_timeframe": htf_label,
        "score": net,
        "direction": direction,'''

patch("strategy.py", old_ret, new_ret, "expose HTF trend in output")

print("Done.")
