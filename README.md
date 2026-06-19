# TrustPositif Domain Checker → Telegram

Checks domains against the Indonesian TrustPositif / Komdigi blocklist (via a
third-party checker that reflects the official list) and posts the results to
your Telegram channel. Domains are organised into **groups** (`Ary`, `AS`,
`BD`, `SV`) and the bot sends **one Telegram message per group**.

> ⚠️ **Before you do anything:** if you ever pasted your bot token anywhere public
> (chat, screenshot, repo), open Telegram → @BotFather → `/revoke` → get a NEW token.

---

## Web panel — manage your domains without touching code

A self-contained control panel lives at `docs/index.html`. From it you can:
- add / remove domains in each of the four groups (`Ary`, `AS`, `BD`, `SV`),
- save the lists straight to `domains.json` in this repo (one commit per save),
- press **Cek Sekarang** to run the check immediately,
- see the status of the last few runs.

The bot sends one Telegram message per group, so you get four separate reports.

### Enable the panel (free, on GitHub Pages)

GitHub Pages is free **for public repositories** (private repos need a paid
plan). Pages and reliable 10-minute Actions both work best on a public repo, so:

1. **Make the repo public** *(recommended)*: repo → **Settings → General →
   Danger Zone → Change visibility → Public**. Your bot token stays safe — it
   lives in GitHub Secrets, not in the code. Only `domains.json` becomes visible.
2. **Turn on Pages:** repo → **Settings → Pages → Build and deployment → Source:
   Deploy from a branch → Branch: `main` / folder: `/docs` → Save.**
3. Open the URL Pages gives you (e.g. `https://rexlads.github.io/trustpositif-bot/`).
4. In the panel, create a **fine-grained token** (the panel explains how) with
   **Contents: Read/write** and **Actions: Read/write** for this repo, paste it,
   and you're in. The token is stored only in your browser.

---

## Status: one piece needs finalizing

`checker.py` contains a function `check_domain()` written for the *most likely*
request format of the Orion checker. The exact field name and the
blocked/not-blocked wording must be confirmed from the site's Network tab
(see the comments marked `>>>` in `checker.py`). Once tuned, it's done.

---

## Option 1 — GitHub Actions (recommended: free, no server)

1. **Upload these files** to your repo, keeping the
   `.github/workflows/check.yml` path intact. **Public repo is recommended**
   (free unlimited Actions + free Pages for the panel).

2. **Add your secrets:** repo → **Settings → Secrets and variables → Actions →
   New repository secret**. Add two:
   - `BOT_TOKEN`  → your fresh token from BotFather
   - `CHANNEL_ID` → `-1004473967915`

   > `DOMAINS` is **no longer required** — the domain list now lives in
   > `domains.json` (edited via the panel). You can still set `DOMAINS` as an
   > optional fallback if `domains.json` is missing.

3. **Make sure the bot can post:** add your bot to the channel as an
   **administrator** with "Post messages" permission.

4. **Set the interval:** edit the `cron` line in `.github/workflows/check.yml`.
   Default is every 10 minutes. (GitHub's minimum is ~5 min and scheduled runs
   can be delayed a few minutes under load — normal for free cron. On a
   **private** repo, every 10 min will exhaust the free Actions quota, which is
   why a public repo is recommended.)

5. **Test now:** repo → **Actions** tab → "TrustPositif Check" → **Run workflow**
   (or press **Cek Sekarang** in the panel). You should get Telegram messages
   within a minute.

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

One message is sent per group (`Ary`, `AS`, `BD`, `SV`):

```
🛡️ TrustPositif — Ary
🔴 baddomain.com — Appears on the blocklist
🟢 gooddomain.com — Not on the blocklist

🔴 1  🟢 1  ⚠️ 0
```

- Domains and their groups are stored in `domains.json` and edited via the panel.
- `ONLY_BLOCKED=1` reports only blocked/problem domains; a group with nothing to
  report sends a short "Semua aman" message instead.

---

## Notes & honest caveats

- This uses a **third-party** checker (Architecture C), so freshness/accuracy
  depend on that service. The official link is included for manual verification.
- The official Komdigi site blocks automation and is IP-restricted to Indonesia,
  which is exactly why we don't scrape it directly.
- Be reasonable with frequency. Every 10 minutes against a free public tool is
  fine; every 30 seconds is abusive and may get you blocked.
