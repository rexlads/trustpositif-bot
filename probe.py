#!/usr/bin/env python3
"""Diagnose: what does Orion return for the domains in the official screenshot?"""
import re, requests, checker

# From the official Komdigi check at 14:39 — expected vs Orion
CASES = {
    "anaklink.id": "Tidak Ada (safe)",
    "superv88.b-cdn.net": "Tidak Ada (safe)",
    "supervegas01.live": "ADA (blocked) <-- official says blocked",
    "supervegas03.live": "Tidak Ada (safe)",
    "supervegas88go.com": "Tidak Ada (safe)",
}

for dom, official in CASES.items():
    r = checker.check_domain(dom)
    # also show what Orion rows mention this domain's core token
    try:
        resp = requests.post(checker.CHECK_URL, data={checker.FORM_FIELD: dom},
                             headers=checker.HEADERS, timeout=25)
        text = checker._visible_text(resp.text)
        rows = checker._ROW_RE.findall(text)
        exact = [x for x in rows if checker._norm(x) == checker._norm(dom)]
        print(f"\n=== {dom}")
        print(f"  official : {official}")
        print(f"  bot/orion: {r['status']}  ({r['detail']})")
        print(f"  exact row in orion: {exact}")
        print(f"  total orion rows containing keyword: {len(rows)}")
    except Exception as e:
        print(f"{dom}: ERR {e}")
