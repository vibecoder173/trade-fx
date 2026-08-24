# 🤖 Crypto Trade Assistant Bot

A Telegram bot that helps you trade crypto **with a plan instead of guesses**. It
reads charts, watches the news, and turns every idea into a risk-managed setup
with a clear entry, stop-loss, take-profit, and position size.

> ### Read this first — honest expectations
> - **This is not financial advice**, and it is **not** a magic money machine.
> - **No tool can predict the market perfectly.** Anything promising "signals
>   with no losses" is misleading you. This bot gives *probabilities and plans*,
>   not guarantees.
> - **The real edge is discipline.** Beginners lose because they trade with no
>   plan and no risk control — not because they lack secret signals. This bot's
>   main job is to fix exactly that.
> - **It never places trades.** It only informs and alerts. You stay in control.

---

## What it does

- **📡 Event Radar (NEW)** — the "be first" system. It watches market-movers
  (Donald Trump on Truth Social, big crypto names, exchange listings, breaking
  news) and pings you the moment something crypto-related drops — naming the
  **token** involved and giving an honest **bullish/bearish read with a
  confidence score**. See the dedicated section below.
- **📊 Analysis + trade plan** — for any coin: trend, RSI, MACD, Bollinger,
  support/resistance, candlestick patterns, and a probabilistic LONG/SHORT/NO-TRADE
  call, plus a full plan (entry / stop / target / size).
- **🧮 Risk engine** — tells you exactly how many coins to buy so you only risk a
  small fixed % of your account per trade. This is the single most important tool
  for surviving.
- **🔎 Watchlist scanning** — checks your coins automatically and alerts you when a
  strong setup appears.
- **📰 News alerts** — pulls free crypto news and pings you on market-moving
  headlines (SEC, ETFs, hacks, listings, etc.).

---

## 📡 Event Radar — be first to market-movers

You asked for a bot that catches when someone like Trump posts something
crypto-related — even 1% — tells you *which token* they mean, and pings you fast
enough to act (like the "Hyperliquid is coming to the US" moment). That's the
radar.

**How it works:** every ~60 seconds it polls fast, free sources. For each new
post/announcement it (1) extracts the token(s) mentioned, (2) estimates likely
direction with a confidence score and plain-English reasons, and (3) if it clears
the bar, sends you an instant alert with the token's live price so you can act.

> **The honest part — please read.** No engine can predict *direction* with "1%
> error"; if one could, its owner would quietly own the market. So we aim for
> near-perfect on the parts we *can* control — **speed** (catching the post fast)
> and **detection** (correctly identifying the post and the token) — and treat the
> direction as a *probability*, never a promise. Confidence is capped below 100% on
> purpose. Always confirm on the chart (`/analyze`) and size with `/risk` before
> acting.

### Radar commands

| Command | What it does |
|---|---|
| `/radar` | Show the most relevant things on the radar right now |
| `/radar on` / `/radar off` | Turn the automatic radar pings on/off |
| `/sources` | Show every source and whether it's live |
| `/track elonmusk` | Add an X/Twitter handle to watch (see caveat below) |
| `/untrack elonmusk` | Stop watching an X handle |

### What's watched (and how well it works for free)

- **🟢 Truth Social (Trump) — works out of the box.** Uses Truth Social's public
  API, no key needed. Trump's account is already configured.
- **🟢 Crypto news (SEC / ETF / Fed / hacks) — works.** Free RSS from CoinDesk,
  Cointelegraph, Decrypt, Bitcoin Magazine.
- **🟡 Exchange listings — mostly works.** Binance new-listing feed + listing RSS.
  Some endpoints are occasionally geo/Cloudflare-blocked; it fails quietly if so.
- **⚪ X / Twitter (Elon, CZ, etc.) — the honest catch.** X shut off free API
  access. So X handles are only polled if you add a working **Nitter mirror** in
  `config.py` (`NITTER_INSTANCES`). Most public mirrors are unreliable. Until then,
  the *names* are pre-configured but X stays quiet — Truth Social + news still
  cover a lot. If you want rock-solid X later, a cheap paid feed can be plugged in.

