"""
nlp.py
------
The "reading brain" of the radar. Given any piece of text (a Trump post, an
exchange announcement, a news headline) it answers three questions:

  1. extract_tokens(text)     -> which crypto token(s) are being talked about?
  2. classify_impact(text)    -> is this likely BULLISH / BEARISH / NEUTRAL, and
                                 how confident are we (with plain-English reasons)?
  3. crypto_relevance(text)   -> is this even 1% crypto-related? (the gate that
                                 decides whether an influencer post is worth a ping)

IMPORTANT — honesty:
  These are transparent *heuristics*, not predictions of profit. Markets often do
  the opposite of the "obvious" read (buy-the-rumor / sell-the-news, already priced
  in, fakeouts). Confidence is deliberately capped below 100% and every alert must
  carry the not-financial-advice disclaimer. This mirrors the whole bot's rule:
  probabilities and risk management, never guarantees.

No third-party packages required — pure standard library. An optional CoinGecko
cache (coins_cache.json) can widen coin coverage but the bot works fine without it.
"""

import json
import os
import re

_HERE = os.path.dirname(__file__)
_COIN_CACHE_FILE = os.path.join(_HERE, "coins_cache.json")


# ============================================================================
# 1) COIN / TOKEN DATABASE
# ============================================================================
# Curated map: TICKER -> list of names/aliases that appear in real text.
# This is hand-picked so it stays high-precision (few false alarms). The bot
# can optionally widen coverage from CoinGecko, but these are the ones that
# actually move on headlines and influencer posts.
CURATED = {
    "BTC": ["bitcoin"],
    "ETH": ["ethereum", "ether"],
    "SOL": ["solana"],
    "XRP": ["ripple", "xrp"],
    "BNB": ["binance coin", "bnb chain"],
    "DOGE": ["dogecoin", "doge coin"],
    "ADA": ["cardano"],
    "AVAX": ["avalanche"],
    "LINK": ["chainlink"],
    "MATIC": ["polygon", "matic"],
    "POL": ["polygon ecosystem"],
    "DOT": ["polkadot"],
    "TRX": ["tron"],
    "LTC": ["litecoin"],
    "BCH": ["bitcoin cash"],
    "SHIB": ["shiba inu", "shiba"],
    "PEPE": ["pepe coin", "pepecoin"],
    "WIF": ["dogwifhat"],
    "BONK": ["bonk"],
    "UNI": ["uniswap"],
    "AAVE": ["aave"],
    "MKR": ["maker dao", "makerdao"],
    "LDO": ["lido"],
    "ARB": ["arbitrum"],
    "OP": ["optimism"],
    "APT": ["aptos"],
    "SUI": ["sui network", "sui blockchain"],
    "SEI": ["sei network"],
    "TIA": ["celestia"],
    "INJ": ["injective"],
    "NEAR": ["near protocol"],
    "FIL": ["filecoin"],
    "ATOM": ["cosmos"],
    "ICP": ["internet computer"],
    "HBAR": ["hedera"],
    "VET": ["vechain"],
    "ALGO": ["algorand"],
    "XLM": ["stellar lumens", "stellar"],
    "ETC": ["ethereum classic"],
    "FTM": ["fantom"],
    "S": ["sonic labs"],
    "RUNE": ["thorchain"],
    "GRT": ["the graph"],
    "IMX": ["immutable"],
    "RNDR": ["render network", "render token"],
    "RENDER": ["render network"],
    "FET": ["fetch.ai", "fetch ai", "artificial superintelligence alliance"],
    "TAO": ["bittensor"],
    "WLD": ["worldcoin", "world network"],
    "ONDO": ["ondo finance", "ondo"],
    "ENA": ["ethena"],
    "JUP": ["jupiter exchange", "jupiter dex"],
    "PYTH": ["pyth network"],
    "JTO": ["jito"],
    "HYPE": ["hyperliquid"],
    "DYDX": ["dydx"],
    "GMX": ["gmx"],
    "SNX": ["synthetix"],
    "CRV": ["curve finance", "curve dao"],
    "COMP": ["compound finance"],
    "USDT": ["tether"],
    "USDC": ["usd coin", "circle usdc"],
    "DAI": ["dai stablecoin"],
    "TON": ["toncoin", "the open network"],
    "KAS": ["kaspa"],
    "STX": ["stacks"],
    "TRUMP": ["official trump", "trump coin", "maga coin"],
    "MELANIA": ["melania coin", "official melania"],
    "MOODENG": ["moo deng", "moodeng"],
    "FART": ["fartcoin"],
    "VIRTUAL": ["virtuals protocol", "virtual protocol"],
    "AI16Z": ["ai16z"],
    "MOG": ["mog coin"],
    "SPX": ["spx6900"],
    "GOAT": ["goatseus maximus"],
    "PENGU": ["pudgy penguins"],
}

