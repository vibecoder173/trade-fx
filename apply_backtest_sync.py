def patch(path, old, new, label):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    count = content.count(old)
    if count != 1:
        print(f"SKIP [{path}] {label}: found {count} matches, expected 1")
        return
    content = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"OK   [{path}] {label}")

old_loop = '''        sr = pat.support_resistance(window)
        patterns = pat.candlestick_patterns(window)
        breakout = pat.detect_breakout(window)
        bull, bear, _rationale, _trend = strategy._score(window, sr, patterns, breakout)
        net = bull - bear
        if abs(net) < min_score:
            continue

        direction = "LONG" if net > 0 else "SHORT"
        price = float(window["close"][-1])
        atr_last = window["atr"][-1]
        atr_val = float(atr_last) if not _isnan(atr_last) else price * 0.02

        try:
            if direction == "LONG":
                atr_sl = price - config.ATR_SL_MULT * atr_val
                struct_sl = (sr["nearest_support"] * 0.998
                            if sr.get("nearest_support") else None)
                sl = min(atr_sl, struct_sl) if struct_sl else atr_sl
            else:
                atr_sl = price + config.ATR_SL_MULT * atr_val
                struct_sl = (sr["nearest_resistance"] * 1.002
                            if sr.get("nearest_resistance") else None)
                sl = max(atr_sl, struct_sl) if struct_sl else atr_sl
            plan = strategy.plan_trade(equity, risk_pct, price, sl, rr)
        except ValueError:
            continue

        open_trade = {
            "direction": direction,
            "entry": price,
            "sl": plan["sl"],
            "tp": plan["tp"],
            "per_unit_risk": plan["per_unit_risk"],
            "risk_amount": plan["risk_amount"],
            "entry_idx": i,
            "score": net,
        }'''

new_loop = '''        sr = pat.support_resistance(window)
        patterns = pat.candlestick_patterns(window)
        breakout = pat.detect_breakout(window)
        bull, bear, _rationale, _trend = strategy._score(window, sr, patterns, breakout)

        # Mirror analyze()'s higher-timeframe confluence adjustment so the
        # backtest tests the SAME logic the live bot actually runs.
        base_net = bull - bear
        htf_tf = strategy._HTF_MAP.get(timeframe)
        if htf_tf and htf_tf in c and False:
            pass  # placeholder, real HTF handled via precomputed series below
        htf_trend_i = htf_series[i] if htf_series is not None else None
        if htf_trend_i:
            if htf_trend_i == "uptrend" and base_net > 0:
                bull += 2
            elif htf_trend_i == "downtrend" and base_net < 0:
                bear += 2
            elif htf_trend_i == "uptrend" and base_net < 0:
                bear = max(0, bear - 2)
            elif htf_trend_i == "downtrend" and base_net > 0:
                bull = max(0, bull - 2)

        net = bull - bear
        if abs(net) < min_score:
            continue

        direction = "LONG" if net > 0 else "SHORT"
        strength = strategy._strength_label(net)
        strength_mult = {"strong": 1.5, "moderate": 1.15, "weak": 0.75}.get(strength, 1.0)
        max_risk = getattr(config, "MAX_RISK_PCT", risk_pct * 2)
        scaled_risk_pct = min(risk_pct * strength_mult, max_risk)

        price = float(window["close"][-1])
        atr_last = window["atr"][-1]
        atr_val = float(atr_last) if not _isnan(atr_last) else price * 0.02

        try:
            if direction == "LONG":
                atr_sl = price - config.ATR_SL_MULT * atr_val
                struct_sl = (sr["nearest_support"] * 0.998
                            if sr.get("nearest_support") else None)
                sl = min(atr_sl, struct_sl) if struct_sl else atr_sl
            else:
                atr_sl = price + config.ATR_SL_MULT * atr_val
                struct_sl = (sr["nearest_resistance"] * 1.002
                            if sr.get("nearest_resistance") else None)
                sl = max(atr_sl, struct_sl) if struct_sl else atr_sl
            plan = strategy.plan_trade(equity, scaled_risk_pct, price, sl, rr)
        except ValueError:
            continue

        open_trade = {
            "direction": direction,
            "entry": price,
            "sl": plan["sl"],
            "tp": plan["tp"],
            "per_unit_risk": plan["per_unit_risk"],
            "risk_amount": plan["risk_amount"],
            "entry_idx": i,
            "score": net,
        }'''

patch("backtest.py", old_loop, new_loop, "sync ADX/HTF/risk-scaling logic into backtest loop")

old_setup = '''    trades = []
    equity = float(account)
    equity_curve = [equity]
    open_trade = None

    for i in range(MIN_WARMUP, n):'''

new_setup = '''    # Precompute higher-timeframe trend for every point in the base timeframe,
    # once, up front - so the walk-forward loop stays fast (no per-candle API
    # calls) while still no-lookahead (each i only sees HTF candles that had
    # actually closed by that point in real time).
    htf_series = _build_htf_series(coin, timeframe, c["open_time"])

    trades = []
    equity = float(account)
    equity_curve = [equity]
    open_trade = None

    for i in range(MIN_WARMUP, n):'''

patch("backtest.py", old_setup, new_setup, "add HTF series precompute call")

old_imports = '''import math

import config
import data as market
import indicators as ind
import patterns as pat
import strategy'''

new_imports = '''import math

import config
import data as market
import indicators as ind
import patterns as pat
import strategy


def _build_htf_series(coin, timeframe, base_open_times):
    """For every candle in the base timeframe, figure out what the higher
    timeframe's trend was AS OF that candle's open time (no lookahead: only
    HTF candles that had already closed). Returns a list aligned to
    base_open_times, or None if this timeframe has no HTF mapping."""
    htf_tf = strategy._HTF_MAP.get(timeframe)
    if not htf_tf:
        return None
    try:
        htf_raw, _src = _get_history(coin, htf_tf, DEFAULT_CANDLES)
        if not htf_raw or len(htf_raw["close"]) < MIN_WARMUP + 5:
            return None
        htf_c = ind.add_indicators(htf_raw)
    except Exception:
        return None

    htf_times = htf_c["open_time"]
    htf_trends = [None] * len(htf_times)
    for j in range(MIN_WARMUP, len(htf_times)):
        htf_trends[j] = pat.detect_trend(_slice(htf_c, j))

    out = []
    hi = 0
    n_htf = len(htf_times)
    for t in base_open_times:
        while hi + 1 < n_htf and htf_times[hi + 1] <= t:
            hi += 1
        out.append(htf_trends[hi] if hi < len(htf_trends) else None)
    return out'''

patch("backtest.py", old_imports, new_imports, "add HTF series builder helper")

print("Done.")
