#!/usr/bin/env python3
"""
Diagnostic probe v2 — Orion is the working engine (field name: "keyword").
This run shows the VISIBLE TEXT of Orion's response for a blocked vs a safe
domain, so we can pick reliable markers for checker.py.
"""

import re
import sys
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA,
           "Accept": "text/html,application/json,*/*;q=0.8",
           "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"}
URL = "https://trustcheck.orion.net.id/"

TESTS = [("BLOCKED?", "pornhub.com"), ("BLOCKED?", "bet365.com"), ("SAFE?", "google.com")]


def visible_text(html: str) -> str:
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def main():
    for label, dom in TESTS:
        print("\n" + "=" * 70)
        print(f"{label}  keyword={dom}")
        print("=" * 70)
        try:
            r = requests.post(URL, headers=HEADERS, data={"keyword": dom}, timeout=30)
            txt = visible_text(r.text)
            # The result usually appears after the domain echo; print a wide window.
            print(f"status={r.status_code} len={len(r.content)}")
            print("VISIBLE TEXT (first 1500 chars):")
            print(txt[:1500])
            # Highlight any lines mentioning likely markers.
            marks = ["blokir", "block", "aman", "safe", "normal", "trust",
                     "tidak", "ada", "found", "listed", "status", "diblok",
                     "negatif", "positif", "clean", "clear"]
            hits = [m for m in marks if m in txt.lower()]
            print("MARKER WORDS PRESENT:", hits)
        except Exception as e:
            print(f"ERROR {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    sys.exit(main())