# Tickers safe to match as a bare word (e.g. "BTC", "SOL"). We exclude tickers
# that are also common English words or too short/ambiguous — those only match
# via a $cashtag or their full name.
SAFE_BARE_TICKERS = {
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "MATIC",
    "TRX", "LTC", "BCH", "SHIB", "PEPE", "ARB", "SUI", "SEI",
    "TIA", "INJ", "ATOM", "ICP", "HBAR", "XLM", "FTM",
    "RUNE", "IMX", "RNDR", "FET", "TAO", "WLD", "ONDO", "ENA", "PYTH",
    "DYDX", "GMX", "SNX", "USDT", "USDC", "KAS", "STX",
}
# NOTE: tickers that are also everyday English words (LINK, NEAR, DOT, HYPE, TON,
# APT, ETC, ALGO...) are deliberately NOT here. They only match via a $cashtag or
# their full project name (e.g. "Hyperliquid" -> HYPE), which keeps false alarms low.

# Words that look like tickers but almost never mean the coin in normal text.
_TICKER_STOPWORDS = {
    "A", "I", "THE", "FOR", "ON", "IN", "AT", "TO", "US", "IT", "AN", "OR",
    "AND", "IS", "BE", "SO", "GO", "UP", "NO", "OK", "ID", "AI", "CEO", "USA",
    "GAS", "TIME", "WIN", "MOVE", "NOT", "ALL", "NEW", "NOW", " ",
}

_CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,9})\b")


def _load_extra_coins():
    """Optionally widen coverage from a cached CoinGecko list (see refresh_coin_cache).

    Returns dict name(lower) -> TICKER, using only *full names* that are long and
    unambiguous, to avoid a flood of false positives from 15k+ tiny coins.
    """
    if not os.path.exists(_COIN_CACHE_FILE):
        return {}
    try:
        with open(_COIN_CACHE_FILE, "r", encoding="utf-8") as f:
            coins = json.load(f)
    except Exception:
        return {}
    out = {}
    for c in coins:
        name = (c.get("name") or "").strip().lower()
        sym = (c.get("symbol") or "").strip().upper()
        if not name or not sym:
            continue
        # Only trust reasonably long, multi-character names (a coin literally
        # named "for" or "id" would wreck precision).
        if len(name) < 5 or name in _TICKER_STOPWORDS:
            continue
        out.setdefault(name, sym)
    return out


# Build the name -> ticker lookup once at import.
def _build_name_index():
    idx = {}
    for ticker, aliases in CURATED.items():
        for a in aliases:
            idx[a.lower()] = ticker
    # Extra coins fill gaps but never override curated (curated is higher-trust).
    for name, ticker in _load_extra_coins().items():
        idx.setdefault(name, ticker)
    return idx


_NAME_INDEX = _build_name_index()
# Longest names first so "bitcoin cash" wins over "bitcoin" when both could match.
_SORTED_NAMES = sorted(_NAME_INDEX.keys(), key=len, reverse=True)


def _word_present(needle, haystack_lower):
    """Whole-word / whole-phrase match, case-insensitive."""
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])",
                     haystack_lower) is not None


def extract_tokens(text):
    """Find crypto tokens mentioned in `text`.

    Returns a list of dicts: {ticker, name, how, confidence}, best first.
      how = 'cashtag' | 'name' | 'ticker' | 'coingecko'
    """
    if not text:
        return []
    low = text.lower()
    found = {}   # ticker -> best match dict

    def _add(ticker, name, how, conf):
        cur = found.get(ticker)
        if cur is None or conf > cur["confidence"]:
            found[ticker] = {"ticker": ticker, "name": name, "how": how,
                             "confidence": round(conf, 2)}

    # 1) $CASHTAGS — strongest, people use them to mean exactly that token.
    for m in _CASHTAG_RE.finditer(text):
        tk = m.group(1).upper()
        if tk in _TICKER_STOPWORDS:
            continue
        pretty = CURATED.get(tk, [tk.title()])[0].title() if tk in CURATED else tk
        _add(tk, "$" + tk, "cashtag", 0.95)

    # 2) Full names / aliases (curated first via the sorted index).
    for name in _SORTED_NAMES:
        if _word_present(name, low):
            ticker = _NAME_INDEX[name]
            how = "name" if name in _flatten_curated_aliases() else "coingecko"
            conf = 0.9 if how == "name" else 0.6
            _add(ticker, name, how, conf)

    # 3) Bare tickers, but only the safe, unambiguous ones.
    for tk in SAFE_BARE_TICKERS:
        if _word_present(tk.lower(), low):
            pretty = CURATED.get(tk, [tk])[0]
            _add(tk, pretty, "ticker", 0.75)

    return sorted(found.values(), key=lambda d: d["confidence"], reverse=True)


