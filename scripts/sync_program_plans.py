"""Validate/add scoped plan documents to an EXISTING DB; read-only by default.

--commit creates only v1.5 and stores all documents in one transaction.
No network, no guessed source URLs, no legacy seed/course/index rewrites.
中文：只对显式数据库操作；先副本演练，不自动替换运行库。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.program_plan_repository import ProgramPlanRepository, content_hash  # noqa: E402
from db.schema_blocks import begin_schema_migration, schema_block  # noqa: E402
from schemas.program_plan import ProgramPlan  # noqa: E402
from schemas.program_source import verify_archived_source  # noqa: E402


def migration_sql() -> str:
    return schema_block("PROGRAM_PLANS_V1_5")


def sync_plans(db_path: str | Path, plan_file: str | Path, *, commit: bool = False, source_dir: str | Path | None = None) -> dict:
    path = Path(db_path).resolve(strict=True)
    payload = json.loads(Path(plan_file).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("Plan file must be an array of scoped rule documents")
    plans = [ProgramPlan.model_validate(item) for item in payload]
    for plan in plans:
        if plan.source_html_sha256:
            if source_dir is None:
                raise ValueError("Fingerprinted plans require the explicit source archive directory")
            verify_archived_source(plan, Path(source_dir))
    if len({plan.plan_id for plan in plans}) != len(plans) or len({plan.scope_key() for plan in plans}) != len(plans):
        raise ValueError("Duplicate plan ID or scope in file")
    conn = sqlite3.connect(f"{path.as_uri()}?mode={'rw' if commit else 'ro'}", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        repo = ProgramPlanRepository(conn)
        report = {"records": len(plans), "schema_missing": not repo.available(), "committed": commit, "would_store": 0, "stored": 0}
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='programs'").fetchone():
            raise ValueError("Existing program schema required")
        if commit:
            begin_schema_migration(conn, migration_sql())
        for plan in plans:
            if not conn.execute("SELECT 1 FROM programs WHERE program_id=?", (plan.program_id,)).fetchone():
                raise ValueError("Plan references an unseeded program")
            repo.validate_slot(plan)
            existing = repo.list_for_program(plan.program_id) if repo.available() else []
            same_id = next((item for item in existing if item.plan_id == plan.plan_id), None)
            changed = same_id is None or content_hash(same_id) != content_hash(plan)
            report["would_store"] += int(changed)
            if commit:
                report["stored"] += int(repo.store(plan))
        if commit:
            conn.commit()
        return report
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--plan-file", required=True)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--source-dir", help="Required for fingerprinted inputs; verifies existing archives offline")
    args = parser.parse_args()
    try:
        print(json.dumps(sync_plans(args.db_path, args.plan_file, commit=args.commit, source_dir=args.source_dir)))
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"Program plan sync failed ({type(exc).__name__}); no transaction committed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
