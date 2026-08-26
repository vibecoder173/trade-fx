"""
bot.py
------
The Telegram bot: command handling (long-polling) + a background scanner that
pushes signal and news alerts.

Run it with:   python bot.py
(Set your token in the .env file first - see README.)

Design notes:
  * Uses the raw Telegram Bot API over HTTPS (only 'requests' needed) so there
    are no async/event-loop surprises - easier to run and debug.
  * All shared state lives in state.json so your watchlist/settings survive
    restarts.
  * Per-user data (watchlist, settings, alert prefs) is keyed by chat_id, so
    multiple people can use this bot without sharing/overwriting each other's
    settings. Shared infrastructure (the radar feed itself, dedup caches,
    tracked X handles) stays global.
  * No trade is ever placed. The bot only informs and alerts.
"""

import copy
import hashlib
import html
import json
import threading
import time
import traceback

import requests

import config
import strategy
import news as news_mod
import data as market
import radar
import nlp

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/"
_STATE_LOCK = threading.Lock()


# ============================================================================
# state
# ============================================================================
def _default_user():
    """Fresh per-user record. Every chat_id gets its own copy of this."""
    return {
        "watchlist": list(config.DEFAULT_WATCHLIST),
        "alerts_on": config.ALERTS_ON_BY_DEFAULT,
        "radar_on": config.RADAR_ON_BY_DEFAULT,
        "settings": {
            "account": config.DEFAULT_ACCOUNT,
            "risk_pct": config.DEFAULT_RISK_PCT,
            "rr": config.DEFAULT_RR,
            "timeframe": config.DEFAULT_TIMEFRAME,
        },
        "last_signal": {},
    }


def _default_state():
    return {
        "users": {},                # chat_id (str) -> _default_user()
        "subscribers": [],          # kept for back-compat / quick membership checks
        "seen_news": [],
        "seen_radar": [],
        "radar_seeded": False,
        "tracked_x": [],
        "commands_sig": None,
    }


def _migrate_legacy_state(raw):
    """
    Old format had one global watchlist/settings/alerts_on/radar_on shared by
    everyone. If we load a file like that, give every existing subscriber
    their own copy of those old values instead of silently losing them.
    """
    if "users" in raw:
        return raw  # already migrated
    legacy_watchlist = raw.get("watchlist", list(config.DEFAULT_WATCHLIST))
    legacy_settings = raw.get("settings", {})
    legacy_alerts_on = raw.get("alerts_on", config.ALERTS_ON_BY_DEFAULT)
    legacy_radar_on = raw.get("radar_on", config.RADAR_ON_BY_DEFAULT)
    legacy_last_signal = raw.get("last_signal", {})

    users = {}
    for chat_id in raw.get("subscribers", []):
        u = _default_user()
        u["watchlist"] = list(legacy_watchlist)
        u["settings"] = {**u["settings"], **legacy_settings}
        u["alerts_on"] = legacy_alerts_on
        u["radar_on"] = legacy_radar_on
        u["last_signal"] = dict(legacy_last_signal)
        users[str(chat_id)] = u

    raw["users"] = users
    for k in ("watchlist", "settings", "alerts_on", "radar_on", "last_signal"):
        raw.pop(k, None)
    print(f"Migrated legacy state.json -> per-user records for {len(users)} user(s).")
    return raw


