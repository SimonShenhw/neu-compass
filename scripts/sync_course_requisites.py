"""Import verified archive clauses into an EXISTING DB; read-only by default.

--commit creates only v1.6 and stores all selected course/year documents
atomically. No course/legacy-edge/index rewrites, no network or inferred IDs.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from db.course_requisite_repository import CourseRequisiteRepository  # noqa: E402
from schemas.course_requisite_document import CourseRequisiteDocument  # noqa: E402
from scripts.audit_course_requisites import build_report  # noqa: E402


def migration_sql() -> str:
    sql = (ROOT / "db/init.sql").read_text(encoding="utf-8")
    return sql.split("-- BEGIN COURSE_REQUISITES_V1_6", 1)[1].split("-- END COURSE_REQUISITES_V1_6", 1)[0]


def sync_requisites(db_path: str | Path, manifest_file: str | Path, source_dir: str | Path,
                    course_codes: list[str], *, commit: bool = False) -> dict:
    path = Path(db_path).resolve(strict=True)
    # All HTML/sidecars/selection identities are validated before opening a DB.
    inputs = build_report(Path(manifest_file), Path(source_dir), course_codes)
    conn = sqlite3.connect(f"{path.as_uri()}?mode={'rw' if commit else 'ro'}", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='courses'").fetchone():
            raise ValueError("Existing course schema required")
        repo = CourseRequisiteRepository(conn)
        report = {"records": len(inputs["records"]), "unparsed_sections": inputs["unparsed_sections"],
                  "schema_missing": not repo.available(), "committed": commit, "would_store": 0, "stored": 0}
        documents = []
        for record in inputs["records"]:
            matches = conn.execute("SELECT course_id,primary_name FROM courses WHERE primary_code=?", (record["course_code"],)).fetchall()
            if len(matches) != 1 or matches[0]["primary_name"] != record["course_name"]:
                raise ValueError("Selected source course must match one existing code and exact title")
            document = CourseRequisiteDocument(course_id=matches[0]["course_id"], course_code=record["course_code"],
                course_name=record["course_name"], catalog_year=record["catalog_year"], source=record["source"], requisites=record["requisites"],
                description_evidence=record["description_evidence"], credit_hours=record["credit_hours"])
            documents.append(document)
            report["would_store"] += int(repo.needs_store(document))
        if commit:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript("BEGIN IMMEDIATE;\n" + migration_sql())
            for document in documents:
                report["stored"] += int(repo.store(document))
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
    parser.add_argument("--manifest-file", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--course-code", action="append", required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(sync_requisites(args.db_path, args.manifest_file, args.source_dir, args.course_code, commit=args.commit)))
        # Unknown clauses are intentionally stored with unparsed status. This
        # exit code reports sync success, not full syntax or eligibility success.
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Course requisite sync failed ({type(exc).__name__}); no transaction committed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
