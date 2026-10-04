"""Add/backfill explicit catalog provenance from existing JSONL archives.

No network, no raw_text guesses, no Course JSON/status/index changes. Default:
read-only report. --commit creates the v1.4 table and stores matched snapshots
in ONE transaction; requires an explicit existing DB and archive directory.
中文：从已有目录存档补来源；默认只读，不重跑清空富化字段的目录摄取流程。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.catalog_source_repository import CatalogSourceRepository  # noqa: E402
from schemas.answer_evidence import CatalogSnapshot  # noqa: E402
from scrapers.neu_catalog import CatalogEntry  # noqa: E402


def migration_sql() -> str:
    sql = (PROJECT_ROOT / "db" / "init.sql").read_text(encoding="utf-8")
    return sql.split("-- BEGIN CATALOG_SOURCES_V1_4", 1)[1].split("-- END CATALOG_SOURCES_V1_4", 1)[0]


def sync_sources(db_path: str | Path, catalog_dir: str | Path, *, commit: bool = False) -> dict:
    path = Path(db_path).resolve(strict=True)
    archive = Path(catalog_dir).resolve(strict=True)
    files = sorted(archive.glob("*.jsonl"))
    if not files:
        raise ValueError("No JSONL catalog archives found")
    # Validate ALL source records before any DDL/DML, including duplicate conflicts.
    snapshots: dict[str, CatalogSnapshot] = {}
    for source in files:
        with source.open(encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                entry = CatalogEntry.model_validate_json(line)
                snapshot = CatalogSourceRepository.snapshot(entry)
                previous = snapshots.get(snapshot.course_code)
                if previous and previous.snapshot_id != snapshot.snapshot_id:
                    raise ValueError("Conflicting archived records for the same course code")
                snapshots[snapshot.course_code] = snapshot
    conn = sqlite3.connect(f"{path.as_uri()}?mode={'rw' if commit else 'ro'}", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        repo = CatalogSourceRepository(conn)
        schema_missing = not repo.available()
        report = {"records": len(snapshots), "matched": 0, "skipped_unknown_or_ambiguous": 0,
                  "skipped_title_mismatch": 0, "unchanged": 0, "stored": 0,
                  "schema_missing": schema_missing, "committed": commit}
        if commit:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            # Keep DDL open in the same transaction as all subsequent stores.
            conn.executescript("BEGIN IMMEDIATE;\n" + migration_sql())
        planned = []
        for snapshot in snapshots.values():
            matches = conn.execute(
                "SELECT course_id, primary_name FROM courses WHERE primary_code=?", (snapshot.course_code,),
            ).fetchall()
            if len(matches) != 1:
                report["skipped_unknown_or_ambiguous"] += 1
                continue
            row = matches[0]
            if row["primary_name"] != snapshot.course_name:
                report["skipped_title_mismatch"] += 1
                continue
            report["matched"] += 1
            previous = None if schema_missing else conn.execute(
                "SELECT snapshot FROM course_catalog_sources WHERE course_id=?", (row["course_id"],),
            ).fetchone()
            if previous:
                try:
                    prior = CatalogSnapshot.model_validate_json(previous["snapshot"])
                    excluded = {"snapshot_id", "imported_at", "retrieved_at"}
                    if (prior.snapshot_id == snapshot.snapshot_id
                            and prior.model_dump(exclude=excluded) == snapshot.model_dump(exclude=excluded)):
                        report["unchanged"] += 1
                        continue
                except ValueError:
                    pass
            planned.append((row["course_id"], snapshot))
        report["would_store"] = len(planned)
        if commit:
            for cid, snapshot in planned:
                repo.store(cid, snapshot)
            conn.commit()
            report["stored"] = len(planned)
        return report
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cli() -> int:
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--catalog-dir", required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    try:
        report = sync_sources(args.db_path, args.catalog_dir, commit=args.commit)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"Catalog source sync failed ({type(exc).__name__}); no transaction committed.")
        return 1
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