def load_state():
    try:
        with open(config.STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
        s = _migrate_legacy_state(s)
        base = _default_state()
        base.update(s)
        # backfill any missing fields in existing user records (e.g. after an
        # upgrade that adds a new per-user setting)
        for cid, u in base["users"].items():
            fresh = _default_user()
            fresh.update(u)
            fresh["settings"] = {**fresh["settings"], **u.get("settings", {})}
            base["users"][cid] = fresh
        return base
    except Exception:
        return _default_state()


def save_state(state):
    try:
        with open(config.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print("Could not save state:", e)


STATE = load_state()


# ---------------------------------------------------------------------------
# per-user helpers
# ---------------------------------------------------------------------------
def get_user(chat_id):
    """Thread-safe snapshot (deep copy) of one user's record. Creates it if new."""
    key = str(chat_id)
    with _STATE_LOCK:
        if key not in STATE["users"]:
            STATE["users"][key] = _default_user()
            save_state(STATE)
        return copy.deepcopy(STATE["users"][key])


def update_user(chat_id, fn):
    """
    Thread-safe mutate-and-save. `fn` receives the live user dict and mutates
    it in place. Returns a snapshot of the result.
    """
    key = str(chat_id)
    with _STATE_LOCK:
        u = STATE["users"].setdefault(key, _default_user())
        fn(u)
        save_state(STATE)
        return copy.deepcopy(u)


def all_users_snapshot():
    with _STATE_LOCK:
        return {cid: copy.deepcopy(u) for cid, u in STATE["users"].items()}


def add_subscriber(chat_id):
    with _STATE_LOCK:
        if chat_id not in STATE["subscribers"]:
            STATE["subscribers"].append(chat_id)
        save_state(STATE)


def remove_subscriber(chat_id):
    with _STATE_LOCK:
        if chat_id in STATE["subscribers"]:
            STATE["subscribers"].remove(chat_id)
        save_state(STATE)


# ============================================================================
# telegram helpers
# ============================================================================
def send_message(chat_id, text, preview=False):
    try:
        requests.post(API + "sendMessage", data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": not preview,
        }, timeout=15)
    except requests.RequestException as e:
        print("send_message failed:", e)


def broadcast(text, predicate=None):
    """
    Send `text` to every user whose record passes `predicate(user_dict)`.
    If predicate is None, sends to everyone in `subscribers` (legacy-style,
    used for things that aren't per-user opt-in).
    """
    users = all_users_snapshot()
    if predicate is None:
        with _STATE_LOCK:
            targets = list(STATE.get("subscribers", []))
    else:
        targets = [cid for cid, u in users.items() if predicate(u)]
    for chat_id in targets:
        send_message(chat_id, text)


# ---------------------------------------------------------------------------
# Telegram "/" command menu (so the app suggests commands as you type)
# ---------------------------------------------------------------------------
BOT_COMMANDS = [
    ("start", "Start the bot & show the menu"),
    ("help", "Show every command & how it works"),
    ("radar", "What's hot on the radar (/radar on|off)"),
    ("sources", "Radar sources & whether each is live"),
    ("price", "Price & 24h stats — e.g. /price btc"),
    ("analyze", "Full analysis + trade plan — /analyze btc"),
    ("signal", "Same as analyze — /signal btc"),
    ("risk", "Position size — /risk 42000 41000"),
    ("scan", "Scan your watchlist for the best setups"),
    ("news", "Latest market-moving headlines"),
    ("track", "Watch an X handle — /track elonmusk"),
    ("untrack", "Stop watching an X handle"),
    ("watch", "Add coins — /watch sol avax"),
    ("unwatch", "Remove a coin — /unwatch sol"),
    ("watchlist", "Show your watched coins"),
    ("alerts", "Auto signal & news alerts (on|off)"),
    ("settings", "Show or change your settings"),
]


def register_commands(force=False):
    sig = hashlib.sha1(json.dumps(BOT_COMMANDS).encode("utf-8")).hexdigest()
    with _STATE_LOCK:
        if not force and STATE.get("commands_sig") == sig:
            return False
    payload = {"commands": [{"command": c, "description": d} for c, d in BOT_COMMANDS]}
    try:
        r = requests.post(API + "setMyCommands", json=payload, timeout=15)
        ok = bool(r.json().get("ok"))
    except Exception as e:
        print("setMyCommands failed:", e)
        return False
    if ok:
        with _STATE_LOCK:
            STATE["commands_sig"] = sig
            save_state(STATE)
        print(f"Registered {len(BOT_COMMANDS)} commands with Telegram.")
    else:
        print("setMyCommands returned not-ok.")
    return ok


def esc(s):
    return html.escape(str(s))


def parse_num(tok):
    """Parse '1,000', '$1000', '10k', '1.5%' -> float."""
    t = str(tok).lower().strip().replace(",", "").replace("$", "").replace("%", "")
    mult = 1.0
    if t.endswith("k"):
        mult, t = 1_000.0, t[:-1]
    elif t.endswith("m"):
        mult, t = 1_000_000.0, t[:-1]
    return float(t) * mult


# ============================================================================
# message formatting
# ============================================================================
def pct(a, b):
    """Signed percent move from b to a."""
    if not b:
        return ""
    return f"{(a - b) / b * 100:+.2f}%"


def format_analysis(a):
    fp = strategy.fmt_price
    lines = [f"<b>{esc(a['coin'])}/USDT · {esc(a['timeframe'])}</b>"]
    lines.append(f"Price: <b>{fp(a['price'])}</b>")
    rsi = f"{a['rsi']:.0f}" if a["rsi"] is not None else "n/a"
    lines.append(f"Trend: {esc(a['trend'])} · RSI {rsi}")
    sup = fp(a["support"]) if a["support"] else "n/a"
    res = fp(a["resistance"]) if a["resistance"] else "n/a"
    lines.append(f"Support: {sup} · Resistance: {res}")
    if a["patterns"]:
        pats = ", ".join(f"{esc(n)}" for n, _ in a["patterns"])
        lines.append(f"Patterns: {pats}")

    sign = "+" if a["score"] >= 0 else ""
    if a["direction"] == "NEUTRAL":
        lines.append(f"\n<b>Signal: NO TRADE</b> — conditions are mixed "
                     f"(score {sign}{a['score']}). Best to wait for a cleaner setup.")
    else:
        lines.append(f"\n<b>Signal: {a['direction']} ({esc(a['strength'])})</b> "
                     f"— score {sign}{a['score']}")

    if a["rationale"]:
        why = "\n".join(f"• {esc(r)}" for r in a["rationale"][:6])
        lines.append(f"<i>Why:</i>\n{why}")

    p = a["plan"]
    if p:
        lines.append(
            f"\n<b>Trade plan</b> (risk {p['risk_pct']:g}% of "
            f"${p['account']:,.0f} = ${p['risk_amount']:,.2f})"
        )
        lines.append(f"Entry: {fp(p['entry'])}")
        lines.append(f"Stop:  {fp(p['sl'])}  ({pct(p['sl'], p['entry'])})")
        lines.append(f"Target: {fp(p['tp'])}  ({pct(p['tp'], p['entry'])}) · R:R {p['rr']:g}")
        lines.append(f"Size: {p['size']:.6g} {esc(a['coin'])}  (~${p['notional']:,.2f})")
        if p["leverage"] > 1.0:
            lines.append(f"⚠️ Needs ~{p['leverage']:.1f}x leverage — "
                         f"or lower your risk% / widen nothing and reduce size.")
    lines.append(f"\n{config.DISCLAIMER}")
    if a.get("source"):
        lines.append(f"<i>Chart data via {esc(a['source'])}</i>")
    return "\n".join(lines)


def format_price(stats):
    fp = strategy.fmt_price
    arrow = "🟢" if stats["change_pct"] >= 0 else "🔴"
    lines = [f"<b>{esc(stats['symbol'])}</b> {arrow}",
             f"Price: <b>{fp(stats['last'])}</b>  ({stats['change_pct']:+.2f}% 24h)",
             f"24h High: {fp(stats['high'])}",
             f"24h Low:  {fp(stats['low'])}"]
    src = stats.get("source")
    if src:
        lines.append(f"<i>via {esc(src)}</i>")
    if src == "CoinGecko":
        lines.append("<i>⚠️ Not on a major exchange we track — thin/less liquid. "
                     "Price only; a reliable trade plan needs exchange chart data.</i>")
    return "\n".join(lines)


def format_risk(p, coin=None):
    fp = strategy.fmt_price
    lines = [f"<b>Position sizing — {p['direction']}</b>"]
    lines.append(f"Account: ${p['account']:,.2f} · Risk: {p['risk_pct']:g}% "
                 f"= <b>${p['risk_amount']:,.2f}</b>")
    lines.append(f"Entry: {fp(p['entry'])}")
    lines.append(f"Stop:  {fp(p['sl'])}  ({pct(p['sl'], p['entry'])})")
    lines.append(f"Target: {fp(p['tp'])}  ({pct(p['tp'], p['entry'])}) · R:R {p['rr']:g}")
    unit = coin.upper() if coin else "units"
    lines.append(f"\n<b>Buy size: {p['size']:.6g} {esc(unit)}</b>  "
                 f"(~${p['notional']:,.2f} position)")
    if p["leverage"] > 1.0:
        lines.append(f"⚠️ That position is bigger than your account — "
                     f"it needs ~{p['leverage']:.1f}x leverage. Consider a smaller size.")
    lines.append(f"\n{config.DISCLAIMER}")
    return "\n".join(lines)


def format_news(items, header="📰 Latest crypto headlines"):
    if not items:
        return "No relevant headlines right now."
    lines = [f"<b>{esc(header)}</b>"]
    for h in items[:8]:
        title = esc(h["title"])
        link = esc(h["link"])
        src = esc(h["source"])
        lines.append(f"• <a href=\"{link}\">{title}</a>\n  <i>{src}</i>")
    return "\n".join(lines)


_DIR_EMOJI = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}


