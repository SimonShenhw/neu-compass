"""Tests for scripts/rebuild_faiss — uses fake embedder, no model download."""

from __future__ import annotations

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
            seed = abs(hash(t)) % (2**32)
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
