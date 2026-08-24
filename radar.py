"""
radar.py
--------
The "ears" of the bot. It pulls fresh posts / announcements from several FREE
public sources and returns them as a single, normalised list of events. It does
NOT decide what they mean — that's nlp.py's job — and it never places trades.

Sources (all free, no paid keys):
  * Truth Social   -> tracks accounts like @realDonaldTrump (Mastodon-style API)
  * Exchange       -> Binance new-listing announcements (+ RSS listing feeds)
  * News           -> the same crypto RSS feeds the /news command already uses
  * X / Twitter    -> BEST-EFFORT only. The free X API is gone, so this works
                      only if you add a working Nitter mirror in config. Off by
                      default; see README for the honest story.

Design rules:
  * A broken source must NEVER crash the bot — every poller catches its own
    errors and just returns [] so the others keep working.
  * Each event has a stable `id` so the bot can avoid alerting twice.
"""

import html
import re
import time
from datetime import datetime, timezone

import requests

import config

try:
    import feedparser
    _HAVE_FEEDPARSER = True
except Exception:
    _HAVE_FEEDPARSER = False

# A browser-ish User-Agent helps with public endpoints that dislike bots.
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
})

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s):
    s = s or ""
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"</p\s*>", " ", s, flags=re.I)
    s = _TAG_RE.sub("", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _iso_to_epoch(s):
    if not s:
        return time.time()
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return time.time()


def _mk(source, source_label, author, text, url, native_id, ts=None):
    return {
        "id": f"{source}:{native_id}",
        "source": source,
        "source_label": source_label,
        "author": author,
        "text": text,
        "url": url or "",
        "ts": ts if ts is not None else time.time(),
    }


# ============================================================================
# Truth Social (Trump & co.) — public Mastodon-compatible API, no key
# ============================================================================
def poll_truth_social(accounts=None, per_account=10):
    accounts = accounts if accounts is not None else config.TRUTH_SOCIAL_ACCOUNTS
    out = []
    for acct in accounts:
        handle = acct.get("handle", "?")
        acct_id = acct.get("id")
        if not acct_id:
            continue
        url = (f"https://truthsocial.com/api/v1/accounts/{acct_id}/statuses"
               f"?limit={per_account}&exclude_replies=true")
        try:
            r = _SESSION.get(url, timeout=12)
            if r.status_code != 200:
                continue
            for st in r.json():
                text = _strip_html(st.get("content", ""))
                # Retruths with no text still matter — fall back to the quoted post.
                if not text and st.get("reblog"):
                    text = _strip_html(st["reblog"].get("content", ""))
                if not text:
                    continue
                out.append(_mk(
                    source="truth_social",
                    source_label=f"Truth Social · {handle}",
                    author=handle,
                    text=text,
                    url=st.get("url") or st.get("uri", ""),
                    native_id=str(st.get("id")),
                    ts=_iso_to_epoch(st.get("created_at")),
                ))
        except Exception:
            continue
    return out


# ============================================================================
# Exchange listing announcements (Binance new-listing + RSS listing feeds)
# ============================================================================
def _find_articles(obj, acc):
    """Recursively hunt for dicts that look like announcement articles."""
    if isinstance(obj, dict):
        if "title" in obj and ("code" in obj or "id" in obj):
            acc.append(obj)
        for v in obj.values():
            _find_articles(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _find_articles(v, acc)


def poll_binance_listings():
    out = []
    try:
        r = _SESSION.get(config.BINANCE_ANNOUNCEMENT_API, timeout=12)
        if r.status_code != 200:
            return out
        arts = []
        _find_articles(r.json(), arts)
        for a in arts:
            title = (a.get("title") or "").strip()
            if not title:
                continue
            code = a.get("code") or a.get("id")
            link = f"https://www.binance.com/en/support/announcement/{code}" if code else ""
            rel = a.get("releaseDate") or a.get("createTime")
            ts = float(rel) / 1000.0 if isinstance(rel, (int, float)) else time.time()
            out.append(_mk("binance_listing", "Binance · Listings",
                           "Binance", title, link, str(code), ts))
    except Exception:
        return []
    return out


def poll_listing_rss():
    if not _HAVE_FEEDPARSER:
        return []
    out = []
    kw = [k.lower() for k in config.LISTING_KEYWORDS]
    for url in config.LISTING_RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            src = feed.feed.get("title", url)
            for e in feed.entries[:25]:
                title = (e.get("title") or "").strip()
                if not any(k in title.lower() for k in kw):
                    continue
                out.append(_mk("exchange_listing", f"Listing · {src}",
                               src, title, e.get("link", ""),
                               e.get("id", e.get("link", title)),
                               _entry_time(e)))
        except Exception:
            continue
    return out


def poll_exchange_listings():
    return poll_binance_listings() + poll_listing_rss()


# ============================================================================
# Crypto news (reuses the free RSS feeds from config)
# ============================================================================
def _entry_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return time.mktime(t)
            except Exception:
                pass
    return time.time()


def poll_news():
    if not _HAVE_FEEDPARSER:
        return []
    out = []
    for url in config.NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            src = feed.feed.get("title", url)
            for e in feed.entries[:20]:
                title = (e.get("title") or "").strip()
                if not title:
                    continue
                out.append(_mk("news", f"News · {src}", src, title,
                               e.get("link", ""),
                               e.get("id", e.get("link", title)),
                               _entry_time(e)))
        except Exception:
            continue
    return out


# ============================================================================
# X / Twitter — BEST-EFFORT via Nitter mirrors (off unless you configure one)
# ============================================================================
def poll_x(handles=None):
    handles = handles if handles is not None else config.X_HANDLES
    bases = [b.rstrip("/") for b in getattr(config, "NITTER_INSTANCES", []) if b]
    if not bases or not _HAVE_FEEDPARSER or not handles:
        return []
    out = []
    for handle in handles:
        h = handle.lstrip("@")
        for base in bases:
            try:
                feed = feedparser.parse(f"{base}/{h}/rss")
                if not feed.entries:
                    continue
                for e in feed.entries[:10]:
                    text = _strip_html(e.get("title", "") or e.get("summary", ""))
                    if not text:
                        continue
                    out.append(_mk("x", f"X · @{h}", f"@{h}", text,
                                   e.get("link", ""),
                                   e.get("id", e.get("link", text[:40])),
                                   _entry_time(e)))
                break  # this mirror worked; don't hammer the others
            except Exception:
                continue
    return out


# ============================================================================
# Collect everything (respects the per-source on/off switches in config)
# ============================================================================
def collect_events(extra_x_handles=None):
    """Poll every ENABLED source and return a de-duplicated, time-sorted list."""
    src = config.RADAR_SOURCES
    events = []
    if src.get("truth_social"):
        events += poll_truth_social()
    if src.get("exchange_listings"):
        events += poll_exchange_listings()
    if src.get("news"):
        events += poll_news()
    if src.get("x"):
        handles = list(config.X_HANDLES) + list(extra_x_handles or [])
        events += poll_x(handles)

    # De-dup by id, keep newest.
    seen = {}
    for e in events:
        if e["id"] not in seen or e["ts"] > seen[e["id"]]["ts"]:
            seen[e["id"]] = e
    return sorted(seen.values(), key=lambda e: e["ts"], reverse=True)


def source_status(extra_x_handles=None):
    """A quick, network-free summary of how each source is set up (for /sources)."""
    src = config.RADAR_SOURCES
    x_on = bool(getattr(config, "NITTER_INSTANCES", []))
    return {
        "truth_social": {
            "on": src.get("truth_social", False),
            "detail": f"{len(config.TRUTH_SOCIAL_ACCOUNTS)} account(s): "
                      + ", ".join(a["handle"] for a in config.TRUTH_SOCIAL_ACCOUNTS),
        },
        "exchange_listings": {
            "on": src.get("exchange_listings", False),
            "detail": "Binance new-listings + listing RSS feeds",
        },
        "news": {
            "on": src.get("news", False),
            "detail": f"{len(config.NEWS_FEEDS)} crypto news feeds",
        },
        "x": {
            "on": src.get("x", False) and x_on,
            "detail": ("watching " + ", ".join("@" + h for h in
                       (list(config.X_HANDLES) + list(extra_x_handles or []))))
                      if x_on else
                      "needs a Nitter mirror in config (free X API is gone) — see README",
        },
    }