def _fmt_hhmm(ts):
    try:
        return time.strftime("%H:%M UTC", time.gmtime(ts))
    except Exception:
        return ""


def _token_price_line(tokens):
    if not tokens:
        return None
    tk = tokens[0]["ticker"]
    try:
        s = market.get_24h_stats(tk)
        arrow = "🟢" if s["change_pct"] >= 0 else "🔴"
        return (f"💹 {esc(tk)}/USDT: {strategy.fmt_price(s['last'])} "
                f"({s['change_pct']:+.2f}% 24h) {arrow}")
    except Exception:
        return None


def format_event_alert(e, a):
    imp = a["impact"]
    lines = [f"🚨 <b>RADAR — {esc(e['source_label'])}</b>"]
    t = _fmt_hhmm(e["ts"])
    if t:
        lines.append(f"🕒 {t}")

    text = e["text"]
    if len(text) > 360:
        text = text[:357] + "…"
    lines.append(f"\n“{esc(text)}”")

    if a["tokens"]:
        toks = ", ".join(
            f"{esc(x['ticker'])}"
            + (f" ({esc(x['name'].title())})" if x["name"].lower() != x["ticker"].lower()
               and not x["name"].startswith("$") else "")
            for x in a["tokens"][:3]
        )
        lines.append(f"\n🎯 <b>Token(s): {toks}</b>")

    if imp["direction"] != "NEUTRAL":
        conf = int(round(imp["confidence"] * 100))
        lines.append(f"📊 Likely <b>{imp['direction']}</b> · confidence ~{conf}%")
        if imp["reasons"]:
            lines.append("   " + " · ".join(esc(r) for r in imp["reasons"][:3]))
    else:
        lines.append("📊 Direction unclear — flagged because it mentions crypto.")

    price = _token_price_line(a["tokens"])
    if price:
        lines.append(price)

    if e.get("url"):
        lines.append(f"🔗 <a href=\"{esc(e['url'])}\">source</a>")

    lines.append(
        "\n<i>Speed + detection, not a prophecy. Confirm on the chart "
        "(/analyze) and size with /risk before acting.</i>"
    )
    lines.append(f"{config.DISCLAIMER}")
    return "\n".join(lines)


