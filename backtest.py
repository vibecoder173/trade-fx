"""
backtest.py
-----------
Measures whether the strategy in strategy.py actually has an edge, using
real history instead of vibes.

How it works: fetch historical candles once, then walk forward one candle
at a time. At each point, run the SAME scoring pipeline analyze() uses
(strategy._score + pat.support_resistance/candlestick_patterns/detect_breakout)
on only the candles visible "as of" that point (no lookahead), and if a
signal fires, open a simulated trade using the SAME stop/target logic
analyze() uses. Walk forward candle-by-candle checking the trade's
high/low against its stop-loss and take-profit until one is hit.

Honest limitations (read before trusting the numbers):
  * Only one open trade at a time per run — no portfolio effects.
  * If a single candle's range touches BOTH the stop and the target, we
    conservatively assume the stop was hit first (can't know true intra-
    candle order without tick data). This slightly understates results.
  * No exchange fees or slippage are modeled yet — real results will be
    somewhat worse than what's reported here.
  * History depth: by default pulls up to ~3000 candles by paging Binance's
    klines endpoint backward in time (a single API call is capped at 1000).
    Falls back to whatever a single call returns (~1000) if Binance doesn't
    have the pair or paging fails partway — still runs, just on less data.
  * Past performance on this window is not a promise of future performance.
    Markets change regimes; an edge here can vanish going forward.
"""

import math

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
    return out

MIN_WARMUP = 210  # candles needed before ema200/atr/etc. are all warmed up
DEFAULT_CANDLES = 3000  # ~500 days on 4h, ~125 days on 1h, ~3000 days on 1d


def _isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def _slice(candles, i):
    """Everything up to and including index i — this is 'what you'd have known'
    if you were standing at that candle, no lookahead."""
    return {k: v[:i + 1] for k, v in candles.items()}


def _fetch_extended_klines(coin, timeframe, total):
    """
    Page Binance's klines endpoint backward in time to assemble more history
    than a single call allows (1000). Returns the same column-dict format as
    data.get_klines, or None if Binance doesn't have this pair/timeframe.
    Best-effort: if paging stops early (rate limit, thin history), returns
    whatever was collected rather than failing outright.
    """
    base, quote = market._split(coin)
    tf = market._norm_tf(timeframe)
    if tf not in market._CANON_SECONDS:
        return None

    all_rows = []
    end_time = None
    remaining = total
    attempts = 0
    while remaining > 0 and attempts < 30:
        attempts += 1
        limit = min(remaining, 1000)
        params = {"symbol": base + quote, "interval": tf, "limit": limit}
        if end_time is not None:
            params["endTime"] = end_time
        try:
            data = market._binance_get("/api/v3/klines", params)
        except Exception:
            break
        if not data:
            break
        all_rows = data + all_rows  # prepend — we're paging backward
        end_time = data[0][0] - 1   # next page ends right before this batch starts
        remaining -= len(data)
        if len(data) < limit:
            break  # exchange ran out of history before we did

    if not all_rows:
        return None
    rows = [(market._ms(r[0]), market._f(r[1]), market._f(r[2]),
             market._f(r[3]), market._f(r[4]), market._f(r[5])) for r in all_rows]
    return market._pack(rows, total)


def _get_history(coin, timeframe, candles):
    """Try for deep history via Binance paging first; fall back to a single
    call through the normal multi-exchange chain (capped ~1000) if that
    doesn't work for this pair."""
    try:
        ext = _fetch_extended_klines(coin, timeframe, candles)
        if ext and len(ext["close"]) >= MIN_WARMUP + 30:
            return ext, f"Binance (paged, {len(ext['close'])} candles)"
    except Exception:
        pass
    raw = market.get_klines(coin, interval=timeframe, limit=min(candles, 1000))
    src = getattr(market, "LAST_KLINE_SOURCE", None)
    return raw, f"{src} (single call, capped at 1000)" if src else None


