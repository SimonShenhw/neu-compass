"""Backup sidecar — daily SQLite snapshot loop for the NAS stack.

Why a compose service instead of host cron: UGOS has no Task Scheduler
GUI and no user crontab, and the 2026-07-02 outage showed host-level
anything (ACLs, container restart policies) can be yanked by a UGOS
update. A sidecar in the same compose file needs ZERO host setup, ships
with `deploy.ps1`, and `restart: always` resurrects it like the rest of
the stack.

为什么用 compose 服务而不是宿主机 cron:UGOS 既没有 Task Scheduler
图形界面,也没有用户级 crontab,而 2026-07-02 那次故障说明,任何
宿主机层面的东西(ACL、容器重启策略)都可能被一次 UGOS 更新连根拔起。
放在同一个 compose 文件里的 sidecar 服务完全不需要宿主机额外设置,
随 `deploy.ps1` 一起发布,`restart: always` 也会像栈里其他服务一样
让它自动复活。

Behavior:
  - One snapshot immediately on start (so every deploy day has one),
    then one per day at ~04:10 container time.
  - Snapshots via sqlite3's Online Backup API — safe against concurrent
    writers (a plain cp of a live WAL database is not).
  - Keeps the newest KEEP snapshots, deletes the rest.
  - Skips (with a log line) when a snapshot for today already exists,
    so container restarts don't pile up extras.

行为:
  - 启动时立即做一次快照(这样每个部署日都至少有一份),之后每天在
    容器本地时间约 04:10 做一次。
  - 通过 sqlite3 的 Online Backup API 做快照 —— 对并发写入是安全的
    (直接 cp 一个正在写入的 WAL 数据库文件则不安全)。
  - 只保留最新的 KEEP 份快照,其余全部删除。
  - 如果今天的快照已经存在就跳过(并打一行日志),这样容器重启不会
    堆出多余的快照。

Run (compose): python scripts/backup_daemon.py
One-shot mode (manual/testing): python scripts/backup_daemon.py --once

运行方式(compose):python scripts/backup_daemon.py
单次模式(手动 / 测试):python scripts/backup_daemon.py --once
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path("/data/courses.db")
BACKUP_DIR = Path("/data/backups")
KEEP = 14
# 中文:保留最新的 14 份快照,其余的一律删除
DAILY_AT_HOUR = 4
DAILY_AT_MINUTE = 10
# 中文:每天 04:10(容器本地时间)执行一次


def _log(msg: str) -> None:
    # 中文:统一的日志输出:加时间戳前缀,并立即 flush(容器日志需要
    # 实时可见,不能被缓冲区攒着)。
    print(f"[backup] {dt.datetime.now().isoformat(timespec='seconds')} {msg}",
          flush=True)


def take_snapshot() -> Path | None:
    """One Online-Backup snapshot; returns the path (None when skipped
    because today's snapshot already exists).

    中文:执行一次 Online-Backup 快照;返回快照文件路径(若今天的快照
    已经存在因而被跳过,则返回 None)。
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().strftime("%Y%m%d")
    existing_today = sorted(BACKUP_DIR.glob(f"courses-{today}-*.db"))
    if existing_today:
        _log(f"snapshot for {today} already exists "
             f"({existing_today[-1].name}); skipping")
        return None

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"courses-{stamp}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        # Online Backup API (sqlite3.Connection.backup): copies page-by-page
        # under SQLite's own locking, so it's safe even while
        # /data/courses.db is being written by the API/ingest process — a
        # plain file copy of a live WAL database could grab a torn/
        # inconsistent snapshot.
        # 中文:Online Backup API(sqlite3.Connection.backup)在 SQLite 自身
        # 的加锁保护下逐页拷贝,因此即使 /data/courses.db 正被 API /
        # 摄取(ingest)进程写入,拷贝依然安全 —— 对处于 WAL 模式且正在
        # 写入的数据库做普通文件拷贝,则可能拿到一份撕裂 / 不一致的快照。
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    _log(f"snapshot ok: {dest.name} "
         f"({dest.stat().st_size / 1_048_576:.1f} MB)")

    snapshots = sorted(BACKUP_DIR.glob("courses-*.db"))
    # Lexicographic sort on the "courses-YYYYMMDD-HHMMSS.db" naming scheme
    # equals chronological order, so slicing off everything but the last
    # KEEP entries and deleting the rest prunes the oldest snapshots first.
    # 中文:按 "courses-YYYYMMDD-HHMMSS.db" 这种命名方式做字典序排序,
    # 结果正好等价于按时间先后排序,所以只保留最后 KEEP 个、删除其余的,
    # 就能优先清理最旧的快照。
    for old in snapshots[:-KEEP]:
        old.unlink()
        _log(f"pruned: {old.name}")
    return dest


def _seconds_until_next_run() -> float:
    # 中文:算出距离下一次运行(容器本地时间 DAILY_AT_HOUR:DAILY_AT_MINUTE)
    # 还有多少秒;如果今天的这个时间点已经过去,就顺延到明天同一时间。
    now = dt.datetime.now()
    target = now.replace(hour=DAILY_AT_HOUR, minute=DAILY_AT_MINUTE,
                         second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--once", action="store_true",
                    help="Take one snapshot and exit (manual/testing).")
    args = ap.parse_args()

    if not DB_PATH.exists():
        _log(f"ERROR: {DB_PATH} not found — is /data mounted?")
        return 1

    take_snapshot()
    if args.once:
        return 0

    while True:
        wait = _seconds_until_next_run()
        _log(f"next run in {wait / 3600:.1f}h")
        time.sleep(wait)
        try:
            take_snapshot()
        except Exception as e:  # noqa: BLE001 — the loop must survive
            # 中文:noqa: BLE001 —— 这里故意捕获所有异常,因为这个循环
            # 绝不能因为某一次快照失败就整体退出。
            _log(f"ERROR: snapshot failed: {type(e).__name__}: {e}")
            time.sleep(300)  # brief backoff, then re-enter the loop
            # 中文:短暂退避(backoff)后,重新进入循环。


if __name__ == "__main__":
    sys.exit(main())
