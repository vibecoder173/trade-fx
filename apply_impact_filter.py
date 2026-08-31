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

impact_py = '''"""
impact.py
---------
Scores a headline/post for how likely it is to actually move a market, so
news.py and radar.py can drop routine noise instead of forwarding everything
that merely mentions a coin's name.

Philosophy: mentioning "bitcoin" is not news. A regulatory action, a hack, an
ETF decision, a bankruptcy, a major partnership, or a violent price move IS.
We score by keyword category; only headlines clearing a minimum score pass.
"""

import re

# category -> (weight, keywords). Weight reflects how reliably this category
# actually correlates with a real price reaction, not just a mention.
_CATEGORIES = {
    "regulatory": (3, [
        "sec ", "sec charges", "sec approves", "sec rejects", "lawsuit",
        "sues", "sued", "settlement", "regulator", "regulation", "ban ",
        "banned", "illegal", "investigation", "subpoena", "cftc", "doj",
    ]),
    "etf": (3, ["etf approval", "etf approved", "etf rejected", "etf filing",
                "spot etf", "etf launch"]),
    "security": (3, ["hack", "hacked", "exploit", "exploited", "breach",
                     "stolen", "rug pull", "drain", "vulnerability"]),
    "corporate": (2, ["bankruptcy", "files for chapter 11", "insolvent",
                       "acquires", "acquisition", "merger", "partnership",
                       "ceo resigns", "ceo arrested", "ceo steps down"]),
    "exchange": (2, ["delist", "delisting", "listed on", "listing", "halts trading",
                      "suspends withdrawals", "freezes"]),
    "macro": (2, ["fed ", "federal reserve", "interest rate", "inflation data",
                   "halving", "hard fork", "network upgrade", "depeg", "depegged"]),
    "price_action": (2, ["all-time high", "all time high", "ath", "crashes",
                          "plunges", "plummets", "surges", "soars", "tumbles",
                          "wipes out", "liquidat"]),
    "adoption": (1, ["government adopts", "legal tender", "reserve", "treasury buys",
                      "adds bitcoin", "adds btc"]),
}


def impact_score(text: str) -> int:
    """Sum of category weights whose keywords appear in the text (case-insens).
    Each category counts once even if multiple its keywords match."""
    t = (text or "").lower()
    score = 0
    for _cat, (weight, kws) in _CATEGORIES.items():
        if any(kw in t for kw in kws):
            score += weight
    return score


def is_significant(text: str, min_score: int = 2) -> bool:
    return impact_score(text) >= min_score
'''

with open("impact.py", "w", encoding="utf-8") as f:
    f.write(impact_py)
print("OK   [impact.py] created")

# ---------------------------------------------------------------------- news.py
old_news_top = '''import time
import config'''
new_news_top = '''import time
import config
import impact'''
patch("news.py", old_news_top, new_news_top, "import impact")

old_filter = '''def filter_relevant(headlines, watchlist):
    """Keep headlines mentioning a watched coin or a market-moving keyword."""
    words = _keywords_for(watchlist)
    out = []
    for h in headlines:
        title = h["title"].lower()
        hit = next((w for w in words if w in title), None)
        if hit:
            h = dict(h)
            h["matched"] = hit
            out.append(h)
    return out'''

new_filter = '''def filter_relevant(headlines, watchlist, min_impact=None):
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
    return out'''

patch("news.py", old_filter, new_filter, "require impact score to pass")

# --------------------------------------------------------------------- radar.py
old_radar_top = '''import requests

import config'''
new_radar_top = '''import requests

import config
import impact'''
patch("radar.py", old_radar_top, new_radar_top, "import impact")

old_collect = '''    if src.get("news"):
        events += poll_news()
    if src.get("x"):
        handles = list(config.X_HANDLES) + list(extra_x_handles or [])
        events += poll_x(handles)'''

new_collect = '''    if src.get("news"):
        min_impact = getattr(config, "RADAR_MIN_IMPACT", 2)
        events += [e for e in poll_news() if impact.impact_score(e["text"]) >= min_impact]
    if src.get("x"):
        handles = list(config.X_HANDLES) + list(extra_x_handles or [])
        min_impact = getattr(config, "RADAR_MIN_IMPACT", 2)
        events += [e for e in poll_x(handles) if impact.impact_score(e["text"]) >= min_impact]'''

patch("radar.py", old_collect, new_collect, "filter news/X events by impact score")

print("Done.")