_CURATED_ALIAS_SET = None


def _flatten_curated_aliases():
    global _CURATED_ALIAS_SET
    if _CURATED_ALIAS_SET is None:
        s = set()
        for aliases in CURATED.values():
            for a in aliases:
                s.add(a.lower())
        _CURATED_ALIAS_SET = s
    return _CURATED_ALIAS_SET


# ============================================================================
# 2) IMPACT / DIRECTION CLASSIFICATION
# ============================================================================
# (phrase, weight) — weight 2 = strong mover, 1 = mild. Phrases are matched as
# substrings on lowercased text, so multi-word phrases work.
_BULLISH = [
    ("etf approved", 3), ("etf approval", 3), ("spot etf", 2),
    ("approved", 2), ("approval", 2), ("green light", 2), ("greenlight", 2),
    ("will list", 3), ("to list", 2), ("lists ", 2), ("listing", 2),
    ("now available", 2), ("now trading", 2), ("goes live", 2), ("going live", 1),
    ("launches", 1), ("launch", 1), ("mainnet", 1),
    ("partnership", 2), ("partners with", 2), ("integrates", 2), ("integration", 2),
    ("collaboration", 1), ("teams up", 1),
    ("adopts", 2), ("adoption", 1), ("accepts", 2), ("accepting", 2),
    ("coming to the us", 2), ("coming to america", 2), ("coming to the united states", 2),
    ("strategic reserve", 3), ("national reserve", 3), ("reserve asset", 2),
    ("buy", 1), ("buys", 2), ("buying", 1), ("accumulate", 2), ("accumulating", 2),
    ("invests", 2), ("investment", 1), ("backed by", 1), ("acquires", 2),
    ("bullish", 2), ("all-time high", 2), ("ath", 1), ("surge", 1), ("rally", 1),
    ("token burn", 2), ("buyback", 2), ("halving", 1), ("upgrade", 1),
    ("approve", 2), ("support for", 1), ("whitelist", 1), ("airdrop", 1),
    ("rate cut", 2), ("cuts rates", 2), ("dovish", 2), ("stimulus", 1),
]
_BEARISH = [
    ("hack", 3), ("hacked", 3), ("exploit", 3), ("exploited", 3), ("stolen", 2),
    ("drained", 3), ("breach", 2), ("attack", 2), ("vulnerability", 1),
    ("lawsuit", 2), ("sues", 2), ("sued", 2), ("charged", 2), ("charges", 2),
    ("sec charges", 3), ("indicted", 3), ("fraud", 3), ("ponzi", 3),
    ("investigation", 2), ("probe", 2), ("subpoena", 2),
    ("ban", 2), ("banned", 3), ("bans", 2), ("crackdown", 2), ("outlaw", 2),
    ("delist", 3), ("delisted", 3), ("delisting", 3), ("remove", 1),
    ("halt", 2), ("halted", 2), ("suspends", 2), ("suspended", 2), ("paused", 1),
    ("freeze", 2), ("frozen", 2), ("seized", 2), ("seizure", 2),
    ("insolvent", 3), ("insolvency", 3), ("bankrupt", 3), ("bankruptcy", 3),
    ("collapse", 3), ("collapses", 3), ("liquidated", 2), ("liquidation", 2),
    ("rug", 3), ("rugpull", 3), ("rug pull", 3), ("scam", 3), ("exit scam", 3),
    ("depeg", 3), ("depegged", 3), ("de-peg", 3),
    ("outage", 2), ("downtime", 1), ("bug", 1), ("emergency", 1),
    ("dump", 2), ("dumps", 2), ("crash", 2), ("plunge", 2), ("bearish", 2),
    ("warning", 1), ("warns", 1), ("reject", 2), ("rejected", 2), ("denied", 2),
    ("rate hike", 2), ("hikes rates", 2), ("hawkish", 2), ("tariff", 1),
]


