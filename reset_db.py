"""
GridSense DB reset utility.

Usage:
    uv run python reset_db.py            # delete rows older than 60s
    uv run python reset_db.py --all      # drop & recreate the telemetry table
"""

import sys
import time
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("gridsense.db")


def wipe_old(max_age_seconds: int = 60) -> int:
    if not DB_PATH.exists():
        print(f"[reset_db] No DB at {DB_PATH}; nothing to do.")
        return 0
    cutoff = time.time() - max_age_seconds
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "DELETE FROM telemetry WHERE timestamp < ?", (cutoff,)
        )
        deleted = cur.rowcount or 0
        conn.commit()
    print(f"[reset_db] Deleted {deleted} rows older than {max_age_seconds}s.")
    return deleted


def wipe_all() -> None:
    if not DB_PATH.exists():
        print(f"[reset_db] No DB at {DB_PATH}; nothing to do.")
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS telemetry")
        conn.commit()
    print(f"[reset_db] Dropped telemetry table. Re-run scheduler.py to recreate.")


if __name__ == "__main__":
    if "--all" in sys.argv:
        wipe_all()
    else:
        wipe_old(60)
