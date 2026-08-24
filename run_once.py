"""
run_once.py
-----------
Runs ONE check-and-reply cycle, then exits.

This is the version of the bot made for FREE hosting on GitHub Actions, which
runs code on a schedule instead of keeping a program on all the time. Every few
minutes GitHub runs this file, which:

  1. Reads any Telegram commands you sent since last time and replies to them.
  2. Runs the event radar (Trump / big names / listings) + market & news scans,
     and pushes any fresh alerts.
  3. Saves what it has seen to state.json (the workflow commits that back so the
     next run remembers it).

It reuses everything in bot.py — the same handlers, the same scan logic — it just
doesn't loop forever.

The bot token is read from the TELEGRAM_BOT_TOKEN environment variable, which on
GitHub is an encrypted Actions *secret*. The token is NEVER stored in the repo.

You can also run this locally to do a single pass:  python run_once.py
"""

import time
import traceback

import requests

import config
import bot   # reuse handlers, scan functions, state helpers (no loop starts on import)

# Safety cap: how many 100-message batches to drain in one run.
_MAX_UPDATE_BATCHES = 10


def drain_commands() -> int:
    """Fetch every pending Telegram command (short poll) and handle it.

    We persist the update offset in state.json so the next run continues exactly
    where this one stopped — no missed or double-processed messages.
    """
    offset = bot.STATE.get("update_offset")
    handled = 0
    for _ in range(_MAX_UPDATE_BATCHES):
        try:
            r = requests.get(
                bot.API + "getUpdates",
                params={"timeout": 0, "offset": offset, "limit": 100},
                timeout=30,
            )
            j = r.json()
        except Exception:
            traceback.print_exc()
            break
        if not j.get("ok"):
            print("getUpdates not ok:", str(j)[:160])
            break
        updates = j.get("result", [])
        if not updates:
            break
        for u in updates:
            offset = u["update_id"] + 1
            try:
                bot.dispatch(u)
                handled += 1
            except Exception:
                traceback.print_exc()
        if len(updates) < 100:
            break

    if offset is not None:
        with bot._STATE_LOCK:
            bot.STATE["update_offset"] = offset
            bot.save_state(bot.STATE)
    return handled


def run_scans() -> None:
    """Run the radar + (if alerts are on) market and news scans, one pass each.

    Each of these de-duplicates internally (seen_radar / seen_news / last_signal),
    so running them every cycle is safe — you won't get repeat alerts.
    """
    if bot.STATE.get("radar_on", True):
        try:
            bot.scan_radar_and_alert()
        except Exception:
            traceback.print_exc()

    if bot.STATE.get("alerts_on", True):
        try:
            bot.scan_market_and_alert()
        except Exception:
            traceback.print_exc()
        try:
            bot.scan_news_and_alert()
        except Exception:
            traceback.print_exc()


def main() -> int:
    if not config.TELEGRAM_BOT_TOKEN:
        print("=" * 64)
        print(" No TELEGRAM_BOT_TOKEN found.")
        print(" On GitHub: repo → Settings → Secrets and variables → Actions →")
        print(" 'New repository secret', name it exactly TELEGRAM_BOT_TOKEN.")
        print("=" * 64)
        return 1

    # Make sure Telegram suggests our commands in the "/" menu. This only calls
    # the API the first time (or whenever the command list changes).
    try:
        bot.register_commands()
    except Exception:
        traceback.print_exc()

    started = time.time()
    print("run_once: draining commands…")
    n = drain_commands()
    print(f"run_once: handled {n} command(s).")

    print("run_once: running radar + scans…")
    run_scans()

    print(f"run_once: done in {time.time() - started:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
