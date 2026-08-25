"""
data.py
-------
Fetches live market data from Binance's public REST API.
No API key or account is required for this read-only market data.

Candles are returned as a plain dict of equal-length lists (columns) so the rest
of the bot needs no pandas/numpy:
    {"open_time": [...ms...], "open": [...], "high": [...], "low": [...],
     "close": [...], "volume": [...]}
"""

import math
import time
import requests

import config

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "crypto-trade-assistant-bot/1.0"})

# Once we find a host that answers, stick with it for the rest of this run so we
# don't keep hitting a geo-blocked host on every call.
_WORKING_BASE = None


def _hosts():
    """Ordered list of market-data hosts to try (working one first)."""
    hosts = list(getattr(config, "BINANCE_HOSTS", None) or [config.BINANCE_BASE])
    if _WORKING_BASE and _WORKING_BASE in hosts:
        hosts = [_WORKING_BASE] + [h for h in hosts if h != _WORKING_BASE]
    return hosts


def to_symbol(coin: str) -> str:
    """Turn user input like 'btc' or 'BTC/USDT' into a Binance symbol 'BTCUSDT'."""
    s = coin.upper().replace("/", "").replace("-", "").strip()
    if not s.endswith(config.DEFAULT_QUOTE) and not s.endswith(("USDC", "BUSD", "USD")):
        s = s + config.DEFAULT_QUOTE
    return s


def _get(path: str, params: dict, retries: int = 2):
    """GET helper that fails over across hosts and retries flaky connections.

    Tries each host in config.BINANCE_HOSTS. A 451/403 (geo-block) or network
    error moves on to the next host; a 400 is a genuinely bad symbol, so we stop.
    """
    global _WORKING_BASE
    last_err = None
    for base in _hosts():
        url = base + path
        for attempt in range(retries):
            try:
                r = _SESSION.get(url, params=params, timeout=10)
                if r.status_code == 200:
                    _WORKING_BASE = base           # remember the good host
                    return r.json()
                # 400 = bad/unknown symbol; retrying or switching host won't help.
                if r.status_code == 400:
                    raise ValueError(
                        f"Binance rejected the request (bad symbol?): {r.text[:120]}")
                # Geo-block or permission wall: don't retry this host, try the next.
                if r.status_code in (401, 403, 451):
                    last_err = RuntimeError(
                        f"HTTP {r.status_code} from {base} (region-blocked?)")
                    break
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
            except requests.RequestException as e:
                last_err = e
            time.sleep(0.6 * (attempt + 1))
    raise last_err if last_err else RuntimeError("Unknown network error")


def get_klines(coin: str,
               interval: str = None,
               limit: int = None) -> dict:
    """
    Return OHLCV candles, oldest first, as a dict of lists.
    Columns: open_time (ms int), open, high, low, close, volume (floats).
    Rows with unparseable/NaN values are dropped (like the old dropna()).
    """
    interval = interval or config.DEFAULT_TIMEFRAME
    limit = limit or config.CANDLE_LIMIT
    symbol = to_symbol(coin)
    raw = _get("/api/v3/klines",
               {"symbol": symbol, "interval": interval, "limit": limit})
    if not raw:
        raise ValueError(f"No candle data returned for {symbol}.")

    candles = {"open_time": [], "open": [], "high": [], "low": [],
               "close": [], "volume": []}
    for row in raw:
        # Binance kline row: [openTime, open, high, low, close, volume, ...]
        try:
            o = float(row[1]); h = float(row[2]); l = float(row[3])
            c = float(row[4]); v = float(row[5])
            ot = int(row[0])
        except (TypeError, ValueError, IndexError):
            continue
        if any(math.isnan(x) for x in (o, h, l, c, v)):
            continue
        candles["open_time"].append(ot)
        candles["open"].append(o)
        candles["high"].append(h)
        candles["low"].append(l)
        candles["close"].append(c)
        candles["volume"].append(v)
    return candles


def get_price(coin: str) -> float:
    """Return the latest traded price for a coin."""
    symbol = to_symbol(coin)
    data = _get("/api/v3/ticker/price", {"symbol": symbol})
    return float(data["price"])


def get_24h_stats(coin: str) -> dict:
    """Return 24h price change stats for a coin."""
    symbol = to_symbol(coin)
    data = _get("/api/v3/ticker/24hr", {"symbol": symbol})
    return {
        "symbol": symbol,
        "last": float(data["lastPrice"]),
        "change_pct": float(data["priceChangePercent"]),
        "high": float(data["highPrice"]),
        "low": float(data["lowPrice"]),
        "volume": float(data["quoteVolume"]),
    }
