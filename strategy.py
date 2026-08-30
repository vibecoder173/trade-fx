"""
strategy.py
-----------
Turns raw data into (a) a transparent setup score and (b) a concrete trade plan
with entry, stop-loss, take-profit, and a risk-based position size.

IMPORTANT PHILOSOPHY
--------------------
The "score" is a weighted count of technical conditions that historically tend
to line up with a direction. It is NOT a probability of profit and it is NOT a
guarantee. Its real job is to stop you trading with no reason and to force every
idea through a risk-managed plan (fixed % risk, defined stop, minimum R:R).
Capital preservation first; being right second.

Candles are a dict of equal-length lists (see indicators.py). No pandas/numpy.
"""

import math

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
        return None, None


# ----------------------------------------------------------------------------
# formatting helpers
# ----------------------------------------------------------------------------
def fmt_price(p):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "n/a"
    p = float(p)
    if abs(p) >= 100:
        return f"{p:,.2f}"
    if abs(p) >= 1:
        return f"{p:,.4f}"
    if abs(p) >= 0.01:
        return f"{p:,.6f}"
    return f"{p:,.8f}"


# ----------------------------------------------------------------------------
# risk / position sizing  (used by /risk and by analyze)
# ----------------------------------------------------------------------------
def plan_trade(account: float, risk_pct: float, entry: float, sl: float,
               rr: float = None):
    """
    Core risk engine. Given how much you'll risk and where your stop is,
    return the position size and a take-profit at the chosen reward:risk.
    Works for both longs (sl < entry) and shorts (sl > entry).
    """
    rr = rr or config.DEFAULT_RR
    if entry <= 0 or account <= 0 or risk_pct <= 0:
        raise ValueError("account, entry and risk% must be positive numbers.")
    per_unit_risk = abs(entry - sl)
    if per_unit_risk == 0:
        raise ValueError("Stop-loss cannot equal the entry price.")

    is_long = sl < entry
    risk_amount = account * (risk_pct / 100.0)
    size = risk_amount / per_unit_risk           # units of the coin
    notional = size * entry                      # position value in quote (USDT)

    if is_long:
        tp = entry + rr * per_unit_risk
    else:
        tp = entry - rr * per_unit_risk

    leverage = notional / account if notional > account else 1.0

    return {
        "direction": "LONG" if is_long else "SHORT",
        "account": account,
        "risk_pct": risk_pct,
        "risk_amount": risk_amount,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": rr,
        "per_unit_risk": per_unit_risk,
        "size": size,
        "notional": notional,
        "leverage": leverage,
    }


# ----------------------------------------------------------------------------
# signal engine
# ----------------------------------------------------------------------------
def _score(c: dict, sr: dict, patterns, breakout):
    """Build a bull/bear score with a plain-English rationale for each point."""
    bull, bear, rationale = 0, 0, []

    trend = pat.detect_trend(c)
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
        rationale.append("No clear trend (range) - signals are lower confidence")

    ema50, ema200 = c["ema50"][-1], c["ema200"][-1]
    close = c["close"][-1]

    # Moving-average alignment
    if not _isnan(ema50) and not _isnan(ema200):
        if ema50 > ema200:
            bull += 1; rationale.append("50 EMA above 200 EMA (bullish structure)")
        else:
            bear += 1; rationale.append("50 EMA below 200 EMA (bearish structure)")

    # RSI
    rsi_val = c["rsi"][-1]
    if not _isnan(rsi_val):
        if rsi_val < 30:
            bull += 1; rationale.append(f"RSI {rsi_val:.0f} - oversold (bounce potential)")
        elif rsi_val > 70:
            bear += 1; rationale.append(f"RSI {rsi_val:.0f} - overbought (pullback risk)")
        else:
            rationale.append(f"RSI {rsi_val:.0f} - neutral")

    # MACD histogram
    hist = c["macd_hist"][-1]
    if not _isnan(hist):
        if hist > 0:
            bull += 1; rationale.append("MACD histogram positive (upward momentum)")
        elif hist < 0:
            bear += 1; rationale.append("MACD histogram negative (downward momentum)")

    # Bollinger position (mean reversion)
    bb_lower, bb_upper = c["bb_lower"][-1], c["bb_upper"][-1]
    if not _isnan(bb_lower) and not _isnan(bb_upper):
        if close < bb_lower:
            bull += 1; rationale.append("Price below lower Bollinger Band (stretched down)")
        elif close > bb_upper:
            bear += 1; rationale.append("Price above upper Bollinger Band (stretched up)")

    # Candlestick patterns
    for name, bias in patterns:
        if bias == "bullish":
            bull += 1; rationale.append(f"Candle: {name} (bullish)")
        elif bias == "bearish":
            bear += 1; rationale.append(f"Candle: {name} (bearish)")
        else:
            rationale.append(f"Candle: {name} (indecision)")

    # Breakouts
    if breakout == "breakout_up":
        bull += 2; rationale.append("Breakout above nearest resistance")
    elif breakout == "breakdown":
        bear += 2; rationale.append("Breakdown below nearest support")

    # Proximity to support / resistance
    price = sr["price"]
    sup, res = sr.get("nearest_support"), sr.get("nearest_resistance")
    if sup and abs(price - sup) / price < 0.015:
        bull += 1; rationale.append("Price sitting on support (bounce zone)")
    if res and abs(res - price) / price < 0.015:
        bear += 1; rationale.append("Price pressing into resistance")

    return bull, bear, rationale, trend


