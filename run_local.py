#!/usr/bin/env python3
"""
REAL-TIME runner — run this on an Indonesian machine/RDP.

From an Indonesian IP the official Komdigi site (trustpositif.komdigi.go.id) is
reachable, so we can check each domain against it directly and get the SAME,
instant result you see when you check manually — no ~1-4h mirror lag.

What it does every INTERVAL_MINUTES:
  1. Pulls the latest domains.json + mentions.json from your GitHub repo
     (so you keep editing them from the web panel — nothing changes there).
  2. Checks every domain against the official site (falls back to the GitHub
     blocklist mirror if the official site can't be reached).
  3. Sends one Telegram message per group, @mentioning people on blocks.

Setup (Windows RDP):
  1) Install Python 3 from python.org (tick "Add Python to PATH").
  2) In this folder run:  pip install requests python-dotenv
  3) Copy .env.example to .env and fill in BOT_TOKEN, CHANNEL_ID.
  4) FIRST verify the official endpoint:  python run_local.py --test
     Paste the printed output back to me so I can lock in the parser.
  5) Run for real:  python run_local.py     (leave it running; Ctrl+C to stop)
"""

import os
import re
import sys
import time
import json
from urllib.parse import quote

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests

# checker.py reads BOT_TOKEN/CHANNEL_ID from the environment at import time, so
# load .env BEFORE importing it (done above).
import checker

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GH_OWNER = os.environ.get("GH_OWNER", "rexlads").strip()
GH_REPO = os.environ.get("GH_REPO", "trustpositif-bot").strip()
GH_BRANCH = os.environ.get("GH_BRANCH", "main").strip()
INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "10"))

# Official checker endpoint. {domain} is substituted. Confirmed/adjusted after
# the --test run on the Indonesian machine.
OFFICIAL_CHECK_URL = os.environ.get(
    "OFFICIAL_CHECK_URL",
    "https://trustpositif.komdigi.go.id/api/cek?url={domain}",
)

RAW = "https://raw.githubusercontent.com/{o}/{r}/{b}/{f}"

# Response markers. "not blocked" is checked first (it often contains "blocked").
SAFE_MARKERS = ["tidak ada", "tidak diblokir", "tidak terblokir", "not blocked",
                "\"blocked\":false", "\"blocked\": false", "aman", "normal"]
BLOCKED_MARKERS = ["diblokir", "terblokir", "\"blocked\":true", "\"blocked\": true",
                   "blocked", "trustpositif", "internetpositif"]


# ---------------------------------------------------------------------------
# Pull config from GitHub so the web panel stays the source of truth
# ---------------------------------------------------------------------------
def pull_config() -> None:
    for fname, path in (("domains.json", checker.GROUPS_FILE),
                        ("mentions.json", checker.MENTIONS_FILE)):
        try:
            url = RAW.format(o=GH_OWNER, r=GH_REPO, b=GH_BRANCH, f=fname)
            resp = requests.get(url, headers=checker.HEADERS, timeout=30,
                                params={"_": int(time.time())})
            if resp.status_code == 200 and resp.text.strip():
                json.loads(resp.text)  # validate
                path.write_text(resp.text, encoding="utf-8")
        except Exception as e:
            print(f"[pull] {fname}: {str(e)[:100]}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Official-site check
# ---------------------------------------------------------------------------
def interpret(body: str):
    """Return True (blocked) / False (safe) / None (undecidable)."""
    text = body.lower()
    # JSON with an explicit boolean wins.
    try:
        data = json.loads(body)
        for key in ("blocked", "isblocked", "is_blocked", "block"):
            if isinstance(data, dict) and key in data and isinstance(data[key], bool):
                return data[key]
    except Exception:
        pass
    if any(m in text for m in SAFE_MARKERS):
        return False
    if any(m in text for m in BLOCKED_MARKERS):
        return True
    # Official site wording is "Ada" (blocked) / "Tidak Ada" (safe). "Tidak Ada"
    # was already caught above, so a standalone "ada" here means blocked. Only
    # trust this on short API-style bodies to avoid matching words in HTML.
    if len(text) < 400 and re.search(r"\bada\b", text):
        return True
    return None


def check_official(domain: str) -> dict:
    url = OFFICIAL_CHECK_URL.format(domain=quote(checker._norm(domain)))
    try:
        r = requests.get(url, headers=checker.HEADERS, timeout=25)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"domain": domain, "status": "error", "detail": f"Resmi: {str(e)[:80]}"}
    verdict = interpret(r.text)
    if verdict is True:
        return {"domain": domain, "status": "blocked", "detail": "Diblokir (resmi Komdigi)"}
    if verdict is False:
        return {"domain": domain, "status": "safe", "detail": "Tidak diblokir (resmi)"}
    return {"domain": domain, "status": "error", "detail": "Respons resmi tak terbaca"}