# ============================================================================
# command handlers
# ============================================================================
HELP = (
    "<b>🤖 Crypto Trade Assistant</b>\n"
    "I help you trade with a <i>plan</i> — not guesses. I read charts, watch news, "
    "and now I run an <b>event radar</b> that pings you the moment a market-mover "
    "(Trump, big names, exchange listings) posts something crypto-related — with the "
    "token named and an honest bullish/bearish read. I never place trades.\n\n"
    "Every user has their own watchlist, risk settings, and alert preferences — "
    "changing yours never affects anyone else.\n\n"
    "<b>📡 Radar</b>\n"
    "/radar — show what's hot right now (or /radar on|off)\n"
    "/sources — what I'm watching &amp; whether each source is live\n"
    "/track &lt;handle&gt; — add an X/Twitter account (e.g. /track elonmusk)\n"
    "/untrack &lt;handle&gt; — stop watching an X account\n\n"
    "<b>📈 Analysis</b>\n"
    "/price &lt;coin&gt; — current price &amp; 24h stats\n"
    "/analyze &lt;coin&gt; [tf] — full analysis + trade plan (e.g. /analyze btc 4h)\n"
    "/signal &lt;coin&gt; — same as analyze\n"
    "/risk &lt;entry&gt; &lt;stop&gt; — position size using your defaults\n"
    "    or /risk &lt;account&gt; &lt;risk%&gt; &lt;entry&gt; &lt;stop&gt; [rr]\n"
    "/scan — scan your whole watchlist now for the best setups\n"
    "/news — latest market-moving headlines\n\n"
    "<b>⚙️ Setup</b>\n"
    "/watch &lt;coins&gt; — add coins · /unwatch · /watchlist\n"
    "/alerts on|off — auto signal &amp; news alerts (just for you)\n"
    "/settings — show/change your account, risk%, rr, timeframe\n\n"
    f"{config.DISCLAIMER}"
)


def cmd_start(chat_id, args):
    get_user(chat_id)  # ensures a per-user record exists
    add_subscriber(chat_id)
    send_message(chat_id, HELP)


def cmd_price(chat_id, args):
    if not args:
        return send_message(chat_id, "Usage: /price btc")
    try:
        send_message(chat_id, format_price(market.get_24h_stats(args[0])))
    except Exception as e:
        send_message(chat_id, f"Couldn't fetch {esc(args[0])}: {esc(e)}")


def cmd_analyze(chat_id, args):
    if not args:
        return send_message(chat_id, "Usage: /analyze btc  (optional timeframe: /analyze btc 1h)")
    coin = args[0]
    u = get_user(chat_id)
    s = u["settings"]
    tf = args[1] if len(args) > 1 else s["timeframe"]
    try:
        send_message(chat_id, "Analyzing… ⏳")
        a = strategy.analyze(coin, timeframe=tf,
                             account=s["account"], risk_pct=s["risk_pct"], rr=s["rr"])
        send_message(chat_id, format_analysis(a))
    except market.DataUnavailable:
        try:
            st = market.get_24h_stats(coin)
            send_message(chat_id,
                f"⚠️ I can’t build a reliable trade plan for <b>{esc(coin.upper())}</b> — "
                f"it doesn’t trade on any major exchange I track, so there’s no solid "
                f"chart data to analyze. Here’s its price instead:\n\n" + format_price(st))
        except Exception:
            send_message(chat_id,
                f"Couldn’t find <b>{esc(coin.upper())}</b> on any exchange or price "
                f"source. Double-check the ticker?")
    except Exception as e:
        send_message(chat_id, f"Couldn't analyze {esc(coin)}: {esc(e)}")


