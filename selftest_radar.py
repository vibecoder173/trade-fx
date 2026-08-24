"""
selftest_radar.py
-----------------
Offline checks for the radar's "brains" — no network, no Telegram needed.
Verifies:
  1. Token extraction (incl. Hyperliquid -> HYPE, cashtags, and NO false alarms
     on everyday words like link / near / ton / dot).
  2. Impact classification direction (bullish / bearish / neutral).
  3. The crypto-relevance gate.
  4. radar.collect_events de-duplication.
  5. The bot's alert decision + alert formatting.

Run:  python selftest_radar.py
"""

import nlp
import radar


def tickers(text):
    return {t["ticker"] for t in nlp.extract_tokens(text)}


def test_extraction():
    cases = [
        ("Hyperliquid is coming to the US!", "HYPE", True),
        ("Coinbase will list $WIF today", "WIF", True),
        ("SEC approves spot Bitcoin ETF", "BTC", True),
        ("Solana validators halted after an outage", "SOL", True),
        ("Ethereum bridge exploit — funds drained", "ETH", True),
        ("$DOGE to the moon", "DOGE", True),
    ]
    for text, want, present in cases:
        got = tickers(text)
        assert (want in got) == present, f"{text!r} -> {got}, wanted {want}={present}"

    # Precision: these everyday words must NOT be read as tokens.
    for text in ["here is the link to the article",
                 "in the near future we will see",
                 "that's a ton of money",
                 "dot the i's and cross the t's",
                 "I walked my dog in the park"]:
        got = tickers(text)
        assert not got, f"false positive on {text!r}: {got}"
    print("  extraction ........ OK (Hyperliquid->HYPE, cashtags, no false alarms)")


def test_impact():
    assert nlp.classify_impact("SEC approves the spot ETF")["direction"] == "BULLISH"
    assert nlp.classify_impact("Binance will list the token")["direction"] == "BULLISH"
    assert nlp.classify_impact("Exchange hacked, funds stolen")["direction"] == "BEARISH"
    assert nlp.classify_impact("Project delisted amid lawsuit")["direction"] == "BEARISH"
    assert nlp.classify_impact("gm crypto fam, happy monday")["direction"] == "NEUTRAL"
    # Confidence is capped below 1.0 on purpose (we never claim certainty).
    strong = nlp.classify_impact("hacked exploit stolen drained bankruptcy delisted")
    assert strong["direction"] == "BEARISH" and strong["confidence"] <= 0.9
    print("  impact ............ OK (bull/bear/neutral, confidence capped <=0.9)")


def test_relevance():
    hi = nlp.crypto_relevance("Bitcoin and crypto adoption in the USA")
    lo = nlp.crypto_relevance("Tariffs on imported steel announced today")
    assert hi["score"] > 0 and hi["relevant"]
    assert lo["score"] == 0 and not lo["relevant"]
    print("  relevance ......... OK (crypto post clears gate, non-crypto does not)")


def test_dedup(monkeypatch=None):
    ev1 = radar._mk("truth_social", "Truth Social · @x", "@x", "Bitcoin!", "u1", "1", ts=100)
    ev1b = radar._mk("truth_social", "Truth Social · @x", "@x", "Bitcoin!", "u1", "1", ts=90)
    ev2 = radar._mk("truth_social", "Truth Social · @x", "@x", "Ethereum!", "u2", "2", ts=200)
    orig_fn = radar.poll_truth_social
    orig_src = radar.config.RADAR_SOURCES
    radar.poll_truth_social = lambda *a, **k: [ev1, ev1b, ev2]
    radar.config.RADAR_SOURCES = {"truth_social": True, "exchange_listings": False,
                                  "news": False, "x": False}
    try:
        events = radar.collect_events()
    finally:
        radar.poll_truth_social = orig_fn
        radar.config.RADAR_SOURCES = orig_src
    ids = [e["id"] for e in events]
    assert ids == ["truth_social:2", "truth_social:1"], ids   # unique, newest first
    print("  dedup ............. OK (duplicates collapsed, newest first)")


def test_alert_decision_and_format():
    import bot
    # No network during the test: make the live-price lookup fail quietly.
    bot.market.get_24h_stats = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))

    # A Trump-style post naming a token that's "coming to the US" -> should alert.
    ev = radar._mk("truth_social", "Truth Social · @realDonaldTrump",
                   "@realDonaldTrump", "Hyperliquid is coming to the US!", "http://x", "9")
    a = nlp.analyze_text(ev["text"])
    assert bot._should_alert(ev, a) is True
    msg = bot.format_event_alert(ev, a)
    assert "RADAR" in msg and "HYPE" in msg and "BULLISH" in msg
    assert "Not financial advice" in msg

    # A non-crypto political post -> must NOT alert.
    ev2 = radar._mk("truth_social", "Truth Social · @realDonaldTrump",
                    "@realDonaldTrump", "Tariffs on steel are going up!", "http://x", "10")
    a2 = nlp.analyze_text(ev2["text"])
    assert bot._should_alert(ev2, a2) is False

    # A listing is always high-signal.
    ev3 = radar._mk("binance_listing", "Binance · Listings", "Binance",
                    "Binance Will List Something (ABC)", "http://b", "11")
    a3 = nlp.analyze_text(ev3["text"])
    assert bot._should_alert(ev3, a3) is True
    print("  alerts ............ OK (fires on crypto post, skips politics, always on listings)")


if __name__ == "__main__":
    print("Token extraction:")
    test_extraction()
    print("Impact classification:")
    test_impact()
    print("Relevance gate:")
    test_relevance()
    print("Radar de-duplication:")
    test_dedup()
    print("Alert decision + formatting:")
    test_alert_decision_and_format()
    print("\nALL RADAR TESTS PASSED ✅")
