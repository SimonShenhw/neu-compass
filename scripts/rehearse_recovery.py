"""Disaster recovery rehearsal CLI and verification engine (Batch 08D).

Performs end-to-end disaster recovery rehearsals in an isolated, temporary
sandbox directory without touching production databases, network endpoints,
or live environment state.

Rehearsal steps:
  1. Prepare/validate backup source (SQLite snapshot + FAISS index & manifest).
  2. Restore SQLite snapshot into clean target directory.
  3. Verify SQLite integrity (`PRAGMA integrity_check`, `PRAGMA foreign_key_check`, schema table count).
  4. Restore or rebuild FAISS index from restored SQLite.
  5. Verify FAISS index manifest and SHA-256 checksums.
  6. Execute read-only retrieval validation (vector search & SQLite cross-check).
  7. Generate structured audit report and automatically clean up sandbox state.

Usage:
    python scripts/rehearse_recovery.py
    python scripts/rehearse_recovery.py --backup-dir /path/to/backup
    python scripts/rehearse_recovery.py --force-rebuild-index --json
"""

from __future__ import annotations

import argparse
import contextlib
import io
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

from db.connection import connect  # noqa: E402
from db.repository import CourseRepository  # noqa: E402
from rag.embedder import EMBEDDING_DIM, EmbedderProtocol, _l2_normalize  # noqa: E402
from rag.index import FaissIndex  # noqa: E402
from schemas.course import Course  # noqa: E402
from scripts.init_db import init_database  # noqa: E402
from scripts.rebuild_faiss import rebuild  # noqa: E402
from scripts.verify_index_manifest import verify_index  # noqa: E402


class _DeterministicEmbedder:
    """Stable, fast offline embedder for recovery rehearsals (no GPU or model download needed)."""

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray:
        vecs = []
        for t in texts:
            # Not hash(t): str hashing is salted per process, so the vectors (and the
            # reported top hit) changed from run to run.
            # 中文：不用 hash(t)：字符串哈希每个进程加盐不同，向量和报告里的 top hit 每次都会变。
            seed = int.from_bytes(hashlib.sha256(t.encode("utf-8")).digest()[:8], "big")
            rng = np.random.default_rng(seed)
            vecs.append(rng.standard_normal(EMBEDDING_DIM, dtype=np.float32))
        out = np.vstack(vecs).astype(np.float32)
        return _l2_normalize(out) if normalize else out


