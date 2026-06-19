#!/usr/bin/env python3
"""
Diagnostic probe — run this on GitHub Actions (open egress, non-ID IP, just like
the real bot) to discover which checker endpoints work and what their responses
look like. The output goes to the Actions log; we use it to finalize the markers
in checker.py.

Run via: Actions tab -> "Probe checkers" -> Run workflow
(or it is triggered automatically by the probe.yml workflow_dispatch).
"""

import sys
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA,
           "Accept": "text/html,application/json,*/*;q=0.8",
           "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"}

# Domains to test: one almost-certainly blocked, one almost-certainly safe.
BLOCKED_GUESS = "pornhub.com"
SAFE_GUESS = "google.com"


def show(label, resp):
    print(f"\n----- {label} -----")
    print(f"  status      : {resp.status_code}")
    print(f"  content-type: {resp.headers.get('content-type','')}")
    print(f"  length      : {len(resp.content)}")
    body = resp.text
    print(f"  body[:1200] :\n{body[:1200]}")


def get(label, url, **kw):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30, **kw)
        show(label, r)
        return r
    except Exception as e:
        print(f"\n----- {label} -----\n  ERROR {type(e).__name__}: {str(e)[:200]}")
        return None


def post(label, url, data=None, json=None, **kw):
    try:
        r = requests.post(url, headers=HEADERS, data=data, json=json, timeout=30, **kw)
        show(label, r)
        return r
    except Exception as e:
        print(f"\n----- {label} -----\n  ERROR {type(e).__name__}: {str(e)[:200]}")
        return None


def main():
    print("=" * 70)
    print("PROBE: discovering which TrustPositif checker endpoints work")
    print("=" * 70)

    # --- Official Komdigi site (likely IP-locked to Indonesia) ---
    get("official root", "https://trustpositif.komdigi.go.id/")
    r = get("official assets/db/domains (HEAD-ish, first bytes)",
            "https://trustpositif.komdigi.go.id/assets/db/domains",
            stream=True)
    # Common internal API shapes seen on the site over time:
    post("official Rest_server/cek_url (name)",
         "https://trustpositif.komdigi.go.id/Rest_server/cek_url",
         data={"name": BLOCKED_GUESS})
    post("official Rest_server/getrecordmim (name)",
         "https://trustpositif.komdigi.go.id/Rest_server/getrecordmim",
         data={"name": BLOCKED_GUESS})

    # --- Orion checker ---
    get("orion root (inspect the form/fields)", "https://trustcheck.orion.net.id/")
    for field in ("keyword", "domain", "name", "url", "q"):
        post(f"orion POST [{field}={BLOCKED_GUESS}]",
             "https://trustcheck.orion.net.id/",
             data={field: BLOCKED_GUESS})

    # --- Alternative third-party checkers (also proxy from Indonesia) ---
    get("komdigi.io root", "https://trustpositif.komdigi.io/")
    get("komdigi.website root", "https://trustpositif.komdigi.website/")

    print("\nDONE. Look above for any 200 response whose body clearly differs")
    print("between a blocked vs safe domain — that is the engine we wire up.")


if __name__ == "__main__":
    sys.exit(main())