def classify_impact(text):
    """Estimate likely market direction of a piece of text.

    Returns {direction, confidence, bull, bear, reasons}. direction is one of
    'BULLISH' / 'BEARISH' / 'NEUTRAL'. confidence is a 0..1 heuristic, capped
    at 0.9 on purpose — we never claim certainty.
    """
    low = (text or "").lower()
    bull = 0
    bear = 0
    reasons = []
    for phrase, w in _BULLISH:
        if phrase in low:
            bull += w
            reasons.append((f"+{w}", "bullish", phrase.strip()))
    for phrase, w in _BEARISH:
        if phrase in low:
            bear += w
            reasons.append((f"-{w}", "bearish", phrase.strip()))

    net = bull - bear
    if net > 0:
        direction = "BULLISH"
    elif net < 0:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    strength = abs(net)
    if strength == 0:
        confidence = 0.0
    else:
        # More net weight -> more confident, but capped so we stay honest.
        confidence = min(0.9, 0.35 + 0.13 * strength)

    # Keep the strongest few reasons for display.
    reasons.sort(key=lambda r: abs(int(r[0])), reverse=True)
    pretty_reasons = [f"{'📈' if pol == 'bullish' else '📉'} {phrase}"
                      for _, pol, phrase in reasons[:5]]

    return {
        "direction": direction,
        "confidence": round(confidence, 2),
        "bull": bull,
        "bear": bear,
        "reasons": pretty_reasons,
    }


# ============================================================================
# 3) CRYPTO RELEVANCE GATE
# ============================================================================
# Generic crypto vocabulary. If an influencer post contains any of these (or a
# recognised token), it clears the "even 1% crypto-related" bar and we consider
# alerting.
_CRYPTO_TERMS = [
    "crypto", "cryptocurrency", "bitcoin", "btc", "ethereum", "eth", "blockchain",
    "token", "tokens", "altcoin", "stablecoin", "defi", "web3", "nft", "mining",
    "miner", "wallet", "exchange", "binance", "coinbase", "kraken", "sec ",
    "etf", "satoshi", "on-chain", "onchain", "ledger", "memecoin", "meme coin",
    "digital asset", "digital currency", "cbdc", "dogecoin", "solana", "ripple",
    "xrp", "hodl", "airdrop", "staking", "halving", "market cap", "trading",
]


def crypto_relevance(text):
    """How crypto-related is this text? Returns {relevant, score, terms, tokens}."""
    low = (text or "").lower()
    hits = [t.strip() for t in _CRYPTO_TERMS if t in low]
    tokens = extract_tokens(text)
    # A recognised token is the strongest signal of relevance.
    token_boost = 0.5 if tokens else 0.0
    term_score = min(0.5, 0.12 * len(set(hits)))
    score = round(min(1.0, token_boost + term_score), 2)
    return {
        "relevant": score > 0,
        "score": score,
        "terms": sorted(set(hits))[:8],
        "tokens": tokens,
    }


# ============================================================================
# One-call convenience used by the radar
# ============================================================================
def analyze_text(text):
    """Full read of a piece of text: tokens + impact + relevance in one dict."""
    rel = crypto_relevance(text)
    impact = classify_impact(text)
    return {
        "tokens": rel["tokens"],
        "impact": impact,
        "relevance": rel["score"],
        "relevance_terms": rel["terms"],
    }


# ============================================================================
# Optional: widen coin coverage from CoinGecko (free, no key). Call occasionally.
# ============================================================================
def refresh_coin_cache(timeout=15):
    """Download the CoinGecko coin list and cache it locally. Best-effort.

    Safe to call in the background at startup. If it fails (offline / rate
    limited), the bot just keeps using the curated map.
    """
    import requests
    url = "https://api.coingecko.com/api/v3/coins/list"
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "crypto-trade-assistant-bot/2.0"})
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        coins = r.json()
        # Trim to the fields we use to keep the file small.
        slim = [{"symbol": c.get("symbol"), "name": c.get("name")} for c in coins]
        with open(_COIN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(slim, f)
        # Rebuild the in-memory index so new coins are usable immediately.
        global _NAME_INDEX, _SORTED_NAMES
        _NAME_INDEX = _build_name_index()
        _SORTED_NAMES = sorted(_NAME_INDEX.keys(), key=len, reverse=True)
        return True, f"cached {len(slim)} coins"
    except Exception as e:
        return False, str(e)
