#!/usr/bin/env python3
"""Test the Skiddle live API (check.skiddle.id) against the official results."""
import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
CASES = {
    "supervegas01.live": "ADA (blocked) per official",
    "supervegas03.live": "Tidak Ada (safe) per official",
    "supervegas88go.com": "Tidak Ada (safe) per official",
    "anaklink.id": "Tidak Ada (safe) per official",
    "arya88link.com": "in our list",
    "bosjudibaik.live": "in our list",
    "google.com": "control: safe",
}

for dom, note in CASES.items():
    print(f"\n=== {dom}  [{note}]")
    for suffix in ("&json=true", ""):
        url = f"https://check.skiddle.id/?domain={dom}{suffix}"
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
            body = r.text.strip().replace("\n", " ")
            print(f"  GET {url}")
            print(f"    HTTP {r.status_code} ct={r.headers.get('content-type','')[:30]} body={body[:300]}")
        except Exception as e:
            print(f"  {url} -> ERR {type(e).__name__}: {str(e)[:120]}")
