"""
news.py
-------
Pulls crypto headlines from free, public RSS feeds and filters them for
relevance (your watched coins + market-moving keywords).

Used two ways:
  - /news command  -> latest relevant headlines on demand
  - background loop -> alert you when a *new* market-moving headline appears
"""

import time
import config
import impact

try:
    import feedparser
    _HAVE_FEEDPARSER = True
except Exception:
    _HAVE_FEEDPARSER = False

# Map tickers to the words that actually appear in headlines.
COIN_NAMES = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "ether", "eth"],
    "SOL": ["solana", "sol"],
    "XRP": ["xrp", "ripple"],
    "ADA": ["cardano", "ada"],
    "DOGE": ["dogecoin", "doge"],
    "BNB": ["bnb", "binance coin"],
    "AVAX": ["avalanche", "avax"],
    "LINK": ["chainlink", "link"],
    "MATIC": ["polygon", "matic"],
}


def _entry_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return time.mktime(t)
    return 0.0


def fetch_headlines(limit: int = 20):
    """Return recent headlines across all feeds, newest first."""
    if not _HAVE_FEEDPARSER:
        raise RuntimeError(
            "The 'feedparser' package is not installed. Run: pip install feedparser"
        )
    items = []
    for url in config.NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            source = feed.feed.get("title", url)
            for e in feed.entries:
                items.append({
                    "title": e.get("title", "").strip(),
                    "link": e.get("link", ""),
                    "source": source,
                    "ts": _entry_time(e),
                    "id": e.get("id", e.get("link", e.get("title", ""))),
                })
        except Exception:
            # A single broken feed should never take down the whole command.
            continue
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]


def _keywords_for(watchlist):
    words = set(k.lower() for k in config.NEWS_MARKET_KEYWORDS)
    for coin in watchlist:
        for w in COIN_NAMES.get(coin.upper(), [coin.lower()]):
            words.add(w)
    return words


def filter_relevant(headlines, watchlist, min_impact=None):
    """Keep headlines that (a) mention a watched coin/keyword AND (b) score as
    actually market-moving - not just any article that says "bitcoin"."""
    min_impact = config.NEWS_MIN_IMPACT if min_impact is None else min_impact
    words = _keywords_for(watchlist)
    out = []
    for h in headlines:
        title = h["title"].lower()
        hit = next((w for w in words if w in title), None)
        if not hit:
            continue
        score = impact.impact_score(h["title"])
        if score < min_impact:
            continue
        h = dict(h)
        h["matched"] = hit
        h["impact_score"] = score
        out.append(h)
    out.sort(key=lambda x: x["impact_score"], reverse=True)
    return out
