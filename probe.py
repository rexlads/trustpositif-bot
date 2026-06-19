#!/usr/bin/env python3
"""Self-test: run the FINAL check_domain() against live Orion (no Telegram)."""
import checker

TESTS = ["pornhub.com", "bet365.com", "google.com", "example.com",
         "wikipedia.org", "indoxxi.lol"]

if __name__ == "__main__":
    for d in TESTS:
        r = checker.check_domain(d)
        print(f"{r['status']:8} {d} — {r['detail']}")
