# 🤖 Host your bot 24/7 for FREE on GitHub (no card, no PC)

This runs your bot on GitHub's servers on a timer, so it works around the clock
and you use it **only from your phone** — nothing of yours has to stay on. It's
**$0**, needs **no credit card**, and takes about **15 minutes** to set up.

### Honest expectations (please read)
- Alerts arrive on a schedule — **about every 5 minutes**, sometimes up to ~15
  when GitHub is busy. So it's "very fast," not "instant."
- Your commands (`/price`, `/analyze`, `/radar`) still work — the bot reads your
  messages and replies on its next run, so answers come within a few minutes
  rather than instantly.
- Everything else (Trump/news/listing radar, token detection, trade plans) works
  exactly the same.

> **The golden rule about your token:** it goes into a GitHub **"secret"** (an
> encrypted box), **never** into the code files. Do **not** upload your `.env`
> file. More on this in Step 3.

---

## Step 1 — Make a free GitHub account
Go to <https://github.com/signup> and sign up. It's free and does **not** ask for
a card. Verify your email.

---

## Step 2 — Create a repository (a home for the code)
1. Click the **+** (top-right) → **New repository**.
2. **Repository name:** `crypto-bot` (anything is fine).
3. Set it to **Public**.
   - *Why public?* GitHub gives **unlimited free run-time to public repos**, which
     is what lets it check every 5 minutes for free. Private repos get a monthly
     limit that would force a much slower schedule.
   - *Is that safe?* Yes — your **token is never in the code** (it goes in a secret
     in Step 4). The files here are just the bot's program, which is fine to share.
4. Click **Create repository**.

---

## Step 3 — Upload the bot files
1. On the new repo page, click **"uploading an existing file"** (or **Add file →
   Upload files**).
2. Open your bot folder on your PC, select **all the files EXCEPT `.env`**, and
   drag them into the browser. (You can skip `__pycache__` and `state.json` too —
   they're not needed and rebuild themselves.)

   > ⚠️ **Do NOT upload `.env`.** It contains your token, and this repo is public.
   > If you ever upload it by accident: open Telegram → BotFather → `/revoke` to
   > kill that token, get a fresh one, and update the secret in Step 4.

3. Make sure the **`.github` folder** made it up (it holds the schedule that runs
   the bot). If you dragged the whole folder it's included automatically.
4. Click **Commit changes**.

---

## Step 4 — Add your token as a secret
This is the safe place for your token.

1. In your repo, go to **Settings** (top menu) → **Secrets and variables** →
   **Actions**.
2. Click **New repository secret**.
3. **Name:** `TELEGRAM_BOT_TOKEN`  (spelled exactly like that).
4. **Secret / value:** paste your bot token from BotFather.
5. Click **Add secret**. Done — GitHub encrypts it and only the bot can read it.

---

## Step 5 — Turn it on
1. Click the **Actions** tab. If it asks, click **"I understand my workflows,
   enable them."**
2. On the left, click the **crypto-bot** workflow.
3. Click **Run workflow** → **Run workflow** (this does the very first run now
   instead of waiting).
4. After ~30–60 seconds it shows a green ✓. (A green check = it ran fine. If it's
   red, open it and send me what the log says.)

> The first run is special: the radar quietly "learns" what's already out there so
> it doesn't spam you with old posts. Real alerts start from the next run onward.

---

## Step 6 — Say hello from your phone
1. Open Telegram and send **`/start`** to your bot.
2. Wait for the next run (up to ~5 min) — it'll reply with the menu and switch on
   your alerts.
3. Try `/price btc` or `/radar`. 🎉

**That's it.** You can close everything. The bot now runs on GitHub 24/7, for
free, and pings your phone on its own.

---

## Living with it

**See what it's doing / logs:** the **Actions** tab lists every run. Click any run
→ the `run` job → "Run one bot cycle" to see its output.

**Make it faster or slower:** edit `.github/workflows/bot.yml`, the line
`- cron: "*/5 * * * *"`. `*/5` = every 5 min, `*/10` = every 10, `*/2` = every 2.
(Faster isn't always faster in practice — GitHub still batches scheduled runs.)

**Pause it:** Actions tab → crypto-bot → the **⋯** menu → **Disable workflow**.
Re-enable the same way.

**Add people to the radar / change coins:** just message the bot (`/track`,
`/watch`, `/settings`, `/radar off`) — same commands as always.

---

## Troubleshooting

- **The run is red / failed.** Open it and read the last lines.
  - *"No TELEGRAM_BOT_TOKEN found"* → the secret is missing or misspelled. It must
    be exactly `TELEGRAM_BOT_TOKEN` (Step 4).
  - *A dependency error* → make sure `requirements.txt` was uploaded.
- **Bot doesn't reply.** Did you send `/start`? Give it one cycle (~5 min). Check
  the Actions tab shows recent green runs.
- **Radar is always quiet.** Some free sources may be blocked from GitHub's
  servers, or nothing crypto-related has been posted yet. News + listings usually
  work well from there; the bot fails quietly on any source it can't reach.
- **Prices/analysis fail but radar works.** The market data has a built-in backup
  source for exactly this, but if both are blocked from GitHub's servers on a given
  day, `/price` and `/analyze` may hiccup while the radar keeps running.
- **It stopped running after a couple of months.** GitHub disables schedules on
  repos with no activity for 60 days. Ours commits state on active days so this is
  unlikely, but if it happens, just open the Actions tab and click **Run
  workflow** once to wake it up.

---

## Want truly instant alerts later?
This free setup is "every few minutes." If you later want *instant* (the moment
Trump posts) plus always-on live commands, the upgrade is a tiny always-on host —
either a spare Android phone running it via Termux (free, if you get one) or a
~$5/month server. The code already supports both; just ask and I'll switch it over.
