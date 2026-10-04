"""db.schema_blocks — one marker parser for every additive migration script."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from db.schema_blocks import INIT_SQL, begin_schema_migration, schema_before_block, schema_block

BLOCKS = {
    "COOP_MODERATION_V1_3": "coop_submissions",
    "CATALOG_SOURCES_V1_4": "course_catalog_sources",
    "PROGRAM_PLANS_V1_5": "program_plans",
    "COURSE_REQUISITES_V1_6": "course_requisite_documents",
    "ANSWER_FEEDBACK_V1_7": "chat_answers",
}


@pytest.mark.parametrize("name,table", BLOCKS.items())
def test_every_migration_block_parses_and_creates_its_table(name, table) -> None:
    assert f"CREATE TABLE IF NOT EXISTS {table}" in schema_block(name)


def test_scripts_delegate_to_the_shared_parser() -> None:
    """Each script keeps its migration_sql() hook (tests inject failing SQL
    through it) but no longer re-implements the marker split or opens the
    migration transaction itself."""
    import scripts.migrate_answer_feedback as feedback  # noqa: PLC0415
    import scripts.migrate_coop_submissions as coop  # noqa: PLC0415
    import scripts.sync_catalog_sources as catalog  # noqa: PLC0415
    import scripts.sync_course_requisites as requisites  # noqa: PLC0415
    import scripts.sync_program_plans as plans  # noqa: PLC0415

    pairs = [(coop, "COOP_MODERATION_V1_3"), (catalog, "CATALOG_SOURCES_V1_4"),
             (plans, "PROGRAM_PLANS_V1_5"), (requisites, "COURSE_REQUISITES_V1_6"),
             (feedback, "ANSWER_FEEDBACK_V1_7")]
    for module, name in pairs:
        assert module.migration_sql() == schema_block(name)
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert '.split("-- BEGIN' not in source and ".split('-- BEGIN" not in source
        assert "executescript(" not in source
        assert "begin_schema_migration(conn, migration_sql())" in source


def test_schema_migration_leaves_the_transaction_open_for_the_caller() -> None:
    conn = sqlite3.connect(":memory:")
    begin_schema_migration(conn, "CREATE TABLE t (x INTEGER);")
    assert conn.in_transaction
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.execute("INSERT INTO t VALUES (1)")
    conn.rollback()  # the DDL and the rows roll back together
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='t'").fetchone() is None


def test_schema_migration_refuses_a_pending_transaction() -> None:
    """executescript() would silently COMMIT the caller's pending write."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a (x INTEGER)")
    conn.execute("INSERT INTO a VALUES (1)")  # implicit BEGIN, not committed
    with pytest.raises(RuntimeError, match="pending transaction"):
        begin_schema_migration(conn, "CREATE TABLE t (x INTEGER);")
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM a").fetchone()[0] == 0
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='t'").fetchone() is None


def test_before_block_is_the_older_schema() -> None:
    before = schema_before_block("COOP_MODERATION_V1_3")
    assert "coop_experiences" in before and "coop_submissions" not in before


@pytest.mark.parametrize("text", [
    "-- BEGIN X\nSELECT 1;\n",                                  # no END
    "-- BEGIN X\nSELECT 1;\n-- END X\n-- BEGIN X\n-- END X\n",  # duplicated
    "-- END X\nSELECT 1;\n-- BEGIN X\n",                        # out of order
    "-- BEGIN X\n   \n-- END X\n",                              # empty
])
def test_malformed_markers_fail_loudly(tmp_path, text) -> None:
    path = tmp_path / "init.sql"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        schema_block("X", init_sql=path)


def test_default_points_at_the_repo_init_sql() -> None:
    assert INIT_SQL.name == "init.sql" and INIT_SQL.exists()
