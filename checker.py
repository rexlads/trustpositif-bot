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
import re
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
    return load_groups()


# ============================================================================
# Domain check engine
# ----------------------------------------------------------------------------
# PRIMARY source — the Skiddle blocklist mirror. It is a verbatim mirror of the
# official Komdigi/TrustPositif domain list (~9M entries), auto-updated hourly,
# served from GitHub's CDN so it is reachable from anywhere (the official
# komdigi.go.id site is IP-locked to Indonesia and unusable from GitHub runners).
# Verified: results match the official site exactly (e.g. supervegas01.live).
# We download the list once per run and test exact membership.
#
# FALLBACK — if the blocklist can't be downloaded, we fall back to the Orion
# checker (https://trustcheck.orion.net.id/) per domain. Orion's data can lag,
# so it is only a safety net.
# ============================================================================

# domains_001.txt, domains_002.txt, ... We probe upward and stop at the first
# missing file, so new shards are picked up automatically.
BLOCKLIST_URL = "https://raw.githubusercontent.com/Skiddle-ID/blocklist/main/domains_{:03d}.txt"
BLOCKLIST_MAX_FILES = 20

# Orion fallback config
CHECK_URL = "https://trustcheck.orion.net.id/"
FORM_FIELD = "keyword"
_ROW_RE = re.compile(r"([A-Za-z0-9_.:\-]+)\s+Terblokir", re.IGNORECASE)
_TAG_RE = re.compile(r"(?s)<[^>]+>")


def _visible_text(html_text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html_text)
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text)


def _norm(d: str) -> str:
    return d.strip().lower().rstrip(".")


def fetch_blocked(targets: set) -> set:
    """
    Stream the Skiddle blocklist shards and return the subset of `targets`
    (already normalised) that appear in the official blocklist.
    Raises RuntimeError if not a single shard could be downloaded.
    """
    found = set()
    remaining = set(targets)
    downloaded = 0
    for i in range(1, BLOCKLIST_MAX_FILES + 1):
        if not remaining:
            break  # every target already matched
        url = BLOCKLIST_URL.format(i)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        except requests.exceptions.RequestException as e:
            print(f"[blocklist] shard {i} error: {str(e)[:80]}", file=sys.stderr)
            break
        if resp.status_code == 404:
            break  # no more shards
        if resp.status_code != 200:
            print(f"[blocklist] shard {i} HTTP {resp.status_code}", file=sys.stderr)
            break
        downloaded += 1
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            d = _norm(raw)
            if d in remaining:
                found.add(d)
                remaining.discard(d)
                if not remaining:
                    break
    if downloaded == 0:
        raise RuntimeError("could not download any blocklist shard")
    print(f"[blocklist] scanned {downloaded} shard(s); "
          f"{len(found)}/{len(targets)} domains blocked")
    return found


def check_domain_orion(domain: str) -> dict:
    """Fallback: query Orion and decide by exact-match on the result rows."""
    target = _norm(domain)
    try:
        resp = requests.post(CHECK_URL, data={FORM_FIELD: domain},
                             headers=HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"domain": domain, "status": "error", "detail": f"Orion: {str(e)[:90]}"}
    blocked_rows = {_norm(m) for m in _ROW_RE.findall(_visible_text(resp.text))}
    if target in blocked_rows:
        return {"domain": domain, "status": "blocked", "detail": "Diblokir (Orion)"}
    return {"domain": domain, "status": "safe", "detail": "Tidak diblokir (Orion)"}


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
    lines.append(f"<a href=\"{OFFICIAL_URL}\">Verifikasi manual</a>")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> None:
    groups = validate_config()
    total = sum(len(v) for v in groups.values())
    if total == 0:
        print("No domains configured yet — add some via the panel. Nothing to do.")
        return
    print(f"Checking {total} domains across {len(groups)} groups...")

    # Build the set of all domains, then resolve blocked status in ONE pass over
    # the official blocklist mirror. Fall back to per-domain Orion if it's down.
    all_targets = {_norm(d) for ds in groups.values() for d in ds}
    blocked_set = None
    try:
        blocked_set = fetch_blocked(all_targets)
    except Exception as e:
        print(f"[blocklist] unavailable ({e}); falling back to Orion", file=sys.stderr)

    def decide(domain: str) -> dict:
        if blocked_set is not None:
            if _norm(domain) in blocked_set:
                return {"domain": domain, "status": "blocked",
                        "detail": "Diblokir TrustPositif/Komdigi"}
            return {"domain": domain, "status": "safe", "detail": "Tidak diblokir"}
        # fallback path
        res = check_domain_orion(domain)
        time.sleep(DELAY_BETWEEN_CHECKS)
        return res

    for group, domains in groups.items():
        results = []
        for d in domains:
            res = decide(d)
            results.append(res)
            print(f"  [{group}] {res['status']:8} {d} — {res['detail']}")

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
