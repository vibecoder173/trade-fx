"""
data.py
-------
Fetches live market data from many free, public, no-key exchange APIs and falls
back through them so the bot works for almost ANY coin — not just Binance pairs.

Coverage strategy (tried in order, first hit wins):
  * Candles / analysis:  Binance -> Bybit -> OKX -> KuCoin -> MEXC -> Gate.io
  * Price / 24h stats:   the six exchanges above, then CoinGecko as a universal
                         catch-all (covers ~everything, incl. DEX/small-cap tokens)

Why this split? Real technical analysis needs a proper orderbook + candle history.
The six exchanges give that for essentially every actively-traded coin. For a coin
that trades nowhere we track (brand-new / DEX-only), we can still show a CoinGecko
price, but we will NOT fake a chart-based trade plan on data that thin.

Candles are returned as a plain dict of equal-length lists (columns) so the rest
of the bot needs no pandas/numpy:
    {"open_time": [...ms...], "open": [...], "high": [...], "low": [...],
     "close": [...], "volume": [...]}   -- always sorted OLDEST -> NEWEST.

Pure Python: only `requests`.
"""

import math
import time
import requests

import config

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "crypto-trade-assistant-bot/1.0"})

# After a successful fetch we record who served it, so the bot can tell the user
# where the data came from (and how much to trust it).
LAST_KLINE_SOURCE = None       # e.g. "Binance", "MEXC" (candles / analysis)
LAST_STATS_SOURCE = None       # e.g. "Binance", "CoinGecko" (price / 24h)

# Binance stays first because it's deepest + fastest for the majors. We keep its
# two-host failover (main api + public data mirror) for geo-blocked networks.
_WORKING_BINANCE = None

# Canonical timeframe -> seconds (used to build time-range requests, e.g. KuCoin).
_CANON_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200,
    "1d": 86400, "3d": 259200, "1w": 604800,
}


# ===========================================================================
# small helpers
# ===========================================================================
def _f(x):
    """Safe float; returns None if it can't parse."""
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _norm_tf(interval):
    """Normalise a user timeframe to our canonical Binance-style token."""
    tf = (interval or config.DEFAULT_TIMEFRAME).lower().strip()
    aliases = {"60m": "1h", "240m": "4h", "1440m": "1d",
               "1hr": "1h", "4hr": "4h", "24h": "1d", "7d": "1w",
               "1min": "1m", "5min": "5m", "15min": "15m", "d": "1d", "w": "1w"}
    return aliases.get(tf, tf)


def _split(coin):
    """Turn 'btc' / 'BTC/USDT' / 'ethusdc' into (BASE, QUOTE). Default quote USDT."""
    s = str(coin).upper().replace("/", "").replace("-", "").replace("_", "").strip()
    for q in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USD"):
        if s.endswith(q) and len(s) > len(q):
            return s[:-len(q)], q
    return s, config.DEFAULT_QUOTE


def to_symbol(coin: str) -> str:
    """Binance-style display symbol, e.g. 'btc' -> 'BTCUSDT'. Used for labels."""
    base, quote = _split(coin)
    return base + quote


def _pack(rows, limit=None):
    """Take a list of (open_time_ms, o, h, l, c, v) tuples -> canonical dict.

    Sorts OLDEST->NEWEST (so we never depend on an exchange's ordering), drops
    junk/NaN rows, and de-duplicates by timestamp.
    """
    clean = {}
    for ot, o, h, l, c, v in rows:
        if None in (ot, o, h, l, c):
            continue
        if v is None:
            v = 0.0
        clean[int(ot)] = (o, h, l, c, v)
    if not clean:
        return None
    out = {"open_time": [], "open": [], "high": [], "low": [], "close": [], "volume": []}
    for ot in sorted(clean):
        o, h, l, c, v = clean[ot]
        out["open_time"].append(ot)
        out["open"].append(o); out["high"].append(h); out["low"].append(l)
        out["close"].append(c); out["volume"].append(v)
    if limit and len(out["open_time"]) > limit:
        for k in out:
            out[k] = out[k][-limit:]
    return out


def _ms(ts):
    """Normalise a timestamp (s or ms) to milliseconds int."""
    v = _f(ts)
    if v is None:
        return None
    return int(v if v > 1e11 else v * 1000)


