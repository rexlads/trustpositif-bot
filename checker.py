#!/usr/bin/env python3
"""
TrustPositif Domain Checker -> Telegram reporter
Architecture C: queries a third-party checker that reflects the official
Komdigi/TrustPositif blocklist, and includes the official URL in the report
so you can manually verify anything flagged.

Run once per invocation. Scheduling is handled externally:
  - GitHub Actions cron  (recommended, free, no server)  OR
  - a VPS cron / loop    (always-on)

Config comes from environment variables (never hard-code secrets):
  BOT_TOKEN    -> from @BotFather   (REQUIRED)
  CHANNEL_ID   -> e.g. -1004473967915 (REQUIRED)
  DOMAINS      -> comma-separated list, e.g. "a.com,b.com"
                  (OPTIONAL fallback; the primary source is domains.txt)
  BATCH_SIZE   -> how many domains per Telegram message (default 5)
  ONLY_BLOCKED -> "1" to report only blocked domains, "0" for full report (default 0)

Domains are organised into groups (Ary, AS, BD, SV). One Telegram message is
sent per group, so each group's result lands as its own message.

Domain source (in priority order):
  1. domains.json next to this file: {"Ary": [...], "AS": [...], ...}.
     This is what the web panel edits, so it is the default source of truth.
  2. domains.txt (one domain per line) — treated as a single group "Domain".
  3. The DOMAINS environment variable (comma-separated) — single group "Domain".
"""

import os
import sys
import json
import time
import html
import requests
from pathlib import Path

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL_ID   = os.environ.get("CHANNEL_ID", "").strip()
DOMAINS_RAW  = os.environ.get("DOMAINS", "").strip()
ONLY_BLOCKED = os.environ.get("ONLY_BLOCKED", "0").strip() == "1"

# The web panel edits domains.json, so it is the primary source of domains.
GROUPS_FILE  = Path(__file__).with_name("domains.json")
DOMAINS_FILE = Path(__file__).with_name("domains.txt")  # legacy fallback

# Fixed group order so the four Telegram messages always arrive consistently.
GROUP_ORDER = ["Ary", "AS", "BD", "SV"]

OFFICIAL_URL = "https://trustpositif.komdigi.go.id/"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

# Polite delay between domain checks so we don't hammer the checker.
DELAY_BETWEEN_CHECKS = 1.5  # seconds

# A normal-looking browser UA. Some checkers reject requests with no UA.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fail(msg: str) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(1)


def _clean(items) -> list:
    """Lowercase, strip, drop empties, keep order, de-duplicate."""
    seen = set()
    out = []
    for item in items:
        d = str(item).strip().lower()
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _legacy_domains() -> list:
    """Read domains.txt, then the DOMAINS env var, as a flat list."""
    raw = []
    if DOMAINS_FILE.exists():
        for line in DOMAINS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                raw.extend(line.split(","))
    if not raw and DOMAINS_RAW:
        raw = DOMAINS_RAW.split(",")
    return _clean(raw)


