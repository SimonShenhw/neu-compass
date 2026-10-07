"""Read-only query_log export: counts by default, explicit private JSONL only.

The database must already exist and is read in one read-only snapshot. Without --out only counts
of the selected rows are printed. --out writes a new metadata JSONL without the query text; the
query text and rejection reason also need --include-private-text --ack-private-data.
Contract: docs/query-log-export.md.
"""

from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from schemas.feedback_candidate import text_sha256  # noqa: E402
from schemas.query_log_export import PrivateQueryText, QueryLogExportRow  # noqa: E402
from scripts.private_export import (ORIGINS, SafeArgumentParser, date_window,  # noqa: E402
    open_read_snapshot, origin_clauses, private_destination, publish_new_file, query_log_compatible,
    result_course_ids, retrieval_mode, traffic_kind, utc_timestamp)

MAX_EXPORT_BYTES = 32 * 1024 * 1024
PRIVATE_DIRECTORY = ROOT / 'data/raw/query_log_review'
ROW_COLUMNS = ('log_id', 'created_at', 'route', 'query', 'matched_via', 'k', 'latency_ms',
               'result_course_ids', 'rejection_reason', 'user_id')
# Counting never reads the query text or the rejection reason. No SELECT *: a column added to
# query_log later is not exported until it is reviewed here.
COUNT_SQL = 'SELECT log_id, created_at, route, matched_via, user_id FROM query_log'
ROW_SQL = f'SELECT {", ".join(ROW_COLUMNS)} FROM query_log'


def _classified(row):
    """Origin, route and retrieval mode of a selected row; bad values fail, they are not skipped."""
    traffic = traffic_kind(row['user_id'])
    utc_timestamp(row['created_at'])
    if row['route'] not in ('search', 'chat'):
        raise ValueError('Invalid route')
    return traffic, row['route'], retrieval_mode(row['matched_via'])


def _export_row(row, include_private_text):
    traffic, route, mode = _classified(row)
    private = PrivateQueryText(query=row['query'], rejection_reason=row['rejection_reason'])
    requirements = ['privacy_review_required', 'results_not_ground_truth', 'no_retrieval_snapshot',
                    'missing_request_context']
    if route == 'chat':
        requirements.append('missing_history_content')
    if traffic != 'eval':
        requirements.append('unverified_traffic_origin')
    if mode == 'unknown':
        requirements.append('unknown_retrieval_mode')
    return QueryLogExportRow(
        log_id=row['log_id'], created_at=utc_timestamp(row['created_at']), route=route,
        traffic_kind=traffic, eval_run_sha256=text_sha256(row['user_id']) if traffic == 'eval' else None,
        retrieval_mode=mode, k=row['k'], latency_ms=row['latency_ms'],
        result_course_ids=result_course_ids(row['result_course_ids']), query_sha256=text_sha256(private.query),
        review_requirements=requirements, private_text=private if include_private_text else None,
    )


def export_query_log(db_path, *, out=None, origin='unmarked', since=None, until=None,
                     limit=200, include_private_text=False, ack_private_data=False):
    if type(limit) is not int or not 1 <= limit <= 1000 or origin not in ORIGINS:
        raise ValueError('Invalid selection')
    if type(include_private_text) is not bool or type(ack_private_data) is not bool:
        raise ValueError('Explicit boolean privacy flags required')
    if include_private_text != ack_private_data or (include_private_text and out is None):
        raise ValueError('Private text requires output and paired acknowledgement')
    lower, upper = date_window(since, until)
    destination = private_destination(out, PRIVATE_DIRECTORY) if out is not None else None
    conn = open_read_snapshot(db_path)
    traffic, routes, modes, lines, byte_count = Counter(), Counter(), Counter(), [], 0
    try:
        if not query_log_compatible(conn, ROW_COLUMNS):
            raise ValueError('Compatible existing query_log schema required')
        clauses, parameters = origin_clauses(origin, 'user_id'), []
        if lower is not None:
            clauses.append('created_at>=?')
            parameters.append(lower)
        if upper is not None:
            clauses.append('created_at<?')
            parameters.append(upper)
        selection = (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY log_id'
        # The counts cover the whole selection; limit bounds only the file.
        for row in conn.execute(COUNT_SQL + selection, parameters):
            kind, route, mode = _classified(row)
            traffic[kind] += 1
            routes[route] += 1
            modes[mode] += 1
        if destination is not None:
            for row in conn.execute(ROW_SQL + selection + ' LIMIT ?', (*parameters, limit)):
                exported = _export_row(row, include_private_text)
                encoded = (json.dumps(exported.model_dump(), ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
                byte_count += len(encoded)
                if byte_count > MAX_EXPORT_BYTES:
                    raise ValueError('Export outside bounded output budget; narrow selection')
                lines.append(encoded)
    finally:
        conn.close()
    # Every exported row has been validated before ANY output file is created.
    cleanup_incomplete = publish_new_file(destination, lines, '.query-log-review-') if destination is not None else False
    selected = sum(traffic.values())
    return dict(
        privacy_mode='counts' if destination is None else 'private_text' if include_private_text else 'metadata',
        origin=origin, since=since, until=until, limit=limit,
        selected_row_count=selected, exported_row_count=len(lines),
        has_more=destination is not None and selected > len(lines),
        written=destination is not None, temporary_cleanup_incomplete=cleanup_incomplete,
        review_state='pending', ground_truth=False,
        traffic_counts=dict(traffic), route_counts=dict(routes), retrieval_mode_counts=dict(modes),
    )


class QueryLogArgumentParser(SafeArgumentParser):
    failure = 'Query log export failed (arguments); no output published.\n'


def cli(argv=None):
    parser = QueryLogArgumentParser(description=__doc__)
    parser.add_argument('--db-path', required=True)
    parser.add_argument('--out', help='New .jsonl file; inside the repository only data/raw/query_log_review/')
    parser.add_argument('--origin', choices=ORIGINS, default='unmarked')
    parser.add_argument('--since', help='Inclusive query_log.created_at UTC date, YYYY-MM-DD')
    parser.add_argument('--until', help='Exclusive query_log.created_at UTC date, YYYY-MM-DD')
    parser.add_argument('--limit', type=int, default=200, help='Rows written to --out, 1-1000; counts are not limited')
    parser.add_argument('--include-private-text', action='store_true')
    parser.add_argument('--ack-private-data', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = export_query_log(**vars(args))
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError):
        print('Query log export failed (input/storage); no output published.', file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(cli())
