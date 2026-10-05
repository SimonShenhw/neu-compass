"""Tests for scripts/rebuild_faiss — uses fake embedder, no model download."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from db.repository import CourseRepository
from rag.embedder import EMBEDDING_DIM, _l2_normalize
from rag.index import FaissIndex
from schemas.course import Course
from scripts.init_db import init_database
from scripts.rebuild_faiss import rebuild


class _DeterministicEmbedder:
    """Hashes each text to a stable vector. No model load."""

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray:
        vecs = []
        for t in texts:
            # hash(t) is salted per process; sha256 keeps the vectors stable across runs.
            seed = int.from_bytes(hashlib.sha256(t.encode("utf-8")).digest()[:8], "big")
            rng = np.random.default_rng(seed)
            vecs.append(rng.standard_normal(EMBEDDING_DIM, dtype=np.float32))
        out = np.vstack(vecs).astype(np.float32)
        return _l2_normalize(out) if normalize else out


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """Create a tmp DB with 3 courses: 2 indexed (with raw_text), 1 pending."""
    db_path = tmp_path / "rebuild_test.db"
    init_database(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    repo = CourseRepository(conn)

    repo.insert(
        Course(course_id="c-1", primary_code="CS 5800", primary_name="Algos"),
        raw_text="syllabus body about algorithms",
    )
    repo.mark_indexed("c-1")

    repo.insert(
        Course(course_id="c-2", primary_code="AAI 6600", primary_name="Applied AI"),
        raw_text="syllabus body about applied AI",
    )
    repo.mark_indexed("c-2")

    # Pending row WITH text — should be excluded from default rebuild
    repo.insert(
        Course(course_id="c-pending", primary_code="DS 5220", primary_name="ML"),
        raw_text="pending row body",
    )
    # status defaults to 'pending'

    conn.commit()
    conn.close()
    return db_path


# === default rebuild (status='indexed') ===

def test_rebuild_indexed_only(seeded_db: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "faiss_idx"
    counts = rebuild(
        db_path=seeded_db, index_path=out_dir,
        embedder=_DeterministicEmbedder(),
        status_filter="indexed",
    )
    assert counts == {"embedded": 2, "skipped_no_text": 0}

    loaded = FaissIndex.load(out_dir)
    assert loaded.count == 2
    assert "c-1" in loaded
    assert "c-2" in loaded
    assert "c-pending" not in loaded


def test_rebuild_includes_pending_when_no_filter(
    seeded_db: Path, tmp_path: Path,
) -> None:
    """status_filter=None embeds everything with raw_text."""
    out_dir = tmp_path / "faiss_idx"
    counts = rebuild(
        db_path=seeded_db, index_path=out_dir,
        embedder=_DeterministicEmbedder(),
        status_filter=None,
    )
    assert counts["embedded"] == 3

    loaded = FaissIndex.load(out_dir)
    assert "c-pending" in loaded


def test_rebuild_skips_rows_with_null_raw_text(
    tmp_path: Path,
) -> None:
    """Rows with raw_text NULL must not crash the embedder; just skip."""
    db_path = tmp_path / "test.db"
    init_database(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    repo = CourseRepository(conn)

    repo.insert(Course(course_id="c-1", primary_code="CS 5800",
                       primary_name="Algos"))  # no raw_text
    repo.mark_indexed("c-1")
    repo.insert(
        Course(course_id="c-2", primary_code="AAI 6600", primary_name="x"),
        raw_text="actual content",
    )
    repo.mark_indexed("c-2")
    conn.commit()
    conn.close()

    out_dir = tmp_path / "faiss_idx"
    counts = rebuild(
        db_path=db_path, index_path=out_dir,
        embedder=_DeterministicEmbedder(),
    )
    assert counts == {"embedded": 1, "skipped_no_text": 1}


def test_rebuild_empty_db(tmp_path: Path) -> None:
    """Empty courses table -> rebuild produces an empty index, no error."""
    db_path = tmp_path / "empty.db"
    init_database(db_path)

    out_dir = tmp_path / "faiss_idx"
    counts = rebuild(
        db_path=db_path, index_path=out_dir,
        embedder=_DeterministicEmbedder(),
    )
    assert counts == {"embedded": 0, "skipped_no_text": 0}

    loaded = FaissIndex.load(out_dir)
    assert loaded.count == 0


def test_rebuild_overwrites_existing_index(
    seeded_db: Path, tmp_path: Path,
) -> None:
    """Calling rebuild() twice should produce a fresh index, not append."""
    out_dir = tmp_path / "faiss_idx"
    rebuild(
        db_path=seeded_db, index_path=out_dir,
        embedder=_DeterministicEmbedder(),
    )
    counts = rebuild(
        db_path=seeded_db, index_path=out_dir,
        embedder=_DeterministicEmbedder(),
    )
    # Second run produces same count, not 4
    assert counts["embedded"] == 2

    loaded = FaissIndex.load(out_dir)
    assert loaded.count == 2

# === 08B Manifest & Incremental Rebuild Tests ===

def test_rebuild_writes_manifest(seeded_db: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "faiss_idx"
    rebuild(
        db_path=seeded_db,
        index_path=out_dir,
        embedder=_DeterministicEmbedder(),
        model_name="custom/test-model",
    )
    manifest_path = out_dir / FaissIndex.MANIFEST_FILE
    assert manifest_path.exists()

    loaded = FaissIndex.load(out_dir, expected_model="custom/test-model", verify_checksums=True)
    assert loaded.count == 2
    assert loaded.manifest is not None
    assert loaded.manifest["embedding_model"] == "custom/test-model"


def test_rebuild_incremental_fallback_when_no_existing_index(seeded_db: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "faiss_idx"
    counts = rebuild(
        db_path=seeded_db,
        index_path=out_dir,
        embedder=_DeterministicEmbedder(),
        incremental=True,
    )
    assert counts["embedded"] == 2
    assert counts["fallback_full"] is True

    loaded = FaissIndex.load(out_dir)
    assert loaded.count == 2
    assert "c-1" in loaded and "c-2" in loaded


def test_rebuild_incremental_add_and_remove(seeded_db: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "faiss_idx"
    # 1. Initial build (2 courses: c-1, c-2)
    rebuild(
        db_path=seeded_db,
        index_path=out_dir,
        embedder=_DeterministicEmbedder(),
    )

    # 2. Add course c-3 to SQLite
    conn = sqlite3.connect(str(seeded_db))
    conn.row_factory = sqlite3.Row
    repo = CourseRepository(conn)
    repo.insert(
        Course(course_id="c-3", primary_code="CS 7000", primary_name="Advanced"),
        raw_text="syllabus body for c-3",
    )
    repo.mark_indexed("c-3")
    conn.commit()
    conn.close()

    # Incremental update: should only embed c-3
    counts = rebuild(
        db_path=seeded_db,
        index_path=out_dir,
        embedder=_DeterministicEmbedder(),
        incremental=True,
    )
    assert counts["embedded"] == 1
    assert counts["removed"] == 0
    assert counts["retained"] == 2
    assert counts["fallback_full"] is False

    loaded = FaissIndex.load(out_dir, verify_checksums=True)
    assert loaded.count == 3
    assert "c-1" in loaded and "c-2" in loaded and "c-3" in loaded

    # 3. Change c-1 status to pending (should be removed from index)
    conn = sqlite3.connect(str(seeded_db))
    conn.execute("UPDATE courses SET status = 'pending' WHERE course_id = 'c-1'")
    conn.commit()
    conn.close()

    counts = rebuild(
        db_path=seeded_db,
        index_path=out_dir,
        embedder=_DeterministicEmbedder(),
        incremental=True,
    )
    assert counts["embedded"] == 0
    assert counts["removed"] == 1
    assert counts["retained"] == 2
    assert counts["fallback_full"] is False

    loaded = FaissIndex.load(out_dir, verify_checksums=True)
    assert loaded.count == 2
    assert "c-1" not in loaded
    assert "c-2" in loaded and "c-3" in loaded


def test_rebuild_incremental_corrupted_index_fallback(seeded_db: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "faiss_idx"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / FaissIndex.INDEX_FILE).write_bytes(b"corrupted binary data")

    counts = rebuild(
        db_path=seeded_db,
        index_path=out_dir,
        embedder=_DeterministicEmbedder(),
        incremental=True,
    )
    assert counts["fallback_full"] is True
    assert counts["fallback_reason"] == "unreadable_or_corrupt_index"
    assert counts["embedded"] == 2

    loaded = FaissIndex.load(out_dir, verify_checksums=True)
    assert loaded.count == 2


# === Review 2026-10-03: staleness + model safety of --incremental ===


def _set_raw_text(db: Path, course_id: str, text: str) -> None:
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE courses SET raw_text=? WHERE course_id=?", (text, course_id))
    conn.commit()
    conn.close()


def test_incremental_reembeds_courses_whose_raw_text_changed(seeded_db: Path, tmp_path: Path) -> None:
    """A catalog re-scrape keeps ids but rewrites descriptions. The old
    incremental mode kept every such vector (retained=2, embedded=0)."""
    out_dir = tmp_path / "faiss_idx"
    embedder = _DeterministicEmbedder()
    rebuild(db_path=seeded_db, index_path=out_dir, embedder=embedder)
    _set_raw_text(seeded_db, "c-1", "COMPLETELY NEW description")

    counts = rebuild(db_path=seeded_db, index_path=out_dir, embedder=embedder, incremental=True)
    assert counts["fallback_full"] is False
    assert counts["reembedded_changed"] == 1
    assert counts["embedded"] == 1
    assert counts["retained"] == 1 and counts["removed"] == 0

    loaded = FaissIndex.load(out_dir, verify_checksums=True)
    fresh = embedder.encode(["COMPLETELY NEW description"])[0]
    top_id, top_score = loaded.search(fresh, k=1)[0]
    assert top_id == "c-1" and top_score == pytest.approx(1.0, abs=1e-5)


def test_incremental_unchanged_text_embeds_nothing(seeded_db: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "faiss_idx"
    rebuild(db_path=seeded_db, index_path=out_dir, embedder=_DeterministicEmbedder())
    counts = rebuild(db_path=seeded_db, index_path=out_dir, embedder=_DeterministicEmbedder(), incremental=True)
    assert counts["embedded"] == 0 and counts["retained"] == 2 and counts["fallback_full"] is False


def test_incremental_model_change_rebuilds_everything(seeded_db: Path, tmp_path: Path) -> None:
    """Never mix two models' vectors under one manifest label."""
    out_dir = tmp_path / "faiss_idx"
    rebuild(db_path=seeded_db, index_path=out_dir, embedder=_DeterministicEmbedder(), model_name="model-A")
    counts = rebuild(db_path=seeded_db, index_path=out_dir, embedder=_DeterministicEmbedder(),
                     model_name="model-B", incremental=True)
    assert counts["fallback_full"] is True and counts["fallback_reason"] == "model_changed"
    assert counts["embedded"] == 2
    assert FaissIndex.load(out_dir, expected_model="model-B", verify_checksums=True).count == 2


