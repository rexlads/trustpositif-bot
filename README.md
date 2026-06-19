# TrustPositif Domain Checker → Telegram

Checks a list of domains against the Indonesian TrustPositif / Komdigi blocklist
(via a third-party checker that reflects the official list) and posts a batched
report to your Telegram channel. Each report links back to the official site
(https://trustpositif.komdigi.go.id/) so you can verify anything flagged.

> ⚠️ **Before you do anything:** if you ever pasted your bot token anywhere public
> (chat, screenshot, repo), open Telegram → @BotFather → `/revoke` → get a NEW token.

---

## Status: one piece needs finalizing

`checker.py` contains a function `check_domain()` written for the *most likely*
request format of the Orion checker. The exact field name and the
blocked/not-blocked wording must be confirmed from the site's Network tab
(see the comments marked `>>>` in `checker.py`). Once tuned, it's done.

---

## Option 1 — GitHub Actions (recommended: free, no server)

1. **Create a new GitHub repo** (private is fine). Upload all these files,
   keeping the `.github/workflows/check.yml` path intact.

2. **Add your secrets:** repo → **Settings → Secrets and variables → Actions →
   New repository secret**. Add three:
   - `BOT_TOKEN`  → your fresh token from BotFather
   - `CHANNEL_ID` → `-1004473967915`
   - `DOMAINS`    → your 20 domains, comma-separated, e.g. `a.com,b.com,c.com`

3. **Make sure the bot can post:** add your bot to the channel as an
   **administrator** with "Post messages" permission.

4. **Set the interval:** edit the `cron` line in `.github/workflows/check.yml`.
   Default is every 10 minutes. (GitHub's minimum is ~5 min and scheduled runs
   can be delayed a few minutes under load — normal for free cron.)

5. **Test now:** repo → **Actions** tab → "TrustPositif Check" → **Run workflow**.
   Watch the log; you should get Telegram messages within a minute.

**Toggle / pause:** Actions tab → the workflow → **⋯ → Disable workflow**.
**Change frequency:** edit the cron line and commit.

---

## Option 2 — Always-on VPS (true 10-min precision)

```bash
git clone <your-repo>            # or upload the files
cd trustpositif-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt python-dotenv

cp .env.example .env
nano .env                        # fill in BOT_TOKEN, CHANNEL_ID, DOMAINS, INTERVAL_MINUTES

python run_loop.py               # runs forever, every INTERVAL_MINUTES
```

To keep it running after logout, create a systemd service (ask and I'll generate
the unit file for your paths), or quick-and-dirty: `nohup python run_loop.py &`.

A single run (no loop) for testing:
```bash
set -a; source .env; set +a
python checker.py
```

---

## Report format

```
TrustPositif Check — Part 1/4
🔴 baddomain.com — Appears on the blocklist
🟢 gooddomain.com — Not on the blocklist
...
Summary
🔴 Blocked: 2   🟢 Safe: 17   ⚠️ Issues: 1
Verify manually at https://trustpositif.komdigi.go.id/
```

- `BATCH_SIZE` controls domains per message (default 5 → 20 domains = 4 parts).
- `ONLY_BLOCKED=1` reports only blocked/problem domains plus a short all-clear
  when everything is fine.

---

## Notes & honest caveats

- This uses a **third-party** checker (Architecture C), so freshness/accuracy
  depend on that service. The official link is included for manual verification.
- The official Komdigi site blocks automation and is IP-restricted to Indonesia,
  which is exactly why we don't scrape it directly.
- Be reasonable with frequency. Every 10 minutes against a free public tool is
  fine; every 30 seconds is abusive and may get you blocked.