### Add more people to watch

- **X/Twitter:** `/track <handle>` (e.g. `/track saylor`). Only fires once a Nitter
  mirror is set (above).
- **Truth Social:** open `config.py` → `TRUTH_SOCIAL_ACCOUNTS` and add
  `{"handle": "@name", "id": "NUMERIC_ID"}`. To find the numeric id, open the
  person's Truth Social profile and view
  `https://truthsocial.com/api/v1/accounts/lookup?acct=THEIR_USERNAME` — the `id`
  field is the number you need.

### Tuning

In `config.py`: `RADAR_SCAN_INTERVAL_SEC` (how often to poll), `RADAR_SOURCES`
(turn each source on/off), and `RADAR_MIN_RELEVANCE` (how crypto-related an
influencer post must be to ping you — lower = more sensitive).

---

## Setup (about 10 minutes)

### 1. Install Python
Download Python 3.10 or newer from <https://www.python.org/downloads/>.
**On Windows, tick "Add Python to PATH"** on the first screen of the installer.

### 2. Install the bot's dependencies
Open a terminal (Windows: search **"PowerShell"**; Mac: **"Terminal"**), then go
into this folder and install the requirements:

```
cd path/to/crypto-trade-assistant-bot
```
Windows:
```
py -m pip install -r requirements.txt
```
Mac/Linux:
```
python3 -m pip install -r requirements.txt
```

### 3. Create your Telegram bot (get a token)
1. Open Telegram and search for **@BotFather** (the one with the blue check).
2. Send `/newbot`.
3. Choose a name (e.g. *My Trade Assistant*) and a username ending in `bot`.
4. BotFather replies with a **token** that looks like
   `123456789:AAF...`. Copy it.

### 4. Add your token to the bot
1. In this folder, make a copy of **`.env.example`** and rename the copy to
   **`.env`**.
