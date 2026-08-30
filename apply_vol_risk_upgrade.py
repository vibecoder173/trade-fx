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

old_bb = '''    # Bollinger position (mean reversion)
    bb_lower, bb_upper = c["bb_lower"][-1], c["bb_upper"][-1]
    if not _isnan(bb_lower) and not _isnan(bb_upper):
        if close < bb_lower:
            bull += 1; rationale.append("Price below lower Bollinger Band (stretched down)")
        elif close > bb_upper:
            bear += 1; rationale.append("Price above upper Bollinger Band (stretched up)")

    # Candlestick patterns'''

new_bb = '''    # Bollinger position (mean reversion)
    bb_lower, bb_upper = c["bb_lower"][-1], c["bb_upper"][-1]
    if not _isnan(bb_lower) and not _isnan(bb_upper):
        if close < bb_lower:
            bull += 1; rationale.append("Price below lower Bollinger Band (stretched down)")
        elif close > bb_upper:
            bear += 1; rationale.append("Price above upper Bollinger Band (stretched up)")

    # Volume confirmation - a move on unusually high volume carries more weight
    vol, vol_avg = c["volume"][-1], c["vol_sma20"][-1]
    open_ = c["open"][-1]
    spike_mult = getattr(config, "VOLUME_SPIKE_MULT", 1.5)
    if not _isnan(vol_avg) and vol_avg > 0 and vol > spike_mult * vol_avg:
        ratio = vol / vol_avg
        if close > open_:
            bull += 1; rationale.append(f"Volume spike ({ratio:.1f}x avg) on an up candle - real buying pressure")
        elif close < open_:
            bear += 1; rationale.append(f"Volume spike ({ratio:.1f}x avg) on a down candle - real selling pressure")

    # Candlestick patterns'''

patch("strategy.py", old_bb, new_bb, "add volume confirmation")

old_plan = '''    plan = None
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
        plan["support_cap"] = sr.get("nearest_support")'''

new_plan = '''    plan = None
    strength_mult = {"strong": 1.5, "moderate": 1.15, "weak": 0.75}.get(_strength_label(net), 1.0)
    max_risk = getattr(config, "MAX_RISK_PCT", risk_pct * 2)
    scaled_risk_pct = min(risk_pct * strength_mult, max_risk)
    if direction == "LONG":
        atr_sl = price - config.ATR_SL_MULT * atr_val
        struct_sl = (sr["nearest_support"] * 0.998
                     if sr.get("nearest_support") else None)
        sl = min(atr_sl, struct_sl) if struct_sl else atr_sl
        plan = plan_trade(account, scaled_risk_pct, price, sl, rr)
        plan["base_risk_pct"] = risk_pct
        plan["resistance_cap"] = sr.get("nearest_resistance")
    elif direction == "SHORT":
        atr_sl = price + config.ATR_SL_MULT * atr_val
        struct_sl = (sr["nearest_resistance"] * 1.002
                     if sr.get("nearest_resistance") else None)
        sl = max(atr_sl, struct_sl) if struct_sl else atr_sl
        plan = plan_trade(account, scaled_risk_pct, price, sl, rr)
        plan["base_risk_pct"] = risk_pct
        plan["support_cap"] = sr.get("nearest_support")'''

patch("strategy.py", old_plan, new_plan, "scale risk % by signal strength")
print("Done.")