def run_backtest(coin, timeframe=None, account=1000.0, risk_pct=1.0,
                  rr=2.0, min_score=4, candles=None):
    """
    Walk-forward backtest of the live strategy. Returns a dict with the
    trade log and summary metrics. Raises ValueError if there isn't enough
    history to say anything meaningful.
    """
    timeframe = timeframe or config.DEFAULT_TIMEFRAME
    candles = candles or DEFAULT_CANDLES
    raw, source_note = _get_history(coin, timeframe, candles)
    if not raw:
        raise ValueError(f"Couldn't fetch history for {coin.upper()} on {timeframe}.")
    c = ind.add_indicators(raw)
    n = len(c["close"])
    if n < MIN_WARMUP + 30:
        raise ValueError(
            f"Only {n} candles of history available on {timeframe} — need at "
            f"least {MIN_WARMUP + 30} for a meaningful backtest. Try a smaller "
            f"timeframe (e.g. 15m/1h) to get more history in the same window."
        )

    # Precompute higher-timeframe trend for every point in the base timeframe,
    # once, up front - so the walk-forward loop stays fast (no per-candle API
    # calls) while still no-lookahead (each i only sees HTF candles that had
    # actually closed by that point in real time).
    htf_series = _build_htf_series(coin, timeframe, c["open_time"])

    trades = []
    equity = float(account)
    equity_curve = [equity]
    open_trade = None

    for i in range(MIN_WARMUP, n):
        window = _slice(c, i)

        if open_trade:
            hi, lo = window["high"][-1], window["low"][-1]
            if open_trade["direction"] == "LONG":
                hit_sl = lo <= open_trade["sl"]
                hit_tp = hi >= open_trade["tp"]
            else:
                hit_sl = hi >= open_trade["sl"]
                hit_tp = lo <= open_trade["tp"]

            if hit_sl or hit_tp:
                exit_price = open_trade["sl"] if hit_sl else open_trade["tp"]
                if open_trade["direction"] == "LONG":
                    r_mult = (exit_price - open_trade["entry"]) / open_trade["per_unit_risk"]
                else:
                    r_mult = (open_trade["entry"] - exit_price) / open_trade["per_unit_risk"]
                pnl = r_mult * open_trade["risk_amount"]
                equity += pnl
                trades.append({
                    **open_trade,
                    "exit_price": exit_price,
                    "exit_idx": i,
                    "r_multiple": r_mult,
                    "pnl": pnl,
                    "win": pnl > 0,
                })
                equity_curve.append(equity)
                open_trade = None
            continue

        sr = pat.support_resistance(window)
        patterns = pat.candlestick_patterns(window)
        breakout = pat.detect_breakout(window)
        bull, bear, _rationale, _trend = strategy._score(window, sr, patterns, breakout)

        # Mirror analyze()'s higher-timeframe confluence adjustment so the
        # backtest tests the SAME logic the live bot actually runs.
        base_net = bull - bear
        htf_tf = strategy._HTF_MAP.get(timeframe)
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
        }

    metrics = _compute_metrics(trades, float(account), equity_curve)
    return {
        "coin": coin.upper(),
        "timeframe": timeframe,
        "candles_used": n,
        "source": source_note,
        "start_ts": c["open_time"][0],
        "end_ts": c["open_time"][-1],
        "trades": trades,
        "metrics": metrics,
        "equity_curve": equity_curve,
    }


def _compute_metrics(trades, starting_equity, equity_curve):
    n = len(trades)
    if n == 0:
        return {"trades": 0}

    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    win_rate = len(wins) / n * 100.0

    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in losses)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    avg_r = sum(t["r_multiple"] for t in trades) / n
    expectancy = sum(t["pnl"] for t in trades) / n
    final_equity = equity_curve[-1]
    total_return_pct = (final_equity - starting_equity) / starting_equity * 100.0

    peak = equity_curve[0]
    max_dd = 0.0
    for e in equity_curve:
        if e > peak:
            peak = e
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)

    max_win_streak = max_loss_streak = cur_win = cur_loss = 0
    for t in trades:
        if t["win"]:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss += 1
            cur_win = 0
        max_win_streak = max(max_win_streak, cur_win)
        max_loss_streak = max(max_loss_streak, cur_loss)

    return {
        "trades": n,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_r": avg_r,
        "expectancy": expectancy,
        "total_return_pct": total_return_pct,
        "final_equity": final_equity,
        "max_drawdown_pct": max_dd * 100.0,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "long_trades": sum(1 for t in trades if t["direction"] == "LONG"),
        "short_trades": sum(1 for t in trades if t["direction"] == "SHORT"),
    }


def format_backtest(result):
    """HTML-formatted Telegram report."""
    import html as _html
    m = result["metrics"]
    lines = [
        f"<b>📊 Backtest — {_html.escape(result['coin'])}/USDT · {_html.escape(result['timeframe'])}</b>",
        f"<i>{result['candles_used']} candles"
        + (f" via {_html.escape(result['source'])}" if result.get("source") else "") + "</i>",
        "",
    ]
    if m.get("trades", 0) == 0:
        lines.append("No trades triggered on this history/settings — try a "
                     "smaller timeframe (more candles) or a lower min_score.")
        return "\n".join(lines)

    lines.append(f"Trades: <b>{m['trades']}</b> "
                 f"({m['long_trades']} long, {m['short_trades']} short)")
    lines.append(f"Win rate: <b>{m['win_rate']:.1f}%</b>")
    pf = m["profit_factor"]
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    lines.append(f"Profit factor: <b>{pf_str}</b>  ·  Avg R: {m['avg_r']:+.2f}")
    lines.append(f"Expectancy: <b>${m['expectancy']:+.2f}</b>/trade")
    lines.append(f"Total return: <b>{m['total_return_pct']:+.1f}%</b> "
                 f"(${m['final_equity']:,.2f} final)")
    lines.append(f"Max drawdown: <b>{m['max_drawdown_pct']:.1f}%</b>")
    lines.append(f"Longest streak: {m['max_win_streak']} wins / "
                 f"{m['max_loss_streak']} losses")
    lines.append(
        "\n<i>⚠️ Backtest only — no fees/slippage modeled, and same-candle "
        "stop/target hits are resolved conservatively (assumes stop first). "
        "Past results don't guarantee future ones.</i>"
    )
    return "\n".join(lines)
