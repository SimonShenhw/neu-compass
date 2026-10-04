"""Named additive schema blocks inside db/init.sql (the single source of truth).

`-- BEGIN NAME` / `-- END NAME` markers delimit each block; the migration and
sync scripts apply exactly ONE block to an existing database. The marker
parsing and the transaction that applies a block live here once instead of
being copy-pasted into every script, so a marker typo, a duplicated block or
a pending transaction fails loudly in one place.

中文：db/init.sql 里带名字的增量 schema 区块（唯一事实来源）。
`-- BEGIN NAME` / `-- END NAME` 标记界定每个区块；迁移与同步脚本只把其中
一个区块应用到已有数据库。标记解析和应用区块的事务只在这里实现一次，
不再复制到每个脚本里；标记写错、区块重复或连接已在事务中时，都会在同一个
地方明确报错。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

INIT_SQL = Path(__file__).resolve().parent / "init.sql"


def schema_block(name: str, *, init_sql: Path = INIT_SQL) -> str:
    """Return the SQL between `-- BEGIN {name}` and `-- END {name}`.

    Raises ValueError unless both markers occur exactly once, in order, with
    a non-empty block between them.
    中文：返回 `-- BEGIN {name}` 与 `-- END {name}` 之间的 SQL。两个标记必须
    各出现且只出现一次、顺序正确、中间不为空，否则抛 ValueError。
    """
    text = init_sql.read_text(encoding="utf-8-sig")
    begin, end = f"-- BEGIN {name}", f"-- END {name}"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError(f"init.sql must contain exactly one {name} block")
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    if stop <= start or not text[start:stop].strip():
        raise ValueError(f"init.sql block {name} is empty or out of order")
    return text[start:stop]


def schema_before_block(name: str, *, init_sql: Path = INIT_SQL) -> str:
    """Everything in init.sql BEFORE `-- BEGIN {name}` — i.e. the schema an
    older database had before that block's migration (rehearsal fixtures).
    中文：init.sql 中 `-- BEGIN {name}` 之前的全部内容 —— 也就是执行该区块
    迁移之前旧数据库的 schema（供演练夹具使用）。"""
    schema_block(name, init_sql=init_sql)  # same marker validation
    text = init_sql.read_text(encoding="utf-8-sig")
    return text[: text.index(f"-- BEGIN {name}")]


def begin_schema_migration(conn: sqlite3.Connection, block_sql: str) -> None:
    """Open an IMMEDIATE write transaction on `conn` and run `block_sql` in it.

    The transaction is left OPEN: the caller validates and stores its rows,
    then commits, or rolls back on any error, so the DDL and the data land
    together. executescript() silently COMMITs a pending transaction before
    it runs (and PRAGMA foreign_keys is a no-op inside one), so a connection
    that is already mid-transaction is refused instead.
    中文：在 `conn` 上开启 IMMEDIATE 写事务并在其中执行 `block_sql`。
    事务保持打开：调用方校验并写入数据后自行提交，出错则回滚，DDL 与数据
    一起落地。executescript() 会先悄悄提交未完成的事务（事务内 PRAGMA
    foreign_keys 也不生效），所以已在事务中的连接会被直接拒绝。
    """
    if conn.in_transaction:
        raise RuntimeError("Schema migration needs a connection with no pending transaction")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript("BEGIN IMMEDIATE;\n" + block_sql)


__all__ = ["INIT_SQL", "begin_schema_migration", "schema_before_block", "schema_block"]
