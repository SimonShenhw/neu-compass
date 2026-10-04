"""Read-only feedback candidates: counts by default, explicit private JSONL only."""

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.answer_feedback_repository import AnswerFeedbackRepository  # noqa: E402
from schemas.feedback_candidate import (FeedbackCandidate, PrivateCandidateText,  # noqa: E402
    ReviewRequestContext, context_sha256, text_sha256)

MAX_EXPORT_BYTES = 32 * 1024 * 1024
PRIVATE_DIRECTORY = ROOT / 'data/raw/feedback_review'
QUERY_COLUMNS = {'log_id', 'route', 'query', 'user_id', 'matched_via', 'result_course_ids', 'created_at'}
KNOWN_MODES = {'alias', 'hybrid', 'hyde_rescued', 'context', 'program', 'empty', 'rejected'}

# Do not select feedback_token_hash, expires_at, OAuth fields or arbitrary columns.
SELECT_SQL = '''
SELECT f.answer_id, f.rating, f.created_at AS feedback_created_at,
       f.updated_at AS feedback_updated_at, a.query_log_id,
       a.answer_text, a.answer_sha256, a.prompt_version, a.request_context,
       a.created_at AS answer_created_at, q.log_id AS joined_log_id,
       q.query, q.route, q.user_id AS source_marker, q.matched_via,
       q.result_course_ids, q.created_at AS query_created_at
FROM answer_feedback f
LEFT JOIN chat_answers a ON a.answer_id=f.answer_id
LEFT JOIN query_log q ON q.log_id=a.query_log_id
'''


