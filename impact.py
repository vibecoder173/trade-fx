"""
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