def cmd_risk(chat_id, args):
    u = get_user(chat_id)
    s = u["settings"]
    try:
        nums = [parse_num(x) for x in args]
    except ValueError:
        return send_message(chat_id, "Please give numbers, e.g. /risk 42000 41000")
    try:
        if len(nums) == 2:
            entry, sl = nums
            p = strategy.plan_trade(s["account"], s["risk_pct"], entry, sl, s["rr"])
        elif len(nums) == 4:
            acct, risk, entry, sl = nums
            p = strategy.plan_trade(acct, risk, entry, sl, s["rr"])
        elif len(nums) == 5:
            acct, risk, entry, sl, rr = nums
            p = strategy.plan_trade(acct, risk, entry, sl, rr)
        else:
            return send_message(chat_id,
                "Usage:\n/risk &lt;entry&gt; &lt;stop&gt;\n"
                "/risk &lt;account&gt; &lt;risk%&gt; &lt;entry&gt; &lt;stop&gt; [rr]")
        send_message(chat_id, format_risk(p))
    except Exception as e:
        send_message(chat_id, f"⚠️ {esc(e)}")


def cmd_watch(chat_id, args):
    if not args:
        return send_message(chat_id, "Usage: /watch sol avax link")
    def _mutate(u):
        for c in args:
            c = c.upper()
            if c not in u["watchlist"]:
                u["watchlist"].append(c)
    u = update_user(chat_id, _mutate)
    send_message(chat_id, f"✅ Watching: {esc(', '.join(u['watchlist']))}")


def cmd_unwatch(chat_id, args):
    if not args:
        return send_message(chat_id, "Usage: /unwatch sol")
    def _mutate(u):
        for c in args:
            c = c.upper()
            if c in u["watchlist"]:
                u["watchlist"].remove(c)
    u = update_user(chat_id, _mutate)
    wl = ", ".join(u["watchlist"]) or "(empty)"
    send_message(chat_id, f"Watchlist: {esc(wl)}")


def cmd_watchlist(chat_id, args):
    u = get_user(chat_id)
    wl = ", ".join(u["watchlist"]) or "(empty)"
    send_message(chat_id, f"👀 Watchlist: {esc(wl)}")


def cmd_news(chat_id, args):
    u = get_user(chat_id)
    try:
        heads = news_mod.fetch_headlines(limit=25)
        rel = news_mod.filter_relevant(heads, u["watchlist"]) or heads
        send_message(chat_id, format_news(rel))
    except Exception as e:
        send_message(chat_id, f"Couldn't fetch news: {esc(e)}")


def cmd_alerts(chat_id, args):
    if not args or args[0].lower() not in ("on", "off"):
        return send_message(chat_id, "Usage: /alerts on   or   /alerts off")
    on = args[0].lower() == "on"
    def _mutate(u):
        u["alerts_on"] = on
    update_user(chat_id, _mutate)
    if on:
        add_subscriber(chat_id)
    send_message(chat_id, f"🔔 Alerts turned {'ON' if on else 'OFF'} (just for you).")


def cmd_settings(chat_id, args):
    u = get_user(chat_id)
    s = u["settings"]
    if not args:
        msg = ("<b>Your settings</b>\n"
               f"account: ${s['account']:,.0f}\n"
               f"risk_pct: {s['risk_pct']:g}%\n"
               f"rr: {s['rr']:g}\n"
               f"timeframe: {s['timeframe']}\n\n"
               "Change with e.g. /settings risk 1.5, /settings account 5000, "
               "/settings rr 2.5, /settings timeframe 1h")
        return send_message(chat_id, msg)
    if len(args) < 2:
        return send_message(chat_id, "Usage: /settings risk 1.5")
    key, val = args[0].lower(), args[1]
    keymap = {"account": "account", "risk": "risk_pct", "risk_pct": "risk_pct",
              "rr": "rr", "timeframe": "timeframe", "tf": "timeframe"}
    if key not in keymap:
        return send_message(chat_id, "Unknown setting. Options: account, risk, rr, timeframe")
    field = keymap[key]
    try:
        parsed = val if field == "timeframe" else parse_num(val)
    except ValueError:
        return send_message(chat_id, "That value doesn't look like a number.")
    def _mutate(u):
        u["settings"][field] = parsed
    update_user(chat_id, _mutate)
    send_message(chat_id, f"✅ {esc(field)} set to {esc(parsed)} (just for you)")


