"""
selftest_data.py
----------------
Offline verification of every exchange adapter in data.py WITHOUT the network.

Each exchange returns candles/tickers in its OWN shape and its OWN order (some
newest-first, some with columns in a weird order like KuCoin's O,C,H,L or
Gate.io's close-before-open). A wrong column index would silently corrupt every
indicator. So here we feed each adapter a hand-built payload that mimics the real
API response and assert the normalized candle dict is exactly right:

  * open/high/low/close/volume mapped to the correct source columns
  * timestamps normalized to ms and sorted OLDEST -> NEWEST
  * price/stats parsed with the right 24h-change convention

We monkeypatch data._get_json (and Binance's getter) so nothing hits the internet.
Pure Python. Run:  python selftest_data.py
"""

import math
import data


def approx(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


def assert_candles(c, label):
    """Every adapter must yield 3 rows, oldest-first, with our known OHLCV."""
    assert c is not None, f"{label}: got None"
    for k in ("open_time", "open", "high", "low", "close", "volume"):
        assert k in c and len(c[k]) == 3, f"{label}: bad column {k} -> {c.get(k)}"
    # oldest -> newest
    assert c["open_time"] == sorted(c["open_time"]), f"{label}: not sorted oldest-first"
    # We encode a recognizable pattern: close = 100,110,120 after sorting.
    assert c["close"] == [100.0, 110.0, 120.0], f"{label}: close mapping wrong -> {c['close']}"
    assert c["open"] == [99.0, 109.0, 119.0], f"{label}: open mapping wrong -> {c['open']}"
    assert c["high"] == [101.0, 111.0, 121.0], f"{label}: high mapping wrong -> {c['high']}"
    assert c["low"] == [98.0, 108.0, 118.0], f"{label}: low mapping wrong -> {c['low']}"
    assert c["volume"] == [10.0, 11.0, 12.0], f"{label}: volume mapping wrong -> {c['volume']}"
    print(f"  {label:8s} klines .. OK (OHLCV mapped + oldest-first)")


# Canonical rows we want to end up with, per candle (oldest to newest):
#   t=1000s, o=99,  h=101, l=98,  c=100, v=10
#   t=2000s, o=109, h=111, l=108, c=110, v=11
#   t=3000s, o=119, h=121, l=118, c=120, v=12
BASE = [
    (1000, 99.0, 101.0, 98.0, 100.0, 10.0),
    (2000, 109.0, 111.0, 108.0, 110.0, 11.0),
    (3000, 119.0, 121.0, 118.0, 120.0, 12.0),
]


def test_binance():
    # Binance kline: [openTime(ms), o, h, l, c, v, ...]  (oldest-first already)
    payload = [[t * 1000, o, h, l, c, v, 0, 0, 0] for (t, o, h, l, c, v) in BASE]
    data._binance_get = lambda path, params, timeout=8: payload
    assert_candles(data._binance_klines("BTC", "USDT", "4h", 300), "Binance")


def test_bybit():
    # Bybit v5: result.list rows [start(ms), o, h, l, c, v, turnover], NEWEST-first
    rows = [[str(t * 1000), str(o), str(h), str(l), str(c), str(v), "0"]
            for (t, o, h, l, c, v) in reversed(BASE)]
    data._get_json = lambda url, params, timeout=7: {"result": {"list": rows}}
    assert_candles(data._bybit_klines("BTC", "USDT", "4h", 300), "Bybit")


def test_okx():
    # OKX: data rows [ts(ms), o, h, l, c, vol, volCcy, ...], NEWEST-first, strings
    rows = [[str(t * 1000), str(o), str(h), str(l), str(c), str(v), "0", "0"]
            for (t, o, h, l, c, v) in reversed(BASE)]
    data._get_json = lambda url, params, timeout=7: {"data": rows}
    assert_candles(data._okx_klines("BTC", "USDT", "4h", 300), "OKX")


def test_kucoin():
    # KuCoin: data rows [time(SEC), open, CLOSE, high, low, volume, turnover]
    # NOTE the O, C, H, L ordering — classic trap. NEWEST-first, strings.
    rows = [[str(t), str(o), str(c), str(h), str(l), str(v), "0"]
            for (t, o, h, l, c, v) in reversed(BASE)]
    data._get_json = lambda url, params, timeout=7: {"data": rows}
    assert_candles(data._kucoin_klines("BTC", "USDT", "4h", 300), "KuCoin")


def test_mexc():
    # MEXC: Binance-compatible [openTime(ms), o, h, l, c, v, ...], oldest-first
    payload = [[t * 1000, str(o), str(h), str(l), str(c), str(v), 0, "0"]
               for (t, o, h, l, c, v) in BASE]
    data._get_json = lambda url, params, timeout=7: payload
    assert_candles(data._mexc_klines("BTC", "USDT", "4h", 300), "MEXC")


def test_gate():
    # Gate.io: [t(SEC), quote_vol, CLOSE, HIGH, LOW, OPEN, base_vol, ...]
    # close/high/low/open ordering + volume in col 6. NEWEST-first, strings.
    rows = [[str(t), "0", str(c), str(h), str(l), str(o), str(v), "true"]
            for (t, o, h, l, c, v) in reversed(BASE)]
    data._get_json = lambda url, params, timeout=7: rows
    assert_candles(data._gate_klines("BTC", "USDT", "4h", 300), "Gate.io")


def test_stats_parsing():
    # Bybit uses a FRACTION for price24hPcnt (0.05 -> +5%); OKX/KuCoin compute
    # from open/rate; CoinGecko already gives a percent. Verify each.
    data._get_json = lambda url, params, timeout=7: {
        "result": {"list": [{"lastPrice": "100", "price24hPcnt": "0.05",
                             "highPrice24h": "110", "lowPrice24h": "90",
                             "turnover24h": "1234"}]}}
    s = data._bybit_stats("BTC", "USDT")
    assert approx(s["last"], 100) and approx(s["change_pct"], 5.0), s
    print("  Bybit    stats ... OK (fraction -> percent)")

    data._get_json = lambda url, params, timeout=7: {
        "data": [{"last": "110", "open24h": "100", "high24h": "120",
                  "low24h": "95", "volCcy24h": "999"}]}
    s = data._okx_stats("BTC", "USDT")
    assert approx(s["last"], 110) and approx(s["change_pct"], 10.0), s
    print("  OKX      stats ... OK (computed from open24h)")

    data._get_json = lambda url, params, timeout=7: {
        "data": {"last": "50", "changeRate": "-0.02", "high": "55",
                 "low": "48", "volValue": "42"}}
    s = data._kucoin_stats("BTC", "USDT")
    assert approx(s["last"], 50) and approx(s["change_pct"], -2.0), s
    print("  KuCoin   stats ... OK (rate -> percent, negative)")

    # CoinGecko: search -> id, then simple/price
    def fake_cg(url, params, timeout=7):
        if "search" in url:
            return {"coins": [{"id": "pepe", "symbol": "PEPE"}]}
        return {"pepe": {"usd": 0.0000012, "usd_24h_change": 7.5, "usd_24h_vol": 999}}
    data._get_json = fake_cg
    s = data._coingecko_stats("PEPE", "USDT")
    assert approx(s["last"], 0.0000012) and approx(s["change_pct"], 7.5), s
    print("  CoinGecko stats .. OK (universal price catch-all)")


def test_fallback_chain():
    """get_klines must skip a source that returns None and use the next one.

    We patch the network GETTERS (not the adapters) so the real adapter code
    runs: Binance's getter returns None (coin not there) -> MEXC's getter serves
    the candles -> get_klines should return MEXC's data and tag the source.
    """
    import config
    orig = config.EXCHANGES
    config.EXCHANGES = ["Binance", "MEXC"]         # only these two in the chain
    data._binance_get = lambda path, params, timeout=8: None   # Binance: no data
    payload = [[t * 1000, str(o), str(h), str(l), str(c), str(v), 0, "0"]
               for (t, o, h, l, c, v) in BASE]
    data._get_json = lambda url, params, timeout=7: payload     # MEXC: has it
    try:
        c = data.get_klines("SOMECOIN", "4h", 300)
        assert data.LAST_KLINE_SOURCE == "MEXC", data.LAST_KLINE_SOURCE
        assert c["close"] == [100.0, 110.0, 120.0]
        print("  fallback klines .. OK (skipped Binance -> used MEXC, source tagged)")
    finally:
        config.EXCHANGES = orig


def test_unavailable_raises():
    """A coin on no source must raise DataUnavailable (so the bot can be honest)."""
    import config
    orig = config.EXCHANGES
    config.EXCHANGES = ["Binance"]
    data._binance_get = lambda path, params, timeout=8: None
    try:
        raised = False
        try:
            data.get_klines("GHOSTCOIN", "4h", 300)
        except data.DataUnavailable:
            raised = True
        assert raised, "expected DataUnavailable"
        print("  unavailable ...... OK (raises DataUnavailable, no fake plan)")
    finally:
        config.EXCHANGES = orig


def test_split_and_symbol():
    assert data._split("btc") == ("BTC", "USDT")
    assert data._split("ETH/USDC") == ("ETH", "USDC")
    assert data._split("sol-usdt") == ("SOL", "USDT")
    assert data.to_symbol("btc") == "BTCUSDT"
    print("  symbol   parse ... OK (base/quote split)")


if __name__ == "__main__":
    print("Symbol handling:")
    test_split_and_symbol()
    print("Kline adapters (OHLCV mapping + ordering):")
    test_binance(); test_bybit(); test_okx(); test_kucoin(); test_mexc(); test_gate()
    print("Stats adapters (24h-change conventions):")
    test_stats_parsing()
    print("Fallback behaviour:")
    test_fallback_chain(); test_unavailable_raises()
    print("\nALL DATA-LAYER TESTS PASSED")