def test_incremental_legacy_index_without_fingerprints_rebuilds(seeded_db: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "faiss_idx"
    legacy = FaissIndex()
    emb = _DeterministicEmbedder()
    legacy.add(emb.encode(["syllabus body about algorithms", "syllabus body about applied AI"]), ["c-1", "c-2"])
    legacy.save(out_dir)  # manifest yes, fingerprints no (pre-fingerprint build)
    counts = rebuild(db_path=seeded_db, index_path=out_dir, embedder=emb, incremental=True)
    assert counts["fallback_full"] is True and counts["fallback_reason"] == "missing_fingerprints"
    loaded = FaissIndex.load(out_dir)
    assert loaded.fingerprint("c-1") is not None and loaded.fingerprint("c-2") is not None


def test_incremental_without_manifest_rebuilds(seeded_db: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "faiss_idx"
    rebuild(db_path=seeded_db, index_path=out_dir, embedder=_DeterministicEmbedder())
    (out_dir / FaissIndex.MANIFEST_FILE).unlink()
    counts = rebuild(db_path=seeded_db, index_path=out_dir, embedder=_DeterministicEmbedder(), incremental=True)
    assert counts["fallback_full"] is True and counts["fallback_reason"] == "no_manifest_unknown_model"


def test_incremental_torn_index_set_rebuilds(seeded_db: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "faiss_idx"
    rebuild(db_path=seeded_db, index_path=out_dir, embedder=_DeterministicEmbedder())
    other = FaissIndex()
    other.add(_DeterministicEmbedder().encode(["x", "y"]), ["c-2", "c-1"])
    other.save(tmp_path / "other")
    (out_dir / FaissIndex.INDEX_FILE).write_bytes((tmp_path / "other" / FaissIndex.INDEX_FILE).read_bytes())
    counts = rebuild(db_path=seeded_db, index_path=out_dir, embedder=_DeterministicEmbedder(), incremental=True)
    assert counts["fallback_full"] is True and counts["fallback_reason"] == "unreadable_or_corrupt_index"
    assert FaissIndex.load(out_dir, verify_checksums=True).count == 2

