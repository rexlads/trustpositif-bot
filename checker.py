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
  DOMAINS      -> comma-separated list, e.g. "a.com,b.com" (REQUIRED)
  BATCH_SIZE   -> how many domains per Telegram message (default 5)
  ONLY_BLOCKED -> "1" to report only blocked domains, "0" for full report (default 0)
"""

import os
import sys
import time
import html
import requests

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL_ID   = os.environ.get("CHANNEL_ID", "").strip()
DOMAINS_RAW  = os.environ.get("DOMAINS", "").strip()
BATCH_SIZE   = int(os.environ.get("BATCH_SIZE", "5"))
ONLY_BLOCKED = os.environ.get("ONLY_BLOCKED", "0").strip() == "1"

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


def validate_config() -> list:
    if not BOT_TOKEN:
        fail("BOT_TOKEN is not set.")
    if not CHANNEL_ID:
        fail("CHANNEL_ID is not set.")
    if not DOMAINS_RAW:
        fail("DOMAINS is not set (comma-separated list).")
    domains = [d.strip().lower() for d in DOMAINS_RAW.split(",") if d.strip()]
    if not domains:
        fail("DOMAINS parsed to an empty list.")
    return domains


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


def build_batch_message(batch_results: list, part: int, total_parts: int) -> str:
    lines = [f"<b>TrustPositif Check — Part {part}/{total_parts}</b>", ""]
    for r in batch_results:
        icon = ICON.get(r["status"], "⚪")
        dom = html.escape(r["domain"])
        det = html.escape(r["detail"])
        lines.append(f"{icon} <code>{dom}</code> — {det}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> None:
    domains = validate_config()
    print(f"Checking {len(domains)} domains, batch size {BATCH_SIZE}...")

    results = []
    for d in domains:
        res = check_domain(d)
        results.append(res)
        print(f"  {res['status']:8} {d} — {res['detail']}")
        time.sleep(DELAY_BETWEEN_CHECKS)

    if ONLY_BLOCKED:
        reportable = [r for r in results if r["status"] in ("blocked", "error", "unknown")]
        if not reportable:
            print("ONLY_BLOCKED=1 and nothing blocked — sending a short all-clear.")
            send_telegram("🟢 <b>TrustPositif Check</b>\nAll monitored domains are clear.")
            return
        results = reportable

    # Split into batches and send one message per batch.
    batches = [results[i:i + BATCH_SIZE] for i in range(0, len(results), BATCH_SIZE)]
    total_parts = len(batches)
    for idx, batch in enumerate(batches, start=1):
        msg = build_batch_message(batch, idx, total_parts)
        send_telegram(msg)
        time.sleep(1)  # avoid Telegram rate limits

    # Summary footer with the official link for manual verification.
    blocked = sum(1 for r in results if r["status"] == "blocked")
    summary = (
        f"<b>Summary</b>\n"
        f"🔴 Blocked: {blocked}   "
        f"🟢 Safe: {sum(1 for r in results if r['status']=='safe')}   "
        f"⚠️ Issues: {sum(1 for r in results if r['status'] in ('error','unknown'))}\n\n"
        f"Verify manually at {OFFICIAL_URL}"
    )
    send_telegram(summary)
    print("Done.")


if __name__ == "__main__":
    main()