def official_reachable() -> bool:
    """Quick probe so we can fall back to the mirror if the site is unreachable."""
    r = check_official("google.com")
    return r["status"] != "error"


# ---------------------------------------------------------------------------
# One check cycle
# ---------------------------------------------------------------------------
def run_once() -> None:
    pull_config()
    groups = checker.load_groups()
    mentions = checker.load_mentions()
    total = sum(len(v) for v in groups.values())
    if total == 0:
        print("No domains yet — add some in the panel.")
        return

    use_official = official_reachable()
    if use_official:
        print("Source: OFFICIAL komdigi.go.id (real-time)")
        decide = check_official
    else:
        print("Source: blocklist MIRROR (official site unreachable from here)")
        blocked_set = None
        try:
            blocked_set = checker.fetch_blocked({checker._norm(d)
                                                 for ds in groups.values() for d in ds})
        except Exception as e:
            print(f"[mirror] {e}", file=sys.stderr)

        def decide(domain):
            if blocked_set is None:
                return {"domain": domain, "status": "error", "detail": "Sumber tak tersedia"}
            blk = checker._norm(domain) in blocked_set
            return {"domain": domain,
                    "status": "blocked" if blk else "safe",
                    "detail": "Diblokir (mirror)" if blk else "Tidak diblokir (mirror)"}

    for group, domains in groups.items():
        results = []
        for d in domains:
            res = decide(d)
            results.append(res)
            print(f"  [{group}] {res['status']:8} {d} — {res['detail']}")
            if use_official:
                time.sleep(1.0)  # be polite to the official site
        if checker.ONLY_BLOCKED:
            results = [r for r in results if r["status"] in ("blocked", "error")]
            if not results:
                checker.send_telegram(
                    f"<b>🛡️ TrustPositif — {group}</b>\n🟢 Semua aman.")
                time.sleep(1)
                continue
        checker.send_telegram(
            checker.build_group_message(group, results, checker.mentions_for(group, mentions)))
        time.sleep(1)


# ---------------------------------------------------------------------------
# --test : dump raw official responses so the parser can be finalized
# ---------------------------------------------------------------------------
def selftest() -> None:
    print("Probing the official endpoint from this machine's IP...\n")
    for dom in ("google.com", "pornhub.com", "bet365.com"):
        url = OFFICIAL_CHECK_URL.format(domain=quote(dom))
        print("=" * 60)
        print(f"GET {url}")
        try:
            r = requests.get(url, headers=checker.HEADERS, timeout=25)
            print(f"  HTTP {r.status_code}  content-type={r.headers.get('content-type','')}")
            print(f"  body: {r.text[:600]}")
            print(f"  -> interpret(): {interpret(r.text)}")
        except Exception as e:
            print(f"  ERROR {type(e).__name__}: {str(e)[:160]}")
    print("\nCopy everything above and send it back to finalize the parser.")


if __name__ == "__main__":
    if not checker.BOT_TOKEN or not checker.CHANNEL_ID:
        print("Set BOT_TOKEN and CHANNEL_ID (in .env or environment) first.",
              file=sys.stderr)
        sys.exit(1)
    if "--test" in sys.argv:
        selftest()
        sys.exit(0)
    print(f"TrustPositif real-time runner. Interval: {INTERVAL_MINUTES} min. Ctrl+C to stop.")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[cycle error] {e}", file=sys.stderr)
        print(f"--- sleeping {INTERVAL_MINUTES} min ---")
        time.sleep(INTERVAL_MINUTES * 60)