2. Open `.env` in Notepad and paste your token:
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAF-your-real-token
   ```
3. Save the file.

### 5. Run it
Windows:
```
py bot.py
```
Mac/Linux:
```
python3 bot.py
```
You should see *"Crypto Trade Assistant bot is running."* Leave this window open
— the bot works only while it's running.

> **Windows note:** if `py` says *"not recognized"*, use `python` instead
> (e.g. `python bot.py` and `python -m pip install -r requirements.txt`). The
> included **`start-bot.bat`** just double-clicks to launch it for you.

### 6. Say hello
Open Telegram, find the bot you just created, and send **`/start`**. 🎉

---

## Commands

| Command | What it does |
|---|---|
| `/radar` | Show what's hot on the radar (or `/radar on`/`/radar off`) |
| `/sources` | Show radar sources & whether each is live |
| `/track elonmusk` | Add an X handle to the radar · `/untrack` to remove |
| `/price btc` | Current price & 24h stats |
| `/analyze btc` | Full analysis + trade plan (add a timeframe: `/analyze btc 1h`) |
| `/signal btc` | Same as `/analyze` |
| `/risk 42000 41000` | Position size for entry 42000, stop 41000 (uses your defaults) |
| `/risk 5000 1 42000 41000 2` | account 5000, risk 1%, entry, stop, R:R 2 |
| `/scan` | Scan your whole watchlist and rank the best setups now |
| `/watch sol avax` | Add coins to your watchlist |
| `/unwatch sol` | Remove a coin |
| `/watchlist` | Show watched coins |
| `/news` | Latest market-moving headlines |
| `/alerts on` / `/alerts off` | Turn automatic alerts on/off |
| `/settings` | Show settings; e.g. `/settings risk 1.5` to change risk % |

---

## How to read a signal (important)

The **score** is a transparent count of technical conditions lining up in one
direction (trend, momentum, structure, patterns). It is **not** a probability of
profit — think of it as *"how many things agree right now."* A higher score means
a cleaner setup, never a sure thing.

The part that actually protects you is the **trade plan**: a stop-loss placed at a
level that invalidates the idea, a target at a sensible reward:risk, and a
position size that caps your loss at a small % of your account. Follow the plan,
and one bad trade can't wipe you out. That is the whole game.

**Golden rules the bot is built around:**
1. Never risk more than 1–2% of your account on a single trade.
2. Always set the stop-loss *before* you enter, and don't move it wider.
3. If there's no clear setup (NO TRADE), the right move is to wait.

---

## Configuration

Open **`config.py`** to change defaults (all optional):

- `DEFAULT_WATCHLIST` — coins scanned for alerts.
- `DEFAULT_TIMEFRAME` — analysis candle size (`15m`, `1h`, `4h`, `1d`, …).
- `DEFAULT_RISK_PCT` — % of account risked per trade.
- `DEFAULT_RR` — reward-to-risk ratio for targets.
- `SCAN_INTERVAL_MIN` / `NEWS_SCAN_INTERVAL_MIN` — how often it checks.
- `MIN_SCORE_ALERT` — how strong a setup must be to auto-alert.

You can also change these live from Telegram with `/settings`.

---

## Keeping it running 24/7

The bot works while it's running somewhere. Options, cheapest first:

- **Free, no PC, no card — GitHub Actions.** Runs on GitHub's servers on a ~5-min
  timer, so it pings your phone around the clock for **$0**. Alerts are "every few
  minutes" rather than instant. Full step-by-step in **`DEPLOY_GITHUB.md`**.
- **Free + instant — a spare Android phone.** Install the free Termux app and run
  `python bot.py` on an old phone left plugged in on WiFi. Real-time, full bot, $0.
- **Rock-solid — a ~$5/month server (VPS).** Any "run a Python script on a VPS"
  guide applies; the command is still `python bot.py`. Best if you want instant
  alerts without keeping a phone on.
- **Simplest for testing — your own PC.** Just run it; alerts stop when the PC is
  off.

For the GitHub route the bot runs in short bursts via **`run_once.py`** instead of
looping; you don't run that yourself — the included workflow does.

---

## Troubleshooting

- **"No Telegram token found"** — you skipped Step 4, or the file is named
  `.env.txt` instead of `.env`. Make sure the file is exactly `.env`.
- **"No module named ..."** — re-run Step 2 (dependency install).
- **"Binance rejected the request (bad symbol?)"** — that coin isn't on Binance
  spot, or you typed it wrong. Try the plain ticker, e.g. `sol`, not `solana`.
- **Bot doesn't reply** — make sure the terminal still shows it running, and that
  you messaged the correct bot username from Step 3.
- **Radar is always quiet / `/radar` finds nothing** — the free sources may be
  blocked from your network/region, or simply nothing crypto-related has been
  posted yet. On first launch the radar *seeds* silently (it learns what's already
  out there without spamming you), then alerts only on genuinely new posts.
- **No X/Twitter alerts** — expected until you set a working `NITTER_INSTANCES`
  entry in `config.py` (see the Event Radar section). Truth Social + news work
  without it.

---

## Ideas for later (roadmap)

- ✅ **Event radar** — influencer/listing/news monitoring with token extraction and
  a bullish/bearish read (done — this release).
- **Next: backtesting** so you can measure whether a setup actually has an edge on
  history before trusting it.
- **Next: stronger TA** — multi-timeframe confluence, more patterns (double
  top/bottom, triangles), funding/open-interest, and volume-profile levels.
- Rock-solid X/Twitter coverage via a paid feed (optional).
- Discord version (the logic is reusable — only the messaging layer changes).

---

## ⚠️ Disclaimer

This software is for **education and information only**. It is **not financial
advice**. Cryptocurrency trading carries substantial risk, and you can lose some
or all of your money. Past performance and technical setups do not guarantee
future results. You are solely responsible for your own trading decisions. Never
trade with money you cannot afford to lose, and always use a stop-loss.
