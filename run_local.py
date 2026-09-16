#!/usr/bin/env python3
"""
REAL-TIME runner for an Indonesian machine/RDP — self-calibrating.

From an Indonesian IP we can see Komdigi/TrustPositif blocks in real-time. But
the exact "how" varies (official API shape, or ISP block-page interception), so
this script DISCOVERS the working method on startup instead of hard-coding one:

  1. It calibrates using domains that are certainly blocked (pornhub.com, ...)
     vs certainly safe (google.com), trying each method until one cleanly tells
     them apart:
        a) official API endpoints (several candidate URLs)
        b) ISP block-page interception (HTTP GET → "internetpositif" page)
  2. Whatever wins is used for all your domains.
  3. If NOTHING works from this machine, it falls back to the GitHub blocklist
     mirror (accurate but ~1h behind) so you're never left blind.

It pulls domains.json / mentions.json from GitHub each cycle, so you keep
editing them in the web panel.

Usage:
  python run_local.py --test     # show what each method sees (send me this)
  python run_local.py            # run forever, every INTERVAL_MINUTES
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
import checker  # reads BOT_TOKEN/CHANNEL_ID from env at import (loaded above)

# ---------------------------------------------------------------------------
GH_OWNER = os.environ.get("GH_OWNER", "rexlads").strip()
GH_REPO = os.environ.get("GH_REPO", "trustpositif-bot").strip()
GH_BRANCH = os.environ.get("GH_BRANCH", "main").strip()
INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "10"))
RAW = "https://raw.githubusercontent.com/{o}/{r}/{b}/{f}"

# Calibration anchors: long-blocked in Indonesia vs certainly reachable.
KNOWN_BLOCKED = ["pornhub.com", "xnxx.com", "xvideos.com", "bet365.com"]
KNOWN_SAFE = "google.com"

# Candidate official endpoints ({domain} substituted).
OFFICIAL_CANDIDATES = [
    "https://trustpositif.komdigi.go.id/api/cek?url={domain}",
    "https://trustpositif.komdigi.go.id/Rest_server/getRecordDomain?domain={domain}",
    "https://trustpositif.komdigi.go.id/rest_server/getrecordlist?search={domain}",
]
# Extra endpoint from OFFICIAL_CHECK_URL env, tried first if given.
if os.environ.get("OFFICIAL_CHECK_URL"):
    OFFICIAL_CANDIDATES.insert(0, os.environ["OFFICIAL_CHECK_URL"].strip())

BLOCK_MARKERS = ["internetpositif", "internet positif", "trustpositif",
                 "trust positif", "aduankonten", "komdigi", "diblokir",
                 "terblokir", "positif.go.id", "\"blocked\":true", "\"blocked\": true"]
SAFE_JSON = ["\"blocked\":false", "\"blocked\": false", "tidak ada", "tidak diblokir"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# ---------------------------------------------------------------------------
# Detection methods. Each returns True (blocked) / False (safe) / None (unknown)
# ---------------------------------------------------------------------------
def _interpret_official(body: str):
    text = body.lower()
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            for k in ("blocked", "isblocked", "is_blocked", "block", "status"):
                if k in data:
                    v = data[k]
                    if isinstance(v, bool):
                        return v
                    if isinstance(v, str):
                        s = v.strip().lower()
                        if s in ("ada", "blocked", "true", "1", "diblokir"):
                            return True
                        if s in ("tidak ada", "not blocked", "false", "0", "aman"):
                            return False
    except Exception:
        pass
    if any(m in text for m in SAFE_JSON):
        return False
    if any(m in text for m in BLOCK_MARKERS):
        return True
    if len(text) < 400 and re.search(r"\bada\b", text):
        return True
    if len(text) < 400 and "aman" in text:
        return False
    return None


def make_official(url_tmpl):
    def fn(domain):
        url = url_tmpl.format(domain=quote(checker._norm(domain)))
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "*/*"}, timeout=20)
        if r.status_code != 200:
            return None
        return _interpret_official(r.text)
    return fn


def http_blockpage(domain):
    """Indonesian ISPs redirect blocked domains to an 'internet positif' page."""
    try:
        r = requests.get("http://" + checker._norm(domain) + "/",
                         headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
    except requests.exceptions.RequestException:
        return None
    blob = (r.url + " " + r.text[:4000]).lower()
    if any(m in blob for m in BLOCK_MARKERS):
        return True
    return False


METHODS = [("official:" + u, make_official(u)) for u in OFFICIAL_CANDIDATES]
METHODS.append(("http-blockpage", http_blockpage))


def calibrate():
    """Return (name, fn) of the first method that cleanly separates a known
    blocked domain (True) from a known safe domain (False). Else (None, None)."""
    for name, fn in METHODS:
        try:
            if fn(KNOWN_SAFE) is not False:
                continue
            for kb in KNOWN_BLOCKED:
                if fn(kb) is True:
                    return name, fn
        except Exception:
            continue
    return None, None


# ---------------------------------------------------------------------------
def pull_config() -> None:
    for fname, path in (("domains.json", checker.GROUPS_FILE),
                        ("mentions.json", checker.MENTIONS_FILE)):
        try:
            url = RAW.format(o=GH_OWNER, r=GH_REPO, b=GH_BRANCH, f=fname)
            resp = requests.get(url, timeout=30, params={"_": int(time.time())})
            if resp.status_code == 200 and resp.text.strip():
                json.loads(resp.text)
                path.write_text(resp.text, encoding="utf-8")
        except Exception as e:
            print(f"[pull] {fname}: {str(e)[:100]}", file=sys.stderr)


def run_once() -> None:
    pull_config()
    groups = checker.load_groups()
    mentions = checker.load_mentions()
    if sum(len(v) for v in groups.values()) == 0:
        print("No domains yet — add some in the panel.")
        return

    name, fn = calibrate()
    mirror_set = None
    if fn is not None:
        print(f"Source: REAL-TIME via [{name}]")
    else:
        print("Source: MIRROR (no real-time method worked from this machine)")
        try:
            mirror_set = checker.fetch_blocked({checker._norm(d)
                                                for ds in groups.values() for d in ds})
        except Exception as e:
            print(f"[mirror] {e}", file=sys.stderr)

    def in_mirror(domain):
        nonlocal mirror_set
        if mirror_set is None:
            try:
                mirror_set = checker.fetch_blocked({checker._norm(d)
                                                    for ds in groups.values() for d in ds})
            except Exception:
                mirror_set = set()
        return checker._norm(domain) in mirror_set

    def decide(domain):
        verdict = None
        if fn is not None:
            try:
                verdict = fn(domain)
            except Exception:
                verdict = None
        if verdict is None:                 # real-time inconclusive → mirror
            verdict = in_mirror(domain)
            src = "mirror"
        else:
            src = "resmi"
        return {"domain": domain,
                "status": "blocked" if verdict else "safe",
                "detail": ("Diblokir" if verdict else "Tidak diblokir") + f" ({src})"}

    for group, domains in groups.items():
        results = []
        for d in domains:
            res = decide(d)
            results.append(res)
            print(f"  [{group}] {res['status']:8} {d} — {res['detail']}")
            if fn is not None:
                time.sleep(0.7)   # be polite to the upstream
        if checker.ONLY_BLOCKED:
            results = [r for r in results if r["status"] == "blocked"]
            if not results:
                checker.send_telegram(f"<b>🛡️ TrustPositif — {group}</b>\n🟢 Semua aman.")
                time.sleep(1)
                continue
        checker.send_telegram(
            checker.build_group_message(group, results, checker.mentions_for(group, mentions)))
        time.sleep(1)


def selftest() -> None:
    print("Calibrating from this machine's IP...\n")
    print(f"KNOWN_SAFE  google.com")
    for name, fn in METHODS:
        try:
            s = fn(KNOWN_SAFE)
            b = {kb: fn(kb) for kb in KNOWN_BLOCKED[:2]}
            print(f"  [{name}]  safe={s}  blocked_probe={b}")
        except Exception as e:
            print(f"  [{name}]  ERROR {type(e).__name__}: {str(e)[:100]}")
    name, fn = calibrate()
    print(f"\nChosen method: {name or 'NONE (will use mirror)'}")


if __name__ == "__main__":
    if not checker.BOT_TOKEN or not checker.CHANNEL_ID:
        print("Set BOT_TOKEN and CHANNEL_ID (in .env) first.", file=sys.stderr)
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
