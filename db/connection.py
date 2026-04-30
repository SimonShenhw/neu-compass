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
    """Open a SQLite connection with project-standard pragmas + row factory."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
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
