"""Offline curator review. Explicit DB path; approve/reject dry-run by default.

Approval requires a FULL sanitized CoopUploadRequest JSON replacement and audit.
The CLI is operator-only, not exposed through a public HTTP/admin endpoint.
中文：运维本地审核；批准需完整脱敏 JSON、审核人和审计说明，默认不写库。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError  # noqa: E402
from api.models import CoopUploadRequest  # noqa: E402
from db.coop_submission_repository import CoopSubmissionRepository  # noqa: E402
from schemas.coop import CoopExperience  # noqa: E402


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true")
    action.add_argument("--show", metavar="COOP_ID", help="Operator-only raw payload; may contain PII")
    action.add_argument("--approve", metavar="COOP_ID")
    action.add_argument("--reject", metavar="COOP_ID")
    parser.add_argument("--redacted-file", help="Full sanitized upload JSON; required for approval")
    parser.add_argument("--reviewer")
    parser.add_argument("--audit")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    writing = bool(args.commit and (args.approve or args.reject))
    conn = None
    try:
        path = Path(args.db_path).resolve(strict=True)
        conn = sqlite3.connect(f"{path.as_uri()}?mode={'rw' if writing else 'ro'}", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        repo = CoopSubmissionRepository(conn)
        if args.list:
            print(json.dumps([
                {"coop_id": row["coop_id"], "status": row["review_status"]}
                for row in repo.list_queue()
            ]))
            return 0
        row = repo.get(args.show or args.approve or args.reject)
        if args.show:
            print(row["payload"])
            return 0
        if not args.reviewer or not args.reviewer.strip() or not args.audit or not args.audit.strip():
            raise ValueError("Reviewer and audit required")
        redacted = None
        if args.approve:
            if not args.redacted_file:
                raise ValueError("Approval requires a sanitized replacement file")
            payload = CoopUploadRequest.model_validate_json(Path(args.redacted_file).read_text(encoding="utf-8-sig"))
            redacted = CoopExperience(
                coop_id=row["coop_id"], contributor_user_id=row["contributor_user_id"], **payload.model_dump(),
            )
        if not writing:
            print(f"Read-only dry-run: would {'approve' if args.approve else 'reject'} {row['coop_id']}; no changes.")
            return 0
        published = repo.review(
            row["coop_id"], approve=bool(args.approve), reviewer=args.reviewer,
            audit=args.audit, redacted=redacted,
        )
        conn.commit()
        print(json.dumps({"status": repo.get(row["coop_id"])["review_status"], "published_ids": published}))
        return 0
    except (OSError, sqlite3.Error, ValueError, LookupError, ValidationError) as exc:
        if conn is not None:
            conn.rollback()
        # Never echo validation inputs or private free text to routine logs.
        print(f"Review failed ({type(exc).__name__}); check DB/schema, ID, sanitized payload and audit.")
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(cli())