def create_fixture_backup(target_dir: Path, embedder: EmbedderProtocol | None = None) -> Path:
    """Create a self-contained, valid simulated backup in target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    db_path = target_dir / "courses.db"
    with contextlib.redirect_stdout(io.StringIO()):
        init_database(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    repo = CourseRepository(conn)

    sample_courses = [
        ("CS-5800", "CS 5800", "Algorithms", "Core course on algorithms, dynamic programming, graphs."),
        ("CS-5001", "CS 5001", "Intensive Foundations", "Introductory programming in Python, data structures."),
        ("CS-5002", "CS 5002", "Discrete Math", "Discrete structures, logic, sets, relations, combinatorics."),
        ("CS-5004", "CS 5004", "Object-Oriented Design", "Java OOP principles, design patterns, testing."),
        ("CS-5008", "CS 5008", "Data Structures with C", "Memory management in C, pointers, stacks and queues."),
    ]

    for cid, code, name, text in sample_courses:
        repo.insert(Course(course_id=cid, primary_code=code, primary_name=name), raw_text=text)
        repo.mark_indexed(cid)

    conn.commit()
    conn.close()

    faiss_dir = target_dir / "faiss_index"
    if embedder is None:
        embedder = _DeterministicEmbedder()

    with contextlib.redirect_stdout(io.StringIO()):
        rebuild(
            db_path=db_path,
            index_path=faiss_dir,
            embedder=embedder,
            model_name="BAAI/bge-m3",
            incremental=False,
        )
    return target_dir


def rehearse_recovery(
    *,
    backup_dir: Path | None = None,
    work_dir: Path | None = None,
    force_rebuild_index: bool = False,
    embedder: EmbedderProtocol | None = None,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Execute end-to-end recovery rehearsal in an isolated sandbox directory."""
    start_time = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "success": False,
        "mode": "custom_backup" if backup_dir else "simulated_fixture",
        "timestamp": start_time.isoformat(),
        "backup_source": str(backup_dir) if backup_dir else "generated_fixture",
        "recovery_dir": None,
        "sqlite_integrity": None,
        "sqlite_fk_check": None,
        "schema_version": None,
        "tables_count": 0,
        "courses_count": 0,
        "faiss_status": None,
        "faiss_count": 0,
        "faiss_checksums_match": False,
        "search_verification": False,
        "errors": [],
        "warnings": [],
        "duration_seconds": 0.0,
    }

    if embedder is None:
        embedder = _DeterministicEmbedder()

    # Create root temporary directory for isolation
    base_tmp = Path(tempfile.mkdtemp(prefix="neu_recovery_rehearsal_"))
    try:
        source_dir: Path
        if backup_dir is not None:
            source_dir = Path(backup_dir)
            if not source_dir.exists() or not source_dir.is_dir():
                report["errors"].append(f"Backup source directory does not exist: {source_dir}")
                return report
        else:
            source_dir = base_tmp / "simulated_backup"
            create_fixture_backup(source_dir, embedder=embedder)

        recovery_target = base_tmp / "recovered_data"
        recovery_target.mkdir(parents=True, exist_ok=True)
        report["recovery_dir"] = str(recovery_target)

        # 1. Restore SQLite database
        src_db = source_dir / "courses.db"
        if not src_db.exists():
            report["errors"].append(f"Missing SQLite database file in backup: {src_db}")
            return report

        dst_db = recovery_target / "courses.db"
        shutil.copy2(src_db, dst_db)

        # 2. SQLite Integrity and Foreign Key Checks
        conn = connect(dst_db)
        try:
            # PRAGMA integrity_check
            int_res = conn.execute("PRAGMA integrity_check").fetchall()
            int_ok = len(int_res) == 1 and int_res[0][0].lower() == "ok"
            report["sqlite_integrity"] = "ok" if int_ok else str(int_res)
            if not int_ok:
                report["errors"].append(f"SQLite integrity check failed: {int_res}")
                return report

            # PRAGMA foreign_key_check
            fk_res = conn.execute("PRAGMA foreign_key_check").fetchall()
            report["sqlite_fk_check"] = "ok" if len(fk_res) == 0 else f"violations: {len(fk_res)}"
            if len(fk_res) > 0:
                report["errors"].append(f"Foreign key violations detected: {len(fk_res)}")
                return report

            # Table count and Schema Version
            tbl_count = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            report["tables_count"] = tbl_count

            ver_row = conn.execute("SELECT version FROM schema_versions ORDER BY applied_at DESC LIMIT 1").fetchone()
            report["schema_version"] = ver_row[0] if ver_row else "unknown"

            # Course count
            course_count = conn.execute("SELECT count(*) FROM courses WHERE status = 'indexed'").fetchone()[0]
            report["courses_count"] = course_count
        finally:
            conn.close()

        # 3. FAISS Index Restoration or Rebuild
        dst_faiss = recovery_target / "faiss_index"
        src_faiss = source_dir / "faiss_index"

        should_rebuild = force_rebuild_index or (not src_faiss.exists())
        if not should_rebuild:
            shutil.copytree(src_faiss, dst_faiss)
            verify_rep = verify_index(dst_faiss, verify_load=True)
            if not verify_rep["valid"]:
                report["warnings"].append(
                    f"Backup FAISS index invalid ({verify_rep.get('errors')}), falling back to rebuild from SQLite"
                )
                should_rebuild = True
            else:
                report["faiss_status"] = "restored_from_backup"
                report["faiss_count"] = verify_rep.get("loaded_count", 0)
                report["faiss_checksums_match"] = verify_rep.get("checksums_match", False)

        if should_rebuild:
            if dst_faiss.exists():
                shutil.rmtree(dst_faiss, ignore_errors=True)
            with contextlib.redirect_stdout(io.StringIO()):
                counts = rebuild(
                    db_path=dst_db,
                    index_path=dst_faiss,
                    embedder=embedder,
                    model_name="BAAI/bge-m3",
                    incremental=False,
                )
            verify_rep = verify_index(dst_faiss, verify_load=True)
            if not verify_rep["valid"]:
                report["errors"].append(f"Rebuilt FAISS index failed verification: {verify_rep.get('errors')}")
                return report
            report["faiss_status"] = "rebuilt_from_sqlite"
            report["faiss_count"] = counts["embedded"]
            report["faiss_checksums_match"] = verify_rep.get("checksums_match", False)

        # 4. End-to-End Query Verification
        # Load index strictly with checksum verification
        loaded_index = FaissIndex.load(dst_faiss, verify_checksums=True)
        assert loaded_index.count == report["courses_count"]

        # Run sample search vector
        if loaded_index.count > 0:
            query_vec = embedder.encode(["Algorithms and data structures"], normalize=True)
            search_hits = loaded_index.search(query_vec, k=1)
            if not search_hits or len(search_hits) == 0:
                report["errors"].append("FAISS vector search returned empty result")
                return report

            top_cid, score = search_hits[0]
            # Verify course exists in restored SQLite
            read_conn = connect(dst_db)
            try:
                row = read_conn.execute("SELECT primary_code, primary_name FROM courses WHERE course_id = ?", [top_cid]).fetchone()
                if row is None:
                    report["errors"].append(f"Top hit course {top_cid} not found in restored SQLite")
                    return report
                report["search_verification"] = True
                report["top_search_hit"] = {
                    "course_id": top_cid,
                    "code": row["primary_code"],
                    "name": row["primary_name"],
                    "score": round(score, 4),
                }
            finally:
                read_conn.close()
        else:
            report["search_verification"] = True

        report["success"] = True

    except Exception as exc:
        report["errors"].append(f"Unexpected exception during recovery rehearsal: {exc}")
        return report

    finally:
        report["duration_seconds"] = round((datetime.now(timezone.utc) - start_time).total_seconds(), 3)
        if cleanup:
            shutil.rmtree(base_tmp, ignore_errors=True)

    return report


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", default=None, help="Path to existing backup snapshot directory")
    parser.add_argument("--force-rebuild-index", action="store_true", help="Force rebuild FAISS index from SQLite")
    parser.add_argument("--no-cleanup", action="store_true", help="Do not delete temporary recovery directory")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    report = rehearse_recovery(
        backup_dir=Path(args.backup_dir) if args.backup_dir else None,
        force_rebuild_index=args.force_rebuild_index,
        cleanup=not args.no_cleanup,
    )

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["success"] else 1

    print(f"=> Disaster Recovery Rehearsal Report ({report['mode']})")
    print(f"   Timestamp          : {report['timestamp']}")
    print(f"   Duration           : {report['duration_seconds']}s")
    if report["success"]:
        print("   Overall Status     : SUCCESS [PASSED]")
        print(f"   SQLite Integrity   : {report['sqlite_integrity']}")
        print(f"   Foreign Keys Check : {report['sqlite_fk_check']}")
        print(f"   Schema Version     : {report['schema_version']}")
        print(f"   Tables Count       : {report['tables_count']}")
        print(f"   Indexed Courses    : {report['courses_count']}")
        print(f"   FAISS Status       : {report['faiss_status']} (count={report['faiss_count']})")
        print(f"   Manifest Checksums : {'MATCHED' if report['faiss_checksums_match'] else 'MISMATCH'}")
        print(f"   Search Check       : {'PASSED' if report['search_verification'] else 'FAILED'}")
        if "top_search_hit" in report:
            hit = report["top_search_hit"]
            print(f"   Sample Hit         : {hit['code']} - {hit['name']} (score={hit['score']})")
        return 0
    else:
        print("   Overall Status     : FAILED")
        for err in report["errors"]:
            print(f"   ERROR: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(cli())
