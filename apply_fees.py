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

old_sig = '''def run_backtest(coin, timeframe=None, account=1000.0, risk_pct=1.0,
                  rr=2.0, min_score=4, candles=None):'''
new_sig = '''def run_backtest(coin, timeframe=None, account=1000.0, risk_pct=1.0,
                  rr=2.0, min_score=4, candles=None,
                  fee_pct=None, slippage_pct=None):'''
patch("backtest.py", old_sig, new_sig, "add fee/slippage params")

old_setup2 = '''    timeframe = timeframe or config.DEFAULT_TIMEFRAME
    candles = candles or DEFAULT_CANDLES'''
new_setup2 = '''    timeframe = timeframe or config.DEFAULT_TIMEFRAME
    candles = candles or DEFAULT_CANDLES
    fee_pct = getattr(config, "BACKTEST_FEE_PCT", 0.1) if fee_pct is None else fee_pct
    slippage_pct = (getattr(config, "BACKTEST_SLIPPAGE_PCT", 0.05)
                     if slippage_pct is None else slippage_pct)
    round_trip_cost_pct = (fee_pct * 2 + slippage_pct * 2) / 100.0'''
patch("backtest.py", old_setup2, new_setup2, "compute round-trip cost pct")

old_exit = '''            if hit_sl or hit_tp:
                exit_price = open_trade["sl"] if hit_sl else open_trade["tp"]
                if open_trade["direction"] == "LONG":
                    r_mult = (exit_price - open_trade["entry"]) / open_trade["per_unit_risk"]
                else:
                    r_mult = (open_trade["entry"] - exit_price) / open_trade["per_unit_risk"]
                pnl = r_mult * open_trade["risk_amount"]
                equity += pnl'''
new_exit = '''            if hit_sl or hit_tp:
                exit_price = open_trade["sl"] if hit_sl else open_trade["tp"]
                if open_trade["direction"] == "LONG":
                    r_mult = (exit_price - open_trade["entry"]) / open_trade["per_unit_risk"]
                else:
                    r_mult = (open_trade["entry"] - exit_price) / open_trade["per_unit_risk"]
                pnl = r_mult * open_trade["risk_amount"]
                # Fees + slippage, charged on both entry and exit, on the full
                # position notional - not just the risked amount.
                cost = open_trade["notional"] * round_trip_cost_pct
                pnl -= cost
                equity += pnl'''
patch("backtest.py", old_exit, new_exit, "deduct fees/slippage from pnl")

old_open = '''        open_trade = {
            "direction": direction,
            "entry": price,
            "sl": plan["sl"],
            "tp": plan["tp"],
            "per_unit_risk": plan["per_unit_risk"],
            "risk_amount": plan["risk_amount"],
            "entry_idx": i,
            "score": net,
        }'''
new_open = '''        open_trade = {
            "direction": direction,
            "entry": price,
            "sl": plan["sl"],
            "tp": plan["tp"],
            "per_unit_risk": plan["per_unit_risk"],
            "risk_amount": plan["risk_amount"],
            "notional": plan["notional"],
            "entry_idx": i,
            "score": net,
        }'''
patch("backtest.py", old_open, new_open, "carry notional for fee calc")

old_return = '''    metrics = _compute_metrics(trades, float(account), equity_curve)
    return {
        "coin": coin.upper(),
        "timeframe": timeframe,
        "candles_used": n,
        "source": source_note,'''
new_return = '''    metrics = _compute_metrics(trades, float(account), equity_curve)
    return {
        "coin": coin.upper(),
        "timeframe": timeframe,
        "candles_used": n,
        "fee_pct": fee_pct,
        "slippage_pct": slippage_pct,
        "source": source_note,'''
patch("backtest.py", old_return, new_return, "expose fee settings in result")

old_fmt = '''    lines = [
        f"<b>📊 Backtest — {_html.escape(result['coin'])}/USDT · {_html.escape(result['timeframe'])}</b>",
        f"<i>{result['candles_used']} candles"
        + (f" via {_html.escape(result['source'])}" if result.get("source") else "") + "</i>",
        "",
    ]'''
new_fmt = '''    lines = [
        f"<b>📊 Backtest — {_html.escape(result['coin'])}/USDT · {_html.escape(result['timeframe'])}</b>",
        f"<i>{result['candles_used']} candles"
        + (f" via {_html.escape(result['source'])}" if result.get("source") else "") + "</i>",
        f"<i>Fees modeled: {result.get('fee_pct', 0):.2f}% + "
        f"{result.get('slippage_pct', 0):.2f}% slippage, round-trip</i>",
        "",
    ]'''
patch("backtest.py", old_fmt, new_fmt, "show fee assumptions in report")
print("Done.")