# ===========================================================================
# Binance (primary) — keeps its two-host geo-failover
# ===========================================================================
def _binance_hosts():
    hosts = list(getattr(config, "BINANCE_HOSTS", None) or [config.BINANCE_BASE])
    if _WORKING_BINANCE and _WORKING_BINANCE in hosts:
        hosts = [_WORKING_BINANCE] + [h for h in hosts if h != _WORKING_BINANCE]
    return hosts


def _binance_get(path, params, timeout=8):
    global _WORKING_BINANCE
    last = None
    for base in _binance_hosts():
        try:
            r = _SESSION.get(base + path, params=params, timeout=timeout)
            if r.status_code == 200:
                _WORKING_BINANCE = base
                return r.json()
            if r.status_code == 400:      # genuinely bad/unknown symbol here
                return None
            last = RuntimeError(f"HTTP {r.status_code} from {base}")
        except requests.RequestException as e:
            last = e
    if last:
        raise last
    return None


_BINANCE_TF = {tf: tf for tf in _CANON_SECONDS}  # Binance uses our canonical names


def _binance_klines(base, quote, tf, limit):
    if tf not in _BINANCE_TF:
        return None
    raw = _binance_get("/api/v3/klines",
                       {"symbol": base + quote, "interval": _BINANCE_TF[tf],
                        "limit": min(limit, 1000)})
    if not raw:
        return None
    rows = [(_ms(r[0]), _f(r[1]), _f(r[2]), _f(r[3]), _f(r[4]), _f(r[5])) for r in raw]
    return _pack(rows, limit)


def _binance_stats(base, quote):
    d = _binance_get("/api/v3/ticker/24hr", {"symbol": base + quote})
    if not d or "lastPrice" not in d:
        return None
    return {"symbol": base + quote, "last": _f(d["lastPrice"]),
            "change_pct": _f(d.get("priceChangePercent")) or 0.0,
            "high": _f(d.get("highPrice")), "low": _f(d.get("lowPrice")),
            "volume": _f(d.get("quoteVolume")) or 0.0}


# ===========================================================================
# Other exchanges — single host each, simple GET
# ===========================================================================
def _get_json(url, params, timeout=7):
    r = _SESSION.get(url, params=params, timeout=timeout)
    if r.status_code != 200:
        return None
    return r.json()


# ---- Bybit (v5) ------------------------------------------------------------
_BYBIT_TF = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
             "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720",
             "1d": "D", "1w": "W"}


def _bybit_klines(base, quote, tf, limit):
    iv = _BYBIT_TF.get(tf)
    if not iv:
        return None
    j = _get_json("https://api.bybit.com/v5/market/kline",
                  {"category": "spot", "symbol": base + quote, "interval": iv,
                   "limit": min(limit, 1000)})
    lst = ((j or {}).get("result") or {}).get("list") or []
    # row: [start, open, high, low, close, volume, turnover]
    rows = [(_ms(r[0]), _f(r[1]), _f(r[2]), _f(r[3]), _f(r[4]), _f(r[5])) for r in lst]
    return _pack(rows, limit)


def _bybit_stats(base, quote):
    j = _get_json("https://api.bybit.com/v5/market/tickers",
                  {"category": "spot", "symbol": base + quote})
    lst = ((j or {}).get("result") or {}).get("list") or []
    if not lst:
        return None
    d = lst[0]
    pcnt = _f(d.get("price24hPcnt"))
    return {"symbol": base + quote, "last": _f(d.get("lastPrice")),
            "change_pct": (pcnt * 100.0) if pcnt is not None else 0.0,
            "high": _f(d.get("highPrice24h")), "low": _f(d.get("lowPrice24h")),
            "volume": _f(d.get("turnover24h")) or 0.0}


# ---- OKX -------------------------------------------------------------------
_OKX_TF = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
           "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
           "1d": "1D", "1w": "1W"}


def _okx_klines(base, quote, tf, limit):
    bar = _OKX_TF.get(tf)
    if not bar:
        return None
    j = _get_json("https://www.okx.com/api/v5/market/candles",
                  {"instId": f"{base}-{quote}", "bar": bar, "limit": min(limit, 300)})
    data = (j or {}).get("data") or []
    # row: [ts, o, h, l, c, vol, volCcy, ...]
    rows = [(_ms(r[0]), _f(r[1]), _f(r[2]), _f(r[3]), _f(r[4]), _f(r[5])) for r in data]
    return _pack(rows, limit)