def _strength_label(net):
    a = abs(net)
    if a >= 6:
        return "strong"
    if a >= 4:
        return "moderate"
    if a >= 2:
        return "weak"
    return "flat"


def analyze(coin: str, timeframe: str = None,
            account: float = None, risk_pct: float = None,
            rr: float = None) -> dict:
    """Full pipeline for one coin: data -> indicators -> structure -> plan."""
    timeframe = timeframe or config.DEFAULT_TIMEFRAME
    account = account or config.DEFAULT_ACCOUNT
    risk_pct = risk_pct or config.DEFAULT_RISK_PCT
    rr = rr or config.DEFAULT_RR

    c = market.get_klines(coin, interval=timeframe)
    c = ind.add_indicators(c)
    sr = pat.support_resistance(c)
    patterns = pat.candlestick_patterns(c)
    breakout = pat.detect_breakout(c)

    bull, bear, rationale, trend = _score(c, sr, patterns, breakout)

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
    price = float(c["close"][-1])
    atr_last = c["atr"][-1]
    atr_val = float(atr_last) if not _isnan(atr_last) else price * 0.02
    rsi_last = c["rsi"][-1]

    if net >= 2:
        direction = "LONG"
    elif net <= -2:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    plan = None
    if direction == "LONG":
        atr_sl = price - config.ATR_SL_MULT * atr_val
        struct_sl = (sr["nearest_support"] * 0.998
                     if sr.get("nearest_support") else None)
        sl = min(atr_sl, struct_sl) if struct_sl else atr_sl
        plan = plan_trade(account, risk_pct, price, sl, rr)
        plan["resistance_cap"] = sr.get("nearest_resistance")
    elif direction == "SHORT":
        atr_sl = price + config.ATR_SL_MULT * atr_val
        struct_sl = (sr["nearest_resistance"] * 1.002
                     if sr.get("nearest_resistance") else None)
        sl = max(atr_sl, struct_sl) if struct_sl else atr_sl
        plan = plan_trade(account, risk_pct, price, sl, rr)
        plan["support_cap"] = sr.get("nearest_support")

    return {
        "coin": coin.upper(),
        "symbol": market.to_symbol(coin),
        "timeframe": timeframe,
        "source": getattr(market, "LAST_KLINE_SOURCE", None),
        "price": price,
        "trend": trend,
        "rsi": float(rsi_last) if not _isnan(rsi_last) else None,
        "atr": atr_val,
        "support": sr.get("nearest_support"),
        "resistance": sr.get("nearest_resistance"),
        "patterns": patterns,
        "breakout": breakout,
        "bull": bull,
        "bear": bear,
        "htf_trend": htf_trend,
        "htf_timeframe": htf_label,
        "score": net,
        "direction": direction,
        "strength": _strength_label(net),
        "rationale": rationale,
        "plan": plan,
    }
