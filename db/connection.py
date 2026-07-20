"""SQLite connection helper.

Why a wrapper:
- PRAGMA foreign_keys is per-connection (SQLite default is OFF).
  Forgetting it lets FK violations through silently — every Repository
  user must go through connect() to be safe.
- Row factory set to sqlite3.Row so callers get column-name access.

为什么需要一个封装:
- PRAGMA foreign_keys 是按连接(per-connection)生效的(SQLite 默认是
  关闭的)。忘记设置这一条,外键违规就会被静默放行 —— 所有用到
  Repository 的地方都必须走 connect() 才安全。
- row_factory 设为 sqlite3.Row,这样调用方可以按列名取值。
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

    中文:打开一个带项目标准 pragma + row factory 的 SQLite 连接。

    之所以要 `check_same_thread=False`,是因为 FastAPI 的 TestClient 和
    异步路由 handler 可能把同一个连接从事件循环线程搬到线程池 worker 上
    使用。我们仍然保证每个连接同一时刻只服务一个使用者(在请求的生命
    周期内),所以不需要额外加锁 —— 只要不是真正的并发访问,SQLite
    内部的串行化机制(CPython sqlite3 模块的 threadsafety=1)就足以保证
    跨线程访问的安全性。
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    # foreign_keys must be turned on for THIS connection — see the module
    # docstring's "why a wrapper" note; SQLite defaults it to OFF per-connection.
    # 中文:foreign_keys 必须针对这个连接单独打开 —— 详见上面模块级
    # docstring 里"为什么需要一个封装"的说明;SQLite 对每个连接默认关闭
    # 这个开关。
    conn.execute("PRAGMA foreign_keys = ON")
    # busy_timeout is per-connection (unlike WAL, which persists in the db
    # file). Without it a write that collides with another writer raises
    # "database is locked" IMMEDIATELY instead of waiting its turn — easy to
    # hit once API routes run in the threadpool alongside ingest scripts.
    # 中文:busy_timeout 也是按连接生效的(不像 WAL 模式那样持久化写在 db
    # 文件里)。不设置的话,一次写入只要跟另一个写者撞上,就会立刻抛出
    # "database is locked" 错误,而不是排队等到轮到自己 —— 一旦 API 路由
    # 跑在线程池里、又和数据摄取(ingest)脚本同时写库,很容易踩到这个坑。
    conn.execute("PRAGMA busy_timeout = 5000")
    # NORMAL is the standard pairing with WAL (set persistently in init.sql):
    # fsync on checkpoint rather than every commit. Durability loss is limited
    # to power-loss-after-commit, acceptable for rebuildable data (ADR-0013).
    # 中文:synchronous=NORMAL 是与 WAL 模式(已在 init.sql 里持久化设置)
    # 标配的搭档:只在 checkpoint 时 fsync,而不是每次 commit 都 fsync。
    # 由此带来的唯一耐久性(durability)风险,是"commit 之后立刻断电"这一种
    # 情况 —— 对于可重建的数据(ADR-0013)来说,这个代价可以接受。
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def open_repository(db_path: str | Path) -> Iterator["CourseRepository"]:
    """Convenience context manager: open conn, yield repository, commit on success.

    Rolls back on exception. Always closes.

    中文:便捷的上下文管理器 —— 打开连接、yield 出仓储对象、成功时
    commit;出现异常则 rollback;无论如何都会 close 连接。
    """
    from db.repository import CourseRepository  # noqa: PLC0415 (avoid circular import)
    # 中文:延迟导入(deferred import),用来避免循环导入(circular import)。

    conn = connect(db_path)
    try:
        yield CourseRepository(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