def cmd_scan(chat_id, args):
    u = get_user(chat_id)
    wl = u["watchlist"]
    if not wl:
        return send_message(chat_id, "Your watchlist is empty. Add coins with /watch btc eth")
    send_message(chat_id, f"🔎 Scanning {len(wl)} coins…")
    s = u["settings"]
    results = []
    for coin in wl:
        try:
            a = strategy.analyze(coin, timeframe=s["timeframe"],
                                 account=s["account"], risk_pct=s["risk_pct"], rr=s["rr"])
            results.append(a)
        except Exception:
            continue
    if not results:
        return send_message(chat_id, "Scan failed — could not fetch data.")
    results.sort(key=lambda a: abs(a["score"]), reverse=True)
    lines = ["<b>🔎 Scan results</b> (strongest setups first)"]
    for a in results:
        sign = "+" if a["score"] >= 0 else ""
        tag = a["direction"] if a["direction"] != "NEUTRAL" else "wait"
        lines.append(f"• <b>{esc(a['coin'])}</b>: {tag} (score {sign}{a['score']}, "
                     f"{esc(a['trend'])})")
    lines.append("\nUse /analyze &lt;coin&gt; for the full plan on any of these.")
    send_message(chat_id, "\n".join(lines))


def cmd_radar(chat_id, args):
    if args and args[0].lower() in ("on", "off"):
        on = args[0].lower() == "on"
        def _mutate(u):
            u["radar_on"] = on
        update_user(chat_id, _mutate)
        if on:
            add_subscriber(chat_id)
        return send_message(chat_id, f"📡 Radar auto-alerts turned {'ON' if on else 'OFF'} (just for you).")

    send_message(chat_id, "📡 Scanning influencer & event radar…")
    with _STATE_LOCK:
        extra_x = list(STATE.get("tracked_x", []))
    try:
        events = radar.collect_events(extra_x_handles=extra_x)
    except Exception as ex:
        return send_message(chat_id, f"Radar error: {esc(ex)}")
    if not events:
        return send_message(chat_id,
            "Radar is quiet right now (or the free sources are blocked from here). "
            "It keeps watching in the background and will ping you on anything new.")
    scored = []
    for e in events[:40]:
        a = nlp.analyze_text(e["text"])
        rank = a["relevance"] + (0.6 if a["tokens"] else 0.0)
        scored.append((rank, e, a))
    scored.sort(key=lambda x: (x[0], x[1]["ts"]), reverse=True)

    lines = ["<b>📡 Radar — most relevant right now</b>"]
    for rank, e, a in scored[:8]:
        imp = a["impact"]
        de = _DIR_EMOJI.get(imp["direction"], "⚪")
        tok = a["tokens"][0]["ticker"] if a["tokens"] else "—"
        snippet = e["text"][:90] + ("…" if len(e["text"]) > 90 else "")
        head = f"{de} <b>{esc(tok)}</b> · {esc(e['source_label'])}"
        if e.get("url"):
            head = f"{de} <b>{esc(tok)}</b> · <a href=\"{esc(e['url'])}\">{esc(e['source_label'])}</a>"
        lines.append(f"\n{head}\n<i>{esc(snippet)}</i>")
    lines.append("\nI’ll auto-ping the moment something new drops. /sources shows what I’m watching.")
    send_message(chat_id, "\n".join(lines))


def cmd_track(chat_id, args):
    if not args:
        return send_message(chat_id,
            "Usage: /track elonmusk cz_binance  (adds X/Twitter handles to the radar)")
    with _STATE_LOCK:
        tracked = STATE.setdefault("tracked_x", [])
        for h in args:
            h = h.lstrip("@")
            if h not in tracked:
                tracked.append(h)
        save_state(STATE)
        allx = ", ".join("@" + h for h in (list(config.X_HANDLES) + tracked))
    note = ""
    if not getattr(config, "NITTER_INSTANCES", []):
        note = ("\n⚠️ Heads-up: X/Twitter needs a working Nitter mirror in config "
                "(the free X API is gone). Trump on Truth Social works without it. "
                "See README → “Watching X”.")
    send_message(chat_id, f"✅ X watchlist: {esc(allx)}{note}")


def cmd_untrack(chat_id, args):
    if not args:
        return send_message(chat_id, "Usage: /untrack elonmusk")
    with _STATE_LOCK:
        tracked = STATE.setdefault("tracked_x", [])
        for h in args:
            h = h.lstrip("@")
            if h in tracked:
                tracked.remove(h)
        save_state(STATE)
        tx = ", ".join("@" + h for h in tracked) or "(none extra)"
    send_message(chat_id, f"Removed. Your added X handles: {esc(tx)}")