def load_groups() -> dict:
    """
    Returns an ordered dict {group_name: [domains]}.
    Reads domains.json first; falls back to a single "Domain" group built from
    domains.txt / the DOMAINS env var.
    """
    if GROUPS_FILE.exists():
        try:
            data = json.loads(GROUPS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            fail(f"domains.json is not valid JSON: {e}")
        groups = {}
        # Keep the fixed order first, then any extra groups the user added.
        for name in GROUP_ORDER + [k for k in data if k not in GROUP_ORDER]:
            if name in data:
                groups[name] = _clean(data[name] or [])
        return groups

    return {"Domain": _legacy_domains()}


def validate_config() -> dict:
    if not BOT_TOKEN:
        fail("BOT_TOKEN is not set.")
    if not CHANNEL_ID:
        fail("CHANNEL_ID is not set.")
    groups = load_groups()
    if not any(groups.values()):
        fail("No domains found. Add some via the panel (domains.json) or set DOMAINS.")
    return groups


# ============================================================================
# >>> THE ONE PART THAT NEEDS THE NETWORK-TAB DETAILS YOU'LL SEND ME <<<
# ----------------------------------------------------------------------------
# Replace the body of check_domain() once you give me the request format from
# the browser's Network tab. Right now it is written for the MOST LIKELY shape
# (a POST with a single field) and includes clear notes on what to adjust.
#
# What I need from you to finalize this function:
#   1. The exact request URL          -> set CHECK_URL below
#   2. GET or POST                     -> adjust the requests call
#   3. The form field name             -> e.g. "keyword" / "domain" / "ip"
#   4. What the response says when a
#      domain IS vs IS NOT blocked     -> adjust the detection logic
# ============================================================================

CHECK_URL = "https://trustcheck.orion.net.id/"          # (1) confirm this
FORM_FIELD = "keyword"                                   # (3) confirm this name

# (4) Words that appear in the response when a domain is BLOCKED / NOT blocked.
#     We will tune these once you paste a real response. These are reasonable
#     defaults based on how these tools usually phrase results.
BLOCKED_MARKERS     = ["diblokir", "blocked", "terblokir", "blokir", "ada", "found"]
NOT_BLOCKED_MARKERS = ["tidak diblokir", "not blocked", "tidak terblokir",
                       "aman", "normal", "tidak ada", "not found", "available"]


def check_domain(domain: str) -> dict:
    """
    Returns: {"domain": str, "status": "blocked"|"safe"|"unknown"|"error",
              "detail": str}
    """
    try:
        resp = requests.post(                         # (2) change to .get if needed
            CHECK_URL,
            data={FORM_FIELD: domain},                # (3) field name
            headers=HEADERS,
            timeout=25,
        )
        resp.raise_for_status()
        text = resp.text.lower()

        # NOT-blocked is checked first because "tidak diblokir" contains "diblokir".
        if any(m in text for m in NOT_BLOCKED_MARKERS):
            return {"domain": domain, "status": "safe",
                    "detail": "Not on the blocklist"}
        if any(m in text for m in BLOCKED_MARKERS):
            return {"domain": domain, "status": "blocked",
                    "detail": "Appears on the blocklist"}
        return {"domain": domain, "status": "unknown",
                "detail": "Could not parse result (markers need tuning)"}

    except requests.exceptions.Timeout:
        return {"domain": domain, "status": "error", "detail": "Timeout"}
    except requests.exceptions.RequestException as e:
        return {"domain": domain, "status": "error", "detail": str(e)[:120]}


# ----------------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------------
ICON = {"blocked": "🔴", "safe": "🟢", "unknown": "🟡", "error": "⚠️"}


def send_telegram(message: str) -> None:
    try:
        r = requests.post(
            TELEGRAM_API,
            data={
                "chat_id": CHANNEL_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
            timeout=20,
        )
        if r.status_code != 200:
            print(f"[Telegram error] {r.status_code}: {r.text}", file=sys.stderr)
    except requests.exceptions.RequestException as e:
        print(f"[Telegram send failed] {e}", file=sys.stderr)


def build_group_message(group: str, results: list) -> str:
    """One Telegram message for a single group."""
    head = html.escape(group)
    lines = [f"<b>🛡️ TrustPositif — {head}</b>", ""]

    if not results:
        lines.append("<i>Belum ada domain di grup ini.</i>")
        return "\n".join(lines)

    for r in results:
        icon = ICON.get(r["status"], "⚪")
        dom = html.escape(r["domain"])
        det = html.escape(r["detail"])
        lines.append(f"{icon} <code>{dom}</code> — {det}")

    blocked = sum(1 for r in results if r["status"] == "blocked")
    safe = sum(1 for r in results if r["status"] == "safe")
    issues = sum(1 for r in results if r["status"] in ("error", "unknown"))
    lines.append("")
    lines.append(f"🔴 {blocked}  🟢 {safe}  ⚠️ {issues}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> None:
    groups = validate_config()
    total = sum(len(v) for v in groups.values())
    print(f"Checking {total} domains across {len(groups)} groups...")

    for group, domains in groups.items():
        results = []
        for d in domains:
            res = check_domain(d)
            results.append(res)
            print(f"  [{group}] {res['status']:8} {d} — {res['detail']}")
            time.sleep(DELAY_BETWEEN_CHECKS)

        if ONLY_BLOCKED:
            results = [r for r in results if r["status"] in ("blocked", "error", "unknown")]
            if not results:
                send_telegram(f"<b>🛡️ TrustPositif — {html.escape(group)}</b>\n🟢 Semua aman.")
                time.sleep(1)
                continue

        # One message per group (always 4 with the default groups).
        send_telegram(build_group_message(group, results))
        time.sleep(1)  # avoid Telegram rate limits

    print("Done.")


if __name__ == "__main__":
    main()
