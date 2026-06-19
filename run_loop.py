#!/usr/bin/env python3
"""
Optional always-on runner for a VPS.
Loads variables from a local .env file and runs checker.py every INTERVAL_MINUTES.

Usage on a VPS:
    pip install -r requirements.txt python-dotenv
    cp .env.example .env   # then edit .env with real values
    python run_loop.py

To keep it alive after you log out, use one of:
    - systemd service (recommended)  OR
    - tmux/screen                    OR
    - nohup python run_loop.py &

Change the interval with INTERVAL_MINUTES in your .env (default 10).
"""

import os
import time
import subprocess
from pathlib import Path

# Load .env if python-dotenv is available; otherwise rely on real env vars.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

INTERVAL_MINUTES = int(os.environ.get("INTERVAL_MINUTES", "10"))


def run_once() -> None:
    print(f"\n=== Running check (every {INTERVAL_MINUTES} min) ===")
    # Pass the current environment straight through to the checker.
    subprocess.run(["python", "checker.py"], env=os.environ.copy())


if __name__ == "__main__":
    print(f"TrustPositif loop started. Interval: {INTERVAL_MINUTES} minutes. "
          f"Ctrl+C to stop.")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[loop error] {e}")
        time.sleep(INTERVAL_MINUTES * 60)
