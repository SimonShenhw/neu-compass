"""Run the query_log retention by hand (batch T, policy P3): question text older than N days becomes its keyed hash,
and saved answers older than N days are deleted with their votes.

The API does this by itself once at startup and then daily when QUERY_LOG_RETENTION_DAYS is set
(api/query_log_retention_task.py). This script is for a manual run or a count: --dry-run only counts what a run would
change or delete and needs no key; a real run needs SESSION_SECRET, the same key the API uses. Run it where the API
runs (for example `docker compose exec api python scripts/redact_query_log.py --dry-run`). Prints counts only, never
text. Contract: docs/query-log-export.md, "到期清理".

中文：手动跑一次 query_log 到期清理（T 批，政策 P3）：超过 N 天的问题原文换成带密钥的哈希，超过 N 天的保存回答连同评价
删除。设了 QUERY_LOG_RETENTION_DAYS 时，API 启动时和之后每天会自己做；这个脚本用来手动跑一次或者只数一数：--dry-run
只数会改几行、删几条，不需要密钥；真跑需要 SESSION_SECRET，和 API 用的是同一个密钥。在 API 所在的环境里跑。只输出计数，
从不输出原文。
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.private_export import SafeArgumentParser  # noqa: E402


class RetentionArgumentParser(SafeArgumentParser):
    failure = 'Query log retention failed (arguments); nothing changed.\n'


def cli(argv=None, *, now=None):
    from api.query_hash import derive_key  # noqa: PLC0415
    from config import settings  # noqa: PLC0415
    from db.connection import connect  # noqa: PLC0415
    from db.query_log_retention import (  # noqa: PLC0415
        checkpoint, count_expired, count_expired_answers, delete_expired_answers, redact_expired)

    parser = RetentionArgumentParser(description=__doc__)
    parser.add_argument('--db-path', help='Default: the configured SQLITE_PATH')
    parser.add_argument('--days', type=int, help='Default: QUERY_LOG_RETENTION_DAYS; at least 1')
    parser.add_argument('--dry-run', action='store_true', help='Only count; change nothing')
    args = parser.parse_args(argv)
    days = args.days if args.days is not None else settings.query_log_retention_days
    if type(days) is not int or days < 1:
        print('Retention is off: pass --days or set QUERY_LOG_RETENTION_DAYS (at least 1). Nothing changed.',
              file=sys.stderr)
        return 2
    if not args.dry_run and not settings.session_secret:
        print('SESSION_SECRET is not set: refusing to replace text with hashes that match nothing. Nothing changed.',
              file=sys.stderr)
        return 2
    db_path = Path(args.db_path or settings.sqlite_path)
    if not db_path.is_file():
        print('Query log retention failed: the database does not exist. Nothing changed.', file=sys.stderr)
        return 1
    now = now or datetime.now(timezone.utc)
    try:
        conn = connect(db_path)
        try:
            if args.dry_run:
                answers, votes = count_expired_answers(conn, now=now, days=days)
                report = {'dry_run': True, 'days': days, 'would_replace': count_expired(conn, now=now, days=days),
                          'would_delete_answers': answers, 'would_delete_votes': votes}
            else:
                replaced = redact_expired(conn, key=derive_key(settings.session_secret), now=now, days=days)
                answers, votes = delete_expired_answers(conn, now=now, days=days)
                checkpoint(conn)
                report = {'dry_run': False, 'days': days, 'replaced': replaced, 'answers_deleted': answers,
                          'votes_deleted': votes}
        finally:
            conn.close()
    except (OSError, sqlite3.Error, ValueError):
        print('Query log retention failed (input/storage); a partial run keeps every finished batch.', file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(cli())