def _date(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('Invalid date selection')
    parsed = datetime.strptime(value, '%Y-%m-%d')
    if parsed.strftime('%Y-%m-%d') != value:
        raise ValueError('Canonical date required')
    return value + ' 00:00:00'


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing timestamp')
    parsed = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    if parsed.strftime('%Y-%m-%d %H:%M:%S') != value:
        raise ValueError('Canonical SQLite UTC timestamp required')
    return parsed.strftime('%Y-%m-%dT%H:%M:%SZ')


def _json(value, budget):
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


def _candidate(row, include_private_text):
    if row['route'] != 'chat' or row['joined_log_id'] != row['query_log_id']:
        raise ValueError('Missing original chat query')
    context = _json(row['request_context'], 8192)
    captured = ReviewRequestContext.model_validate(context)
    private = PrivateCandidateText(query=row['query'], answer=row['answer_text'], request_context=context)
    if text_sha256(private.answer) != row['answer_sha256']:
        raise ValueError('Stored answer hash mismatch')
    ids = _json(row['result_course_ids'], 65536)
    if not isinstance(ids, list) or len(ids) > 1000 or any(not isinstance(item, str) or not item for item in ids):
        raise ValueError('Invalid result IDs')
    marker = row['source_marker']
    if marker is not None and not isinstance(marker, str):
        raise ValueError('Invalid original traffic marker')
    traffic = 'unmarked' if marker is None else 'eval' if marker.startswith('eval:') and len(marker) > 5 else 'unknown'
    if row['matched_via'] is not None and not isinstance(row['matched_via'], str):
        raise ValueError('Invalid retrieval mode type')
    mode = row['matched_via'] if row['matched_via'] in KNOWN_MODES else 'unknown'
    context_status = 'recorded' if set(context) == set(ReviewRequestContext.model_fields) else 'missing'
    requirements = ['privacy_review_required', 'usefulness_not_ground_truth', 'no_retrieval_snapshot']
    if traffic != 'eval':
        requirements.append('unverified_traffic_origin')
    if context_status == 'missing':
        requirements.append('missing_request_context')
    if captured.history_turn_count is None or captured.history_turn_count > 0:
        requirements.append('missing_history_content')
    if mode == 'unknown':
        requirements.append('unknown_retrieval_mode')
    data = dict(
        answer_id=row['answer_id'], query_log_id=row['query_log_id'],
        query_sha256=text_sha256(private.query), answer_sha256=row['answer_sha256'],
        request_context_sha256=context_sha256(context), prompt_version=row['prompt_version'],
        rating=row['rating'], traffic_kind=traffic,
        eval_run_sha256=text_sha256(marker) if traffic == 'eval' else None,
        retrieval_mode=mode, result_course_ids=ids,
        query_created_at=_timestamp(row['query_created_at']), answer_created_at=_timestamp(row['answer_created_at']),
        feedback_created_at=_timestamp(row['feedback_created_at']), feedback_updated_at=_timestamp(row['feedback_updated_at']),
        context_status=context_status, history_turn_count=captured.history_turn_count,
        context_course_count=len(captured.context_course_ids) if captured.context_course_ids is not None else None,
        review_state='pending', ground_truth=False, review_requirements=requirements,
    )
    # Source revision does not depend on text-export mode or receipt expiry. Unknown
    # markers/modes still affect the fingerprint without being published verbatim.
    revision_input = {**data, 'source_marker_sha256': text_sha256(marker) if marker is not None else None,
                      'source_mode_sha256': text_sha256(row['matched_via']) if isinstance(row['matched_via'], str) else None}
    return FeedbackCandidate(**data, source_revision=context_sha256(revision_input),
                             private_text=private if include_private_text else None)


def _destination(out):
    lexical = Path(out).absolute()
    if lexical.suffix.lower() != '.jsonl' or os.path.lexists(lexical):
        raise ValueError('Output must be a new JSONL file')
    parent = lexical.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError('Existing private output directory required')
    resolved = parent / lexical.name
    # Both lexical and resolved paths matter if a repository directory is a symlink.
    for path in (lexical, resolved):
        if path.is_relative_to(ROOT) and not path.is_relative_to(PRIVATE_DIRECTORY):
            raise ValueError('Repository output must stay in the ignored private directory')
    return resolved


def _publish(out, lines):
    """Complete a mode-0600 temp file, then link exclusively; never overwrite."""
    descriptor, name = tempfile.mkstemp(prefix='.feedback-review-', suffix='.tmp', dir=out.parent)
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


def export_feedback(db_path, *, out=None, origin='unmarked', since=None, until=None,
                    limit=200, include_private_text=False, ack_private_data=False):
    if type(limit) is not int or not 1 <= limit <= 1000 or origin not in ('unmarked', 'eval', 'all'):
        raise ValueError('Invalid selection')
    if type(include_private_text) is not bool or type(ack_private_data) is not bool:
        raise ValueError('Explicit boolean privacy flags required')
    if include_private_text != ack_private_data or (include_private_text and out is None):
        raise ValueError('Private text requires output and paired acknowledgement')
    lower, upper = _date(since), _date(until)
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError('Empty or reversed date window')
    destination = _destination(out) if out is not None else None
    path = Path(db_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('Existing database file required')
    conn = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    candidates, lines, byte_count, has_more = [], [], 0, False
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute('BEGIN')  # One read snapshot; no migration, commit or DML.
        info = list(conn.execute('PRAGMA table_info(query_log)'))
        columns = {row[1] for row in info}
        primary_key = [(row[1], row[2].upper()) for row in info if row[5]]
        if (not QUERY_COLUMNS.issubset(columns) or primary_key != [('log_id', 'INTEGER')]
            or not AnswerFeedbackRepository(conn).schema_available()):
            raise ValueError('Compatible existing feedback schema required')
        clauses, parameters = [], []
        if origin == 'unmarked':
            clauses.append('q.user_id IS NULL')
        elif origin == 'eval':
            clauses.append("substr(q.user_id,1,5)='eval:' AND length(q.user_id)>5")
        if lower is not None:
            clauses.append('f.updated_at>=?')
            parameters.append(lower)
        if upper is not None:
            clauses.append('f.updated_at<?')
            parameters.append(upper)
        sql = SELECT_SQL + (' WHERE ' + ' AND '.join(clauses) if clauses else '')
        sql += ' ORDER BY f.updated_at, f.answer_id LIMIT ?'
        cursor = conn.execute(sql, (*parameters, limit + 1))
        for index, row in enumerate(cursor):
            if index == limit:
                has_more = True
                break
            candidate = _candidate(row, include_private_text)
            encoded = (json.dumps(candidate.model_dump(), ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
            byte_count += len(encoded)
            if byte_count > MAX_EXPORT_BYTES:
                raise ValueError('Export outside bounded output budget; narrow selection')
            candidates.append(candidate)
            lines.append(encoded)
    finally:
        conn.close()
    # Every selected row has been validated before ANY output file is created.
    cleanup_incomplete = _publish(destination, lines) if destination is not None else False
    return dict(
        candidate_count=len(candidates), has_more=has_more, origin=origin, since=since, until=until,
        limit=limit, privacy_mode='private_text' if include_private_text else 'metadata',
        review_state='pending', ground_truth=False, written=destination is not None,
        temporary_cleanup_incomplete=cleanup_incomplete,
        traffic_counts=dict(Counter(row.traffic_kind for row in candidates)),
        rating_counts=dict(Counter(row.rating for row in candidates)),
    )


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes untrusted option values, which may contain PII.
        self.exit(2, 'Feedback export failed (arguments); no output published.\n')


def cli(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument('--db-path', required=True)
    parser.add_argument('--out')
    parser.add_argument('--origin', choices=('unmarked', 'eval', 'all'), default='unmarked')
    parser.add_argument('--since', help='Inclusive feedback.updated_at UTC date, YYYY-MM-DD')
    parser.add_argument('--until', help='Exclusive feedback.updated_at UTC date, YYYY-MM-DD')
    parser.add_argument('--limit', type=int, default=200)
    parser.add_argument('--include-private-text', action='store_true')
    parser.add_argument('--ack-private-data', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = export_feedback(**vars(args))
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError):
        print('Feedback export failed (input/storage); no output published.', file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(cli())
