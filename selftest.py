"""
selftest.py
-----------
Offline + online verification of the bot's brains (no Telegram needed).

1. Sanity-checks indicator math against hand-computed values.
2. Builds a synthetic OHLCV series and runs the FULL pipeline
   (indicators -> patterns -> signal -> risk plan) so we know it works even if
   the network is blocked.
3. If Binance is reachable, runs a live analysis on BTC as a bonus.

Pure Python — no pandas/numpy needed. Run it with:  python selftest.py
"""

import math
import random

import indicators as ind
import patterns as pat
import strategy


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(b))


def test_ema():
    s = [1.0, 2, 3, 4, 5]
    # EMA span=2 -> alpha=2/3. Compute expected iteratively.
    alpha = 2 / 3
    exp = [1.0]
    for x in [2, 3, 4, 5]:
        exp.append(alpha * x + (1 - alpha) * exp[-1])
    got = ind.ema(s, 2)
    assert all(approx(g, e) for g, e in zip(got, exp)), (got, exp)
    print("  ema ....... OK")


def test_rsi_all_gains():
    # Strictly increasing closes -> RSI should be 100 (no losses).
    s = [float(x) for x in range(1, 40)]
    r = ind.rsi(s, 14)[-1]
    assert approx(r, 100.0, 1e-3), r
    print("  rsi ....... OK (all-gains -> 100)")


def test_atr_positive():
    n = 60
    high = [10 + 10 * i / (n - 1) + 0.5 for i in range(n)]
    low = [10 + 10 * i / (n - 1) - 0.5 for i in range(n)]
    close = [10 + 10 * i / (n - 1) for i in range(n)]
    candles = {"high": high, "low": low, "close": close}
    a = ind.atr(candles, 14)[-1]
    assert a > 0 and math.isfinite(a), a
    print("  atr ....... OK (positive, finite)")


def test_bollinger_contains_mean():
    s = [100 + 5 * math.sin(i / 3.0) for i in range(100)]
    up, mid, low = ind.bollinger(s, 20, 2.0)
    i = 50
    assert low[i] <= mid[i] <= up[i]
    print("  bollinger . OK (lower <= mid <= upper)")


def test_risk_engine():
    # Long: account 1000, risk 1% => risk $10. Entry 100, stop 95 => $5/unit.
    p = strategy.plan_trade(1000, 1.0, 100, 95, rr=2.0)
    assert p["direction"] == "LONG"
    assert approx(p["risk_amount"], 10.0)
    assert approx(p["per_unit_risk"], 5.0)
    assert approx(p["size"], 2.0)                 # $10 / $5
    assert approx(p["tp"], 110.0)                 # entry + 2 * 5
    assert approx(p["notional"], 200.0)           # 2 units * 100
    # Short: stop above entry.
    ps = strategy.plan_trade(1000, 2.0, 100, 105, rr=1.5)
    assert ps["direction"] == "SHORT"
    assert approx(ps["risk_amount"], 20.0)
    assert approx(ps["size"], 4.0)                # $20 / $5
    assert approx(ps["tp"], 92.5)                 # 100 - 1.5*5
    # Zero-distance stop must raise.
    try:
        strategy.plan_trade(1000, 1, 100, 100)
        raise AssertionError("expected ValueError for stop==entry")
    except ValueError:
        pass
    print("  risk ...... OK (long, short, size, TP, guardrail)")


def make_synthetic(n=260, seed=7):
    """Trending-up series with noise, so trend/plan logic has something real."""
    rng = random.Random(seed)
    close, cum = [], 0.0
    for i in range(n):
        drift = 30.0 * i / (n - 1)
        cum += rng.gauss(0, 0.8)
        close.append(100.0 + drift + cum)
    high = [close[i] + rng.uniform(0.2, 1.2) for i in range(n)]
    low = [close[i] - rng.uniform(0.2, 1.2) for i in range(n)]
    openp = [close[i] - rng.gauss(0, 0.5) for i in range(n)]
    vol = [rng.uniform(100, 500) for _ in range(n)]
    return {"open_time": list(range(n)), "open": openp, "high": high,
            "low": low, "close": close, "volume": vol}


def test_pipeline_offline(_unused=None):
    """Run analyze() end-to-end against synthetic data by patching data.get_klines."""
    import data as market
    synthetic = make_synthetic()
    orig = market.get_klines
    market.get_klines = lambda *a, **k: {k2: list(v) for k2, v in synthetic.items()}
    try:
        a = strategy.analyze("TEST", timeframe="4h", account=1000, risk_pct=1, rr=2)
    finally:
        market.get_klines = orig
    assert a["direction"] in ("LONG", "SHORT", "NEUTRAL")
    assert a["price"] > 0
    assert "rationale" in a and len(a["rationale"]) >= 1
    if a["plan"]:
        p = a["plan"]
        # Risk must equal exactly risk_pct of account.
        assert approx(p["risk_amount"], 10.0), p["risk_amount"]
        # Stop must be on the correct side of entry.
        if p["direction"] == "LONG":
            assert p["sl"] < p["entry"] < p["tp"]
        else:
            assert p["tp"] < p["entry"] < p["sl"]
    print(f"  pipeline .. OK (direction={a['direction']}, score={a['score']}, "
          f"trend={a['trend']})")
    return a


def test_live():
    import data as market
    try:
        px = market.get_price("BTC")
        a = strategy.analyze("BTC", timeframe="4h")
        print(f"  live ...... OK (BTC ~${px:,.0f}, signal={a['direction']}, "
              f"score={a['score']})")
    except Exception as e:
        print(f"  live ...... SKIPPED (no network / blocked): {e}")


if __name__ == "__main__":
    print("Indicator math:")
    test_ema(); test_rsi_all_gains(); test_atr_positive(); test_bollinger_contains_mean()
    print("Risk engine:")
    test_risk_engine()
    print("Full pipeline (offline synthetic data):")
    test_pipeline_offline()
    print("Live data (bonus):")
    test_live()
    print("\nALL CORE TESTS PASSED")
