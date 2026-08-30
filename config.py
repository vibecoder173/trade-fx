"""
config.py
---------
Central configuration for the Crypto Trade Assistant Bot.

For a normal setup you only ever need to touch:
  1. The .env file  -> your Telegram bot token
  2. DEFAULT_WATCHLIST below -> the coins you care about

Everything else has sensible defaults you can leave alone.
"""

import os

# --- Load the token from the .env file -----------------------------------
# We try python-dotenv first; if it isn't installed we fall back to a tiny
# manual parser so the bot still runs.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(_env_path):
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

# --- Market data ----------------------------------------------------------
DEFAULT_QUOTE = "USDT"          # coins are priced against this (BTC -> BTCUSDT)
DEFAULT_TIMEFRAME = "4h"        # candle size used for analysis
CANDLE_LIMIT = 300             # how many candles to pull per analysis
BINANCE_BASE = "https://api.binance.com"
# Market-data hosts, tried in order until one answers. The first works from most
# of the world. The second is Binance's PUBLIC data mirror, which is reachable
# from places where the main api is geo-blocked — e.g. US-based servers like
# GitHub Actions runners. This fallback is what lets /price and /analyze keep
# working when the bot is hosted for free on GitHub. (No effect on phone/PC use,
# where the first host answers straight away.)
BINANCE_HOSTS = [
    "https://api.binance.com",
    "https://data-api.binance.vision",
]

# --- Multi-exchange coverage ---------------------------------------------
# The bot no longer depends on Binance alone. For any coin, it tries these
# exchanges IN ORDER until one has the pair, so you can reach almost anything.
# Leave as-is for widest coverage, or trim to just the ones you trust.
# Valid labels: Binance, Bybit, OKX, KuCoin, MEXC, Gate.io
EXCHANGES = ["Binance", "Bybit", "OKX", "KuCoin", "MEXC", "Gate.io"]
# If none of the above has the coin, fall back to CoinGecko for a PRICE ONLY
# (covers ~every token incl. small-caps/DEX). Chart analysis still needs an
# exchange — we won't fake a trade plan on a coin that trades nowhere we track.
COINGECKO_PRICE_FALLBACK = True


# Coins the bot watches for automatic alerts (symbols WITHOUT the quote).
DEFAULT_WATCHLIST = ["BTC", "ETH", "SOL"]

# --- Risk / trade-plan defaults ------------------------------------------
DEFAULT_ACCOUNT = 1000.0        # used by /risk when you don't pass an amount
DEFAULT_RISK_PCT = 1.0          # risk this % of the account per trade
DEFAULT_RR = 2.0                # default reward-to-risk ratio for take-profit
ATR_SL_MULT = 1.5               # stop-loss distance = this * ATR

# --- Signal engine --------------------------------------------------------
# A setup must reach at least this |score| for the bot to auto-alert you.
# The score is a transparent heuristic, NOT a probability of profit.
MIN_SCORE_ALERT = 4

# --- Auto-scanning --------------------------------------------------------
SCAN_INTERVAL_MIN = 30          # minutes between automatic market scans
NEWS_SCAN_INTERVAL_MIN = 20     # minutes between automatic news checks
ALERTS_ON_BY_DEFAULT = True

# --- News feeds (free, public RSS) ---------------------------------------
NEWS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://bitcoinmagazine.com/feed",
]
# Only headlines containing one of these words trigger an auto news alert.
NEWS_MARKET_KEYWORDS = [
    "sec", "etf", "hack", "exploit", "lawsuit", "ban", "regulation",
    "approval", "rate", "fed", "inflation", "listing", "delist",
    "partnership", "upgrade", "fork", "halving", "liquidation",
]

# ==========================================================================
# EVENT RADAR — influencer posts, exchange listings, breaking news
# ==========================================================================
# This is the "be first" system: it polls fast, free sources and pings you the
# moment something market-moving drops, tells you which token it's about, and
# gives an honest BULLISH/BEARISH read with a confidence score (never a promise).
RADAR_ON_BY_DEFAULT = True
RADAR_SCAN_INTERVAL_SEC = 60        # how often to check the fast sources (seconds)

# --- Who to watch on Truth Social (free, Mastodon-style public API, no key) ---
# 'id' is the account's numeric Truth Social ID. Trump's is below. To add
# someone, find their numeric id (see README) and add a line here.
TRUTH_SOCIAL_ACCOUNTS = [
    {"handle": "@realDonaldTrump", "id": "107780257626128497"},
]

# --- Who to watch on X / Twitter ------------------------------------------
# HONEST NOTE: X killed free API access. These handles are only polled if you
# add a working Nitter mirror below. Left empty, X is simply skipped and the
# other sources still work. See README for options (incl. a cheap paid feed).
X_HANDLES = ["elonmusk", "cz_binance", "VitalikButerin", "saylor",
             "brian_armstrong", "justinsuntron"]
NITTER_INSTANCES = []               # e.g. ["https://nitter.poast.org"] if one works

# --- Exchange listing sources ---------------------------------------------
BINANCE_ANNOUNCEMENT_API = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    "?type=1&catalogId=48&pageNo=1&pageSize=20"
)
LISTING_RSS_FEEDS = [
    "https://www.coinbase.com/blog/rss.xml",
]
LISTING_KEYWORDS = [
    "will list", "lists ", "listing", "new listing", "adds", "now available",
    "now trading", "launches trading", "support for", "goes live", "perpetual",
]

# --- Master on/off switches for each radar source -------------------------
RADAR_SOURCES = {
    "truth_social": True,
    "exchange_listings": True,
    "news": True,
    "x": True,          # only actually runs if NITTER_INSTANCES is set
}

# How crypto-related an INFLUENCER post must be to ping you (0..1). Low on
# purpose — you asked to hear about anything even 1% crypto-related.
RADAR_MIN_RELEVANCE = 0.15

# --- Files ----------------------------------------------------------------
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

# --- Legal ----------------------------------------------------------------
DISCLAIMER = (
    "⚠️ *Not financial advice.* This bot shares educational analysis "
    "and probabilities, never guarantees. Crypto is volatile and you can lose "
    "money. Never risk more than you can afford to lose. Always use a stop-loss."
)

# Minimum ADX to treat a trend as strong enough to fully trust (else discounted)
ADX_TREND_THRESHOLD = 20