def cmd_sources(chat_id, args):
    u = get_user(chat_id)
    with _STATE_LOCK:
        extra_x = list(STATE.get("tracked_x", []))
    st = radar.source_status(extra_x_handles=extra_x)
    lines = [f"<b>📡 Radar sources</b> (your auto-alerts: {'ON' if u['radar_on'] else 'OFF'}, "
             f"every ~{config.RADAR_SCAN_INTERVAL_SEC}s)"]
    labels = {"truth_social": "Truth Social", "exchange_listings": "Exchange listings",
              "news": "Crypto news", "x": "X / Twitter"}
    for key, label in labels.items():
        info = st[key]
        dot = "🟢" if info["on"] else "⚪"
        lines.append(f"{dot} <b>{esc(label)}</b> — {esc(info['detail'])}")
    lines.append("\nToggle with /radar on|off · add people with /track &lt;handle&gt;")
    send_message(chat_id, "\n".join(lines))


def cmd_help(chat_id, args):
    send_message(chat_id, HELP)


HANDLERS = {
    "start": cmd_start, "help": cmd_help,
    "price": cmd_price,
    "analyze": cmd_analyze, "signal": cmd_analyze,
    "risk": cmd_risk,
    "watch": cmd_watch, "unwatch": cmd_unwatch, "watchlist": cmd_watchlist,
    "news": cmd_news, "alerts": cmd_alerts, "settings": cmd_settings,
    "scan": cmd_scan,
    "radar": cmd_radar, "track": cmd_track, "untrack": cmd_untrack,
    "sources": cmd_sources,
}


def dispatch(update):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text:
        return
    if not text.startswith("/"):
        return send_message(chat_id, "Send /help to see what I can do.")
    parts = text.split()
    cmd = parts[0].lstrip("/").split("@")[0].lower()
    args = parts[1:]
    print(f"> got: /{cmd} {' '.join(args)}".rstrip(), flush=True)
    handler = HANDLERS.get(cmd)
    if handler:
        try:
            handler(chat_id, args)
        except Exception:
            traceback.print_exc()
            send_message(chat_id, "Something went wrong handling that. Try again.")
    else:
        send_message(chat_id, "Unknown command. Send /help.")


# ============================================================================
# background scanner (signals + news)
# ============================================================================
def scanner_loop():
    last_market = 0.0
    last_news = 0.0
    last_radar = 0.0
    while True:
        try:
            now = time.time()

            if now - last_radar >= config.RADAR_SCAN_INTERVAL_SEC:
                last_radar = now
                scan_radar_and_alert()

            if now - last_market >= config.SCAN_INTERVAL_MIN * 60:
                last_market = now
                scan_market_and_alert()

            if now - last_news >= config.NEWS_SCAN_INTERVAL_MIN * 60:
                last_news = now
                scan_news_and_alert()
        except Exception:
            traceback.print_exc()
        time.sleep(10)


def scan_market_and_alert():
    """
    Per-user scan: each user has their own watchlist/settings, so we loop
    per user (only those with alerts_on) rather than one shared watchlist.
    """
    users = {cid: u for cid, u in all_users_snapshot().items() if u.get("alerts_on")}
    for chat_id, u in users.items():
        wl = u["watchlist"]
        s = u["settings"]
        last_sig = dict(u.get("last_signal", {}))
        touched = False
        for coin in wl:
            try:
                a = strategy.analyze(coin, timeframe=s["timeframe"],
                                     account=s["account"], risk_pct=s["risk_pct"], rr=s["rr"])
            except Exception:
                continue
            if a["direction"] == "NEUTRAL" or abs(a["score"]) < config.MIN_SCORE_ALERT:
                continue
            prev = last_sig.get(a["symbol"])
            if prev == a["score"]:
                continue
            last_sig[a["symbol"]] = a["score"]
            touched = True
            send_message(chat_id, "🚨 <b>Signal alert</b>\n" + format_analysis(a))
        if touched:
            def _mutate(uu, ls=last_sig):
                uu["last_signal"] = ls
            update_user(chat_id, _mutate)


def scan_news_and_alert():
    """
    News dedup (seen_news) stays global — headlines are the same for everyone.
    But which users get pinged, and which watchlist decides relevance, is
    per-user.
    """
    with _STATE_LOCK:
        seen = set(STATE.get("seen_news", []))
    try:
        heads = news_mod.fetch_headlines(limit=30)
    except Exception:
        return
    fresh_ids = set()
    users = {cid: u for cid, u in all_users_snapshot().items() if u.get("alerts_on")}
    for chat_id, u in users.items():
        rel = news_mod.filter_relevant(heads, u["watchlist"])
        fresh = [h for h in rel if h["id"] not in seen]
        for h in fresh[:5]:
            send_message(chat_id, format_news([h], header=f"📰 News · {h.get('matched','crypto')}"))
            fresh_ids.add(h["id"])
    with _STATE_LOCK:
        seen |= fresh_ids
        STATE["seen_news"] = sorted(seen)[-500:]
        save_state(STATE)


