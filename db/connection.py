"""SQLite connection helper.

Why a wrapper:
- PRAGMA foreign_keys is per-connection (SQLite default is OFF).
  Forgetting it lets FK violations through silently — every Repository
  user must go through connect() to be safe.
- Row factory set to sqlite3.Row so callers get column-name access.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with project-standard pragmas + row factory.

    `check_same_thread=False` because FastAPI's TestClient and async route
    handlers can move a connection across the event-loop thread and
    threadpool workers. We still get exactly one user per connection (the
    request lifetime), so we don't need additional locking — SQLite's
    internal serialization (threadsafety=1 in CPython's sqlite3) handles
    safe access from different threads as long as it's not concurrent.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    # busy_timeout is per-connection (unlike WAL, which persists in the db
    # file). Without it a write that collides with another writer raises
    # "database is locked" IMMEDIATELY instead of waiting its turn — easy to
    # hit once API routes run in the threadpool alongside ingest scripts.
    conn.execute("PRAGMA busy_timeout = 5000")
    # NORMAL is the standard pairing with WAL (set persistently in init.sql):
    # fsync on checkpoint rather than every commit. Durability loss is limited
    # to power-loss-after-commit, acceptable for rebuildable data (ADR-0013).
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def open_repository(db_path: str | Path) -> Iterator["CourseRepository"]:
    """Convenience context manager: open conn, yield repository, commit on success.

    Rolls back on exception. Always closes.
    """
    from db.repository import CourseRepository  # noqa: PLC0415 (avoid circular import)

    conn = connect(db_path)
    try:
        yield CourseRepository(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
