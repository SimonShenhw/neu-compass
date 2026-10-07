"""Shared contract of the private offline exporters (answer feedback, query log).

The database must already exist and is read in one read-only snapshot: no file is created, nothing
is migrated or written. Callers validate every selected row before any output exists. Output is a
new .jsonl file published without overwriting; inside the repository only the tool's ignored
private directory is allowed. The original X-Eval-Run marker is classified, never exported.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parent.parent
ORIGINS = ('unmarked', 'eval', 'all')
RETRIEVAL_MODES = frozenset({'alias', 'hybrid', 'hyde_rescued', 'context', 'program', 'empty', 'rejected'})


def _date(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('Invalid date selection')
    parsed = datetime.strptime(value, '%Y-%m-%d')
    if parsed.strftime('%Y-%m-%d') != value:
        raise ValueError('Canonical date required')
    return value + ' 00:00:00'


def date_window(since, until):
    """Inclusive since / exclusive until UTC dates as SQLite timestamps; empty windows fail."""
    lower, upper = _date(since), _date(until)
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError('Empty or reversed date window')
    return lower, upper


def utc_timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing timestamp')
    parsed = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    if parsed.strftime('%Y-%m-%d %H:%M:%S') != value:
        raise ValueError('Canonical SQLite UTC timestamp required')
    return parsed.strftime('%Y-%m-%dT%H:%M:%SZ')


def strict_json(value, budget):
    if not isinstance(value, str) or len(value) > budget:
        raise ValueError('Source JSON outside budget')
    def unique_keys(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = item
        return result
    return json.loads(value, object_pairs_hook=unique_keys)


def result_course_ids(value):
    ids = strict_json(value, 65536)
    if not isinstance(ids, list) or len(ids) > 1000 or any(not isinstance(item, str) or not item for item in ids):
        raise ValueError('Invalid result IDs')
    return ids


def traffic_kind(marker):
    """NULL only means no X-Eval-Run header; it does not prove a real person."""
    if marker is not None and not isinstance(marker, str):
        raise ValueError('Invalid original traffic marker')
    return 'unmarked' if marker is None else 'eval' if marker.startswith('eval:') and len(marker) > 5 else 'unknown'


def origin_clauses(origin, column):
    """SQL selecting one origin ('all' adds none); it agrees with traffic_kind() on text markers."""
    if origin == 'unmarked':
        return [f'{column} IS NULL']
    if origin == 'eval':
        return [f"substr({column},1,5)='eval:' AND length({column})>5"]
    return []


def retrieval_mode(value):
    """Unknown modes become 'unknown' so a stored string is never published verbatim."""
    if value is not None and not isinstance(value, str):
        raise ValueError('Invalid retrieval mode type')
    return value if value in RETRIEVAL_MODES else 'unknown'


def open_read_snapshot(db_path):
    path = Path(db_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Existing database file required')
    conn = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute('BEGIN')  # One read snapshot; no migration, commit or DML.
    except BaseException:
        conn.close()
        raise
    return conn


def query_log_compatible(conn, columns):
    """The original query_log with these columns and its real INTEGER primary key (stable log IDs)."""
    info = list(conn.execute('PRAGMA table_info(query_log)'))
    primary_key = [(row[1], row[2].upper()) for row in info if row[5]]
    return set(columns).issubset({row[1] for row in info}) and primary_key == [('log_id', 'INTEGER')]


def private_destination(out, private_directory):
    lexical = Path(out).absolute()
    if lexical.suffix.lower() != '.jsonl' or os.path.lexists(lexical):
        raise ValueError('Output must be a new JSONL file')
    parent = lexical.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError('Existing private output directory required')
    resolved = parent / lexical.name
    # Both lexical and resolved paths matter if a repository directory is a symlink.
    for path in (lexical, resolved):
        if path.is_relative_to(ROOT) and not path.is_relative_to(private_directory):
            raise ValueError('Repository output must stay in the ignored private directory')
    return resolved


def publish_new_file(out, lines, prefix):
    """Complete a mode-0600 temp file, then link exclusively; never overwrite."""
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix='.tmp', dir=out.parent)
    temporary = Path(name)
    published, cleanup_incomplete = False, False
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            if os.name == 'posix':
                os.fchmod(stream.fileno(), 0o600)
            for line in lines:
                stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        # link() fails if the destination (including a symlink) exists. It does
        # not expose a half-written final file on write failure.
        os.link(temporary, out)
        published = True
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            if not published:
                raise
            # The final file is complete. Do not misreport a successful publish
            # as "no output" if removing our private staging file failed.
            cleanup_incomplete = True
    return cleanup_incomplete


class SafeArgumentParser(argparse.ArgumentParser):
    failure = 'Export failed (arguments); no output published.\n'

    def error(self, message):
        # argparse normally echoes untrusted option values, which may contain PII.
        self.exit(2, self.failure)