def _should_alert(e, a):
    src = e["source"]
    has_token = bool(a["tokens"])
    directional = a["impact"]["direction"] != "NEUTRAL"
    if src in ("binance_listing", "exchange_listing"):
        return True
    if src in ("truth_social", "x"):
        return has_token or a["relevance"] >= config.RADAR_MIN_RELEVANCE
    if src == "news":
        return has_token or directional
    return has_token


def scan_radar_and_alert():
    """
    The radar feed itself (seen_radar dedup, seeding) stays global — it's one
    shared external feed. Which users actually get pinged is per-user
    (radar_on).
    """
    with _STATE_LOCK:
        seen = set(STATE.get("seen_radar", []))
        seeded = STATE.get("radar_seeded", False)
        extra_x = list(STATE.get("tracked_x", []))
    try:
        events = radar.collect_events(extra_x_handles=extra_x)
    except Exception:
        traceback.print_exc()
        return
    if not events:
        return

    if not seeded:
        with _STATE_LOCK:
            STATE["seen_radar"] = [e["id"] for e in events][:1000]
            STATE["radar_seeded"] = True
            save_state(STATE)
        print(f"Radar seeded with {len(events)} existing items (no history spam).")
        return

    fresh = [e for e in events if e["id"] not in seen]
    fresh.sort(key=lambda e: e["ts"])
    sent = 0
    for e in fresh:
        a = nlp.analyze_text(e["text"])
        if _should_alert(e, a) and sent < 6:
            try:
                broadcast(format_event_alert(e, a), predicate=lambda u: u.get("radar_on"))
                sent += 1
            except Exception:
                traceback.print_exc()
        seen.add(e["id"])
    with _STATE_LOCK:
        STATE["seen_radar"] = sorted(seen)[-1000:]
        save_state(STATE)


# ============================================================================
# main long-polling loop
# ============================================================================
def main():
    if not config.TELEGRAM_BOT_TOKEN or "paste-your-token" in config.TELEGRAM_BOT_TOKEN:
        print("=" * 60)
        print(" No Telegram token found.")
        print(" 1) Message @BotFather on Telegram and create a bot")
        print(" 2) Copy .env.example to .env")
        print(" 3) Paste the token into .env as TELEGRAM_BOT_TOKEN")
        print(" See README.md for step-by-step help.")
        print("=" * 60)
        return

    print("Crypto Trade Assistant bot is running. Press Ctrl+C to stop.")

    register_commands()

    def _warm_coins():
        try:
            ok, msg = nlp.refresh_coin_cache()
            print(f"Coin list: {msg}" if ok else f"Coin list: using built-in map ({msg})")
        except Exception:
            pass
    threading.Thread(target=_warm_coins, daemon=True).start()
    threading.Thread(target=scanner_loop, daemon=True).start()

    offset = None
    conflict_warned = False
    while True:
        try:
            r = requests.get(API + "getUpdates",
                             params={"timeout": 50, "offset": offset},
                             timeout=60)
            data_json = r.json()
            if not data_json.get("ok"):
                if data_json.get("error_code") == 409:
                    if not conflict_warned:
                        print("!" * 64)
                        print(" CONFLICT (409): another copy of this bot is already running")
                        print(" on this same token. This makes commands slow & unreliable.")
                        print(" Telegram says:", data_json.get("description"))
                        print(" Close the OTHER copy so ONLY this one runs:")
                        print("   • the old Windows PC bot (start-bot.bat / a python window)")
                        print("   • a second Termux session/tab")
                        print("   • the GitHub Actions workflow (must be Disabled)")
                        print("!" * 64, flush=True)
                        conflict_warned = True
                else:
                    print("getUpdates not ok:", data_json.get("description"), flush=True)
                time.sleep(3)
                continue
            if conflict_warned:
                print("Conflict cleared — this is now the only bot. ✅", flush=True)
                conflict_warned = False
            for update in data_json["result"]:
                offset = update["update_id"] + 1
                threading.Thread(target=dispatch, args=(update,), daemon=True).start()
        except requests.RequestException:
            time.sleep(3)
        except KeyboardInterrupt:
            print("\nStopping. Bye!")
            break
        except Exception:
            traceback.print_exc()
            time.sleep(3)


if __name__ == "__main__":
    main()
