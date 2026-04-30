"""Shared pytest fixtures.

Anything that touches the DB schema should depend on `empty_db` (in-memory,
init.sql applied, FK enforcement on) so tests stay fast and isolated.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INIT_SQL_PATH = PROJECT_ROOT / "db" / "init.sql"


@pytest.fixture
def empty_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(INIT_SQL_PATH.read_text(encoding="utf-8"))
    yield conn
    conn.close()