def _okx_stats(base, quote):
    j = _get_json("https://www.okx.com/api/v5/market/ticker",
                  {"instId": f"{base}-{quote}"})
    data = (j or {}).get("data") or []
    if not data:
        return None
    d = data[0]
    last, open24 = _f(d.get("last")), _f(d.get("open24h"))
    chg = ((last - open24) / open24 * 100.0) if (last and open24) else 0.0
    return {"symbol": f"{base}{quote}", "last": last, "change_pct": chg,
            "high": _f(d.get("high24h")), "low": _f(d.get("low24h")),
            "volume": _f(d.get("volCcy24h")) or 0.0}


# ---- KuCoin ----------------------------------------------------------------
_KUCOIN_TF = {"1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min",
              "30m": "30min", "1h": "1hour", "2h": "2hour", "4h": "4hour",
              "6h": "6hour", "8h": "8hour", "12h": "12hour", "1d": "1day",
              "1w": "1week"}


def _kucoin_klines(base, quote, tf, limit):
    typ = _KUCOIN_TF.get(tf)
    if not typ:
        return None
    sec = _CANON_SECONDS.get(tf, 3600)
    end = int(time.time())
    start = end - sec * min(limit, 1500)
    j = _get_json("https://api.kucoin.com/api/v1/market/candles",
                  {"symbol": f"{base}-{quote}", "type": typ,
                   "startAt": start, "endAt": end})
    data = (j or {}).get("data") or []
    # row: [time(sec), open, close, high, low, volume, turnover]  (note O,C,H,L!)
    rows = [(_ms(r[0]), _f(r[1]), _f(r[3]), _f(r[4]), _f(r[2]), _f(r[5])) for r in data]
    return _pack(rows, limit)


def _kucoin_stats(base, quote):
    j = _get_json("https://api.kucoin.com/api/v1/market/stats",
                  {"symbol": f"{base}-{quote}"})
    d = (j or {}).get("data") or {}
    if not d or d.get("last") is None:
        return None
    rate = _f(d.get("changeRate"))
    return {"symbol": f"{base}{quote}", "last": _f(d.get("last")),
            "change_pct": (rate * 100.0) if rate is not None else 0.0,
            "high": _f(d.get("high")), "low": _f(d.get("low")),
            "volume": _f(d.get("volValue")) or 0.0}


# ---- MEXC (Binance-compatible; huge small-cap coverage) --------------------
_MEXC_TF = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "60m", "4h": "4h", "1d": "1d", "1w": "1W"}


def _mexc_klines(base, quote, tf, limit):
    iv = _MEXC_TF.get(tf)
    if not iv:
        return None
    raw = _get_json("https://api.mexc.com/api/v3/klines",
                    {"symbol": base + quote, "interval": iv, "limit": min(limit, 1000)})
    if not raw or not isinstance(raw, list):
        return None
    rows = [(_ms(r[0]), _f(r[1]), _f(r[2]), _f(r[3]), _f(r[4]), _f(r[5])) for r in raw]
    return _pack(rows, limit)


def _mexc_stats(base, quote):
    d = _get_json("https://api.mexc.com/api/v3/ticker/24hr", {"symbol": base + quote})
    if not d or "lastPrice" not in d:
        return None
    return {"symbol": base + quote, "last": _f(d["lastPrice"]),
            "change_pct": _f(d.get("priceChangePercent")) or 0.0,
            "high": _f(d.get("highPrice")), "low": _f(d.get("lowPrice")),
            "volume": _f(d.get("quoteVolume")) or 0.0}


# ---- Gate.io (v4) ----------------------------------------------------------
_GATE_TF = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1h", "4h": "4h", "8h": "8h", "1d": "1d", "1w": "7d"}


def _gate_klines(base, quote, tf, limit):
    iv = _GATE_TF.get(tf)
    if not iv:
        return None
    raw = _get_json("https://api.gateio.ws/api/v4/spot/candlesticks",
                    {"currency_pair": f"{base}_{quote}", "interval": iv,
                     "limit": min(limit, 1000)})
    if not raw or not isinstance(raw, list):
        return None
    # row: [t(sec), quote_volume, close, high, low, open, base_volume, ...]
    rows = []
    for r in raw:
        vol = _f(r[6]) if len(r) > 6 else _f(r[1])
        rows.append((_ms(r[0]), _f(r[5]), _f(r[3]), _f(r[4]), _f(r[2]), vol))
    return _pack(rows, limit)


