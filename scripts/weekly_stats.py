"""Read-only counts for the weekly trial check (batch T, policy P7): no question text, emails or IDs.

Opens the database read-only in one snapshot (the same helper as the exports) and prints one JSON object:
- questions per UTC day of the window, by route and by traffic (unmarked = no X-Eval-Run header, which is not proof
  of a real person; eval; unknown), plus the retrieval modes of unmarked questions;
- answer votes (up / down) by the day they were last changed, and saved answers created in the window;
- accounts in total and created in the window; Co-op submissions waiting for review and published;
- today's model calls from `model_budget.json` next to the database, when the file exists.
Nothing is written. Running it on the NAS is still touching the NAS: ask the user first (P7).

中文：每周试用检查用的只读计数（T 批，政策 P7）：不输出问题原文、邮箱或 ID。以只读方式在一次快照里打开数据库（和导出
用同一个工具），输出一个 JSON：窗口内每个 UTC 日的提问数（按路由和流量分：unmarked＝没带 X-Eval-Run，不能证明是真人；
eval；unknown），unmarked 提问的检索方式；按最后修改日期计的 👍／👎，窗口内新保存的回答；账号总数和窗口内新建的；
等审核和已公开的 Co-op 投稿；如果有 `model_budget.json`，今天的模型调用次数。不写任何东西。在 NAS 上跑仍然算碰 NAS，
要先问用户（P7）。
"""

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.private_export import SafeArgumentParser, open_read_snapshot, retrieval_mode, traffic_kind  # noqa: E402


class StatsArgumentParser(SafeArgumentParser):
    failure = 'Weekly stats failed (arguments); nothing read.\n'


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def weekly_stats(db_path, *, days=7, today=None):
    if type(days) is not int or not 1 <= days <= 31:
        raise ValueError('days must be 1-31')
    today = today or datetime.now(timezone.utc).date()
    first = today - timedelta(days=days - 1)
    lower, upper = f'{first.isoformat()} 00:00:00', f'{(today + timedelta(days=1)).isoformat()} 00:00:00'
    conn = open_read_snapshot(db_path)
    try:
        tables = _tables(conn)
        per_day = {(first + timedelta(days=i)).isoformat(): Counter() for i in range(days)}
        modes = Counter()
        for row in conn.execute('SELECT created_at, route, matched_via, user_id FROM query_log '
                                'WHERE julianday(created_at) >= julianday(?) AND julianday(created_at) < julianday(?)',
                                (lower, upper)):
            day = str(row['created_at'])[:10]
            traffic, route = traffic_kind(row['user_id']), row['route'] if row['route'] in ('search', 'chat') else 'other'
            if day in per_day:
                per_day[day][f'{traffic}_{route}'] += 1
            if traffic == 'unmarked':
                modes[retrieval_mode(row['matched_via'])] += 1
        report = {'window': {'first_day': first.isoformat(), 'last_day': today.isoformat(), 'days': days},
                  'questions_per_day': {day: dict(sorted(counts.items())) for day, counts in per_day.items()},
                  'unmarked_retrieval_modes': dict(sorted(modes.items()))}
        if {'answer_feedback', 'chat_answers'} <= tables:
            votes = Counter(row[0] for row in conn.execute(
                'SELECT rating FROM answer_feedback WHERE julianday(updated_at) >= julianday(?) '
                'AND julianday(updated_at) < julianday(?)', (lower, upper)))
            report['votes'] = {'up': votes['up'], 'down': votes['down']}
            report['saved_answers'] = conn.execute(
                'SELECT count(*) FROM chat_answers WHERE julianday(created_at) >= julianday(?) '
                'AND julianday(created_at) < julianday(?)', (lower, upper)).fetchone()[0]
        report['accounts'] = {
            'total': conn.execute('SELECT count(*) FROM users').fetchone()[0],
            'created_in_window': conn.execute('SELECT count(*) FROM users WHERE julianday(created_at) >= julianday(?) '
                                              'AND julianday(created_at) < julianday(?)', (lower, upper)).fetchone()[0]}
        if 'coop_submissions' in tables:
            status = Counter(row[0] for row in conn.execute('SELECT review_status FROM coop_submissions'))
            report['coop_submissions'] = {'pending': status['pending'], 'published': status['published']}
    finally:
        conn.close()
    budget = Path(db_path).resolve().parent / 'model_budget.json'
    try:
        data = json.loads(budget.read_text(encoding='utf-8'))
        if data.get('day') == today.isoformat() and type(data.get('calls')) is int:
            report['model_calls_today'] = data['calls']
    except (OSError, ValueError, AttributeError):
        pass
    return report


def cli(argv=None):
    parser = StatsArgumentParser(description=__doc__)
    parser.add_argument('--db-path', required=True)
    parser.add_argument('--days', type=int, default=7, help='Window length in UTC days, 1-31, ending today')
    parser.add_argument('--today', help='Last day of the window, YYYY-MM-DD (default: today, UTC)')
    args = parser.parse_args(argv)
    try:
        today = date.fromisoformat(args.today) if args.today else None
        report = weekly_stats(args.db_path, days=args.days, today=today)
    except (OSError, sqlite3.Error, ValueError, TypeError):
        print('Weekly stats failed (input/storage); nothing written.', file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(cli())
