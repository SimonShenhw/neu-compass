"""Explicit additive v1.7 migration on an existing DB; read-only unless --commit."""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.answer_feedback_repository import AnswerFeedbackRepository, TABLE_COLUMNS  # noqa: E402


def migration_sql():
    return (ROOT / 'db/init.sql').read_text(encoding='utf-8').split(
        '-- BEGIN ANSWER_FEEDBACK_V1_7', 1)[1].split('-- END ANSWER_FEEDBACK_V1_7', 1)[0]


def migrate(db_path, *, commit=False):
    path = Path(db_path).resolve(strict=True)
    conn = sqlite3.connect(f"{path.as_uri()}?mode={'rw' if commit else 'ro'}", uri=True)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'query_log','schema_versions'}.issubset(tables):
            raise ValueError('Existing telemetry schema required')
        if not {'log_id','route','query','user_id'}.issubset({r[1] for r in conn.execute('PRAGMA table_info(query_log)')}):
            raise ValueError('Existing telemetry columns incompatible')
        for table in TABLE_COLUMNS:
            if table in tables and not AnswerFeedbackRepository(conn).table_available(table):
                raise ValueError('Existing feedback table has incompatible identity/foreign-key constraints')
        missing = sorted(TABLE_COLUMNS.keys() - tables)
        if commit:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA busy_timeout=5000')
            try:
                conn.executescript('BEGIN IMMEDIATE;\n' + migration_sql())
                if not AnswerFeedbackRepository(conn).schema_available():
                    raise ValueError('Feedback schema incomplete')
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return missing
    finally:
        conn.close()


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db-path', required=True)
    parser.add_argument('--commit', action='store_true')
    args = parser.parse_args()
    try:
        missing = migrate(args.db_path, commit=args.commit)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f'Migration failed ({type(exc).__name__}); database not replaced.')
        return 1
    print(f"{'Applied additive migration' if args.commit else 'Read-only dry-run'}; missing tables: {missing}")
    return 0


if __name__ == '__main__':
    raise SystemExit(cli())
