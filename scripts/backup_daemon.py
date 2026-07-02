"""Backup sidecar — daily SQLite snapshot loop for the NAS stack.

Why a compose service instead of host cron: UGOS has no Task Scheduler
GUI and no user crontab, and the 2026-07-02 outage showed host-level
anything (ACLs, container restart policies) can be yanked by a UGOS
update. A sidecar in the same compose file needs ZERO host setup, ships
with `deploy.ps1`, and `restart: always` resurrects it like the rest of
the stack.

Behavior:
  - One snapshot immediately on start (so every deploy day has one),
    then one per day at ~04:10 container time.
  - Snapshots via sqlite3's Online Backup API — safe against concurrent
    writers (a plain cp of a live WAL database is not).
  - Keeps the newest KEEP snapshots, deletes the rest.
  - Skips (with a log line) when a snapshot for today already exists,
    so container restarts don't pile up extras.

Run (compose): python scripts/backup_daemon.py
One-shot mode (manual/testing): python scripts/backup_daemon.py --once
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path("/data/courses.db")
BACKUP_DIR = Path("/data/backups")
KEEP = 14
DAILY_AT_HOUR = 4
DAILY_AT_MINUTE = 10


def _log(msg: str) -> None:
    print(f"[backup] {dt.datetime.now().isoformat(timespec='seconds')} {msg}",
          flush=True)


def take_snapshot() -> Path | None:
    """One Online-Backup snapshot; returns the path (None when skipped
    because today's snapshot already exists)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().strftime("%Y%m%d")
    existing_today = sorted(BACKUP_DIR.glob(f"courses-{today}-*.db"))
    if existing_today:
        _log(f"snapshot for {today} already exists "
             f"({existing_today[-1].name}); skipping")
        return None

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"courses-{stamp}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    _log(f"snapshot ok: {dest.name} "
         f"({dest.stat().st_size / 1_048_576:.1f} MB)")

    snapshots = sorted(BACKUP_DIR.glob("courses-*.db"))
    for old in snapshots[:-KEEP]:
        old.unlink()
        _log(f"pruned: {old.name}")
    return dest


def _seconds_until_next_run() -> float:
    now = dt.datetime.now()
    target = now.replace(hour=DAILY_AT_HOUR, minute=DAILY_AT_MINUTE,
                         second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--once", action="store_true",
                    help="Take one snapshot and exit (manual/testing).")
    args = ap.parse_args()

    if not DB_PATH.exists():
        _log(f"ERROR: {DB_PATH} not found — is /data mounted?")
        return 1

    take_snapshot()
    if args.once:
        return 0

    while True:
        wait = _seconds_until_next_run()
        _log(f"next run in {wait / 3600:.1f}h")
        time.sleep(wait)
        try:
            take_snapshot()
        except Exception as e:  # noqa: BLE001 — the loop must survive
            _log(f"ERROR: snapshot failed: {type(e).__name__}: {e}")
            time.sleep(300)  # brief backoff, then re-enter the loop


if __name__ == "__main__":
    sys.exit(main())
