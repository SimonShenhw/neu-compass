"""Validate/add scoped plan documents to an EXISTING DB; read-only by default.

--commit creates only v1.5 and stores all documents in one transaction.
No network, no guessed source URLs, no legacy seed/course/index rewrites.
A file that would replace a fingerprinted or source-checked plan with a weaker
version (e.g. the core layer re-run after the extended one), or a fingerprinted
capture with an older one, is refused, dry run included; --allow-downgrade makes
such a replacement deliberate. On success stdout is exactly the JSON report;
warnings go to stderr.
中文：只对显式数据库操作；先副本演练，不自动替换运行库。若会用较弱版本覆盖已带指纹
或已 source_checked 的方案（例如在 extended 之后单独重跑 core），或用更早的抓取覆盖
带指纹的抓取，整份文件被拒绝（dry-run 同样）；确需覆盖时显式加 --allow-downgrade。
成功时 stdout 只有 JSON 报告，告警写到 stderr。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import structlog

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.program_plan_repository import (  # noqa: E402
    PlanDowngradeError,
    ProgramPlanRepository,
    content_hash,
    provenance_downgrade,
)
from db.schema_blocks import begin_schema_migration, schema_block  # noqa: E402
from schemas.program_plan import ProgramPlan  # noqa: E402
from schemas.program_source import verify_archived_source  # noqa: E402


def migration_sql() -> str:
    return schema_block("PROGRAM_PLANS_V1_5")


def sync_plans(db_path: str | Path, plan_file: str | Path, *, commit: bool = False, source_dir: str | Path | None = None,
               allow_downgrade: bool = False) -> dict:
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
        # The whole file is checked before the first write, inside the write
        # transaction when committing, so a refusal lists every affected plan. Slots
        # are checked first, from the row columns exactly as store() does, so a
        # rebinding error is not masked and dry run and commit judge alike.
        # 中文：第一次写入前先检查整份文件（commit 时在写事务内），拒绝时列出全部受影响方案；
        # 先按行的列值检查范围（与 store() 一致），换绑错误不被掩盖，dry-run 与 commit 判断相同。
        downgrades = []
        for plan in plans:
            repo.validate_slot(plan)
            reason = provenance_downgrade(repo.recorded(plan.plan_id), plan)
            if reason:
                downgrades.append({"plan_id": plan.plan_id, "reason": reason})
        if downgrades and not allow_downgrade:
            raise PlanDowngradeError(downgrades)
        if downgrades:
            report["downgraded"] = downgrades
        for plan in plans:
            if not conn.execute("SELECT 1 FROM programs WHERE program_id=?", (plan.program_id,)).fetchone():
                raise ValueError("Plan references an unseeded program")
            repo.validate_slot(plan)
            existing = repo.list_for_program(plan.program_id) if repo.available() else []
            same_id = next((item for item in existing if item.plan_id == plan.plan_id), None)
            changed = same_id is None or content_hash(same_id) != content_hash(plan)
            report["would_store"] += int(changed)
            if commit:
                report["stored"] += int(repo.store(plan, allow_downgrade=allow_downgrade))
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
    parser.add_argument("--allow-downgrade", action="store_true",
                        help="Deliberately replace fingerprinted/source-checked plans with weaker versions")
    args = parser.parse_args()
    # Library warnings (e.g. program.plan_unusable) go to stderr: stdout is the JSON report.
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    try:
        print(json.dumps(sync_plans(args.db_path, args.plan_file, commit=args.commit, source_dir=args.source_dir,
                                    allow_downgrade=args.allow_downgrade)))
    except PlanDowngradeError as exc:
        listed = ", ".join(f"{item['plan_id']} ({item['reason']})" for item in exc.downgrades)
        print(f"Program plan sync refused; nothing was written. Already stored with more verified or newer "
              f"provenance than this file has: {listed}. To update the other plans, sync a file that leaves "
              "these out; to replace these on purpose (e.g. the source page really reverted to an older "
              "capture), pass --allow-downgrade.")
        return 1
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"Program plan sync failed ({type(exc).__name__}); no transaction committed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