def _gate_stats(base, quote):
    raw = _get_json("https://api.gateio.ws/api/v4/spot/tickers",
                    {"currency_pair": f"{base}_{quote}"})
    if not raw or not isinstance(raw, list) or not raw:
        return None
    d = raw[0]
    return {"symbol": f"{base}{quote}", "last": _f(d.get("last")),
            "change_pct": _f(d.get("change_percentage")) or 0.0,
            "high": _f(d.get("high_24h")), "low": _f(d.get("low_24h")),
            "volume": _f(d.get("quote_volume")) or 0.0}


# ---- CoinGecko (universal PRICE catch-all; never used for candles) ---------
def _coingecko_stats(base, quote):
    j = _get_json("https://api.coingecko.com/api/v3/search", {"query": base})
    coins = (j or {}).get("coins") or []
    cid = None
    for c in coins:                                  # prefer an exact ticker match
        if (c.get("symbol") or "").upper() == base.upper():
            cid = c.get("id"); break
    if not cid and coins:                            # else the top (biggest) hit
        cid = coins[0].get("id")
    if not cid:
        return None
    p = _get_json("https://api.coingecko.com/api/v3/simple/price",
                  {"ids": cid, "vs_currencies": "usd",
                   "include_24hr_change": "true", "include_24hr_vol": "true"})
    d = (p or {}).get(cid) or {}
    last = _f(d.get("usd"))
    if last is None:
        return None
    return {"symbol": f"{base}USD", "last": last,
            "change_pct": _f(d.get("usd_24h_change")) or 0.0,
            "high": None, "low": None,
            "volume": _f(d.get("usd_24h_vol")) or 0.0}


# ===========================================================================
# source registries + public API
# ===========================================================================
# (label, klines_fn, stats_fn)  -- order = fallback priority.
_ALL_SOURCES = [
    ("Binance", _binance_klines, _binance_stats),
    ("Bybit",   _bybit_klines,   _bybit_stats),
    ("OKX",     _okx_klines,     _okx_stats),
    ("KuCoin",  _kucoin_klines,  _kucoin_stats),
    ("MEXC",    _mexc_klines,    _mexc_stats),
    ("Gate.io", _gate_klines,    _gate_stats),
]
# CoinGecko is price-only (no reliable candles), so it's a stats-chain tail.
_COINGECKO = ("CoinGecko", None, _coingecko_stats)


def _enabled_labels():
    """Which exchanges are on, from config.EXCHANGES (default: all)."""
    want = getattr(config, "EXCHANGES", None)
    if not want:
        return None
    return {w.strip().lower() for w in want}


def _sources():
    want = _enabled_labels()
    if want is None:
        return list(_ALL_SOURCES)
    return [s for s in _ALL_SOURCES if s[0].lower() in want]


class DataUnavailable(Exception):
    """Raised when no source can serve the requested coin."""


def get_klines(coin: str, interval: str = None, limit: int = None) -> dict:
    """OHLCV candles (oldest first) as a dict of lists, from the first source
    that has the coin. Records the winning source in data.LAST_KLINE_SOURCE."""
    global LAST_KLINE_SOURCE
    tf = _norm_tf(interval)
    limit = limit or config.CANDLE_LIMIT
    base, quote = _split(coin)
    errors = []
    for label, kfn, _sfn in _sources():
        if not kfn:
            continue
        try:
            candles = kfn(base, quote, tf, limit)
        except Exception as e:                       # never let one source crash us
            errors.append(f"{label}: {e}")
            continue
        if candles and len(candles["close"]) >= 2:
            LAST_KLINE_SOURCE = label
            return candles
    raise DataUnavailable(
        f"No exchange has chart data for {base}/{quote} on {tf}. "
        f"(brand-new or DEX-only token?)")


def get_24h_stats(coin: str) -> dict:
    """Price + 24h stats from the first source that has the coin; CoinGecko is
    the universal last resort. Includes a 'source' key."""
    global LAST_STATS_SOURCE
    base, quote = _split(coin)
    chain = _sources() + [_COINGECKO if getattr(config, "COINGECKO_PRICE_FALLBACK", True) else _COINGECKO]
    seen = set()
    for label, _kfn, sfn in chain:
        if not sfn or label in seen:
            continue
        seen.add(label)
        try:
            st = sfn(base, quote)
        except Exception:
            continue
        if st and st.get("last") is not None:
            st["source"] = label
            LAST_STATS_SOURCE = label
            return st
    raise DataUnavailable(f"Couldn't find a price for {base} on any source.")


def get_price(coin: str) -> float:
    """Latest price for a coin (uses the same universal fallback chain)."""
    return float(get_24h_stats(coin)["last"])
