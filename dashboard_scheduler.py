"""
Dashboard Auto-Refresh Scheduler
Regenerates the daily_dashboard.html every hour so the browser
picks up fresh Toast data on its next meta-refresh reload.

Usage:
    python dashboard_scheduler.py          # run in a terminal, leave it open
    python dashboard_scheduler.py --once   # single run (useful for Task Scheduler)

Leave this running during business hours. Press Ctrl+C to stop.
"""

import subprocess
import sys
import time
from datetime import datetime

REPO_DIR = r"C:\Users\ascha\OneDrive\Desktop\forage-data"
SCRIPT = REPO_DIR + r"\daily_dashboard.py"
INTERVAL = 3600  # seconds (1 hour)

# Business hours: only regenerate between 6 AM and 10 PM
HOUR_START = 6
HOUR_END = 22


def publish_to_github():
    """Commit daily_dashboard.html and push to GitHub Pages."""
    try:
        # Only stage the HTML file - don't touch other modified files
        subprocess.run(["git", "add", "daily_dashboard.html"], cwd=REPO_DIR, check=True)
        # Check if there's actually anything to commit
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_DIR)
        if diff.returncode == 0:
            print("  >> No changes to publish.")
            return True
        msg = f"Auto-refresh dashboard {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "commit", "-m", msg], cwd=REPO_DIR, check=True)
        result = subprocess.run(["git", "push"], cwd=REPO_DIR, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print("  >> Pushed to GitHub Pages.")
            return True
        else:
            print(f"  >> Push failed: {result.stderr.strip()}")
            return False
    except subprocess.CalledProcessError as e:
        print(f"  >> Git error: {e}")
        return False
    except Exception as e:
        print(f"  >> Publish error: {e}")
        return False


def run_dashboard():
    """Run the dashboard generator and return success/failure."""
    now = datetime.now()
    print(f"\n{'='*60}")
    print(f"  Regenerating dashboard at {now.strftime('%I:%M %p on %m/%d/%Y')}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=False,
            timeout=300,  # 5 min max
            cwd=REPO_DIR,
        )
        if result.returncode == 0:
            print(f"\n  >> Generation success. Encrypting...")
            subprocess.run(
                [sys.executable, "encrypt_dashboards.py"],
                cwd=REPO_DIR,
                timeout=60,
            )
            print(f"  >> Publishing to GitHub...")
            publish_to_github()
            print(f"  >> Next refresh in {INTERVAL // 60} minutes.")
            return True
        else:
            print(f"\n  >> Script exited with code {result.returncode}")
            return False
    except subprocess.TimeoutExpired:
        print("\n  >> Timed out after 5 minutes")
        return False
    except Exception as e:
        print(f"\n  >> Error: {e}")
        return False


def main():
    if "--once" in sys.argv:
        run_dashboard()
        return

    print("Dashboard Auto-Refresh Scheduler")
    print(f"  Interval: every {INTERVAL // 60} minutes")
    print(f"  Active hours: {HOUR_START}:00 AM - {HOUR_END % 12 or 12}:00 PM")
    print(f"  Press Ctrl+C to stop\n")

    # Run immediately on start
    run_dashboard()

    while True:
        try:
            time.sleep(INTERVAL)
            hour = datetime.now().hour
            if HOUR_START <= hour < HOUR_END:
                run_dashboard()
            else:
                print(f"  [{datetime.now().strftime('%I:%M %p')}] Outside business hours, skipping.")
        except KeyboardInterrupt:
            print("\n\nScheduler stopped.")
            break


if __name__ == "__main__":
    main()
