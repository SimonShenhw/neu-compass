"""Shared pytest fixtures.

Anything that touches the DB schema should depend on `empty_db` (in-memory,
init.sql applied, FK enforcement on) so tests stay fast and isolated.

API test helpers (FixtureEmbedder, seed_minimal_corpus, build_test_app,
api_client fixture) live here too so api/* modules are imported eagerly
at collection time — if a route's import breaks, the failure surfaces
loudly rather than as a lazy-import error inside one test.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INIT_SQL_PATH = PROJECT_ROOT / "db" / "init.sql"


@pytest.fixture
def empty_db() -> Iterator[sqlite3.Connection]:
    # check_same_thread=False so the FastAPI TestClient (which runs the ASGI
    # app in a worker thread via anyio) can reuse this fixture's connection
    # via the get_db_conn dependency override. Tests are sequential so we
    # don't hit the "concurrent write corruption" risk that flag enables.
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(INIT_SQL_PATH.read_text(encoding="utf-8"))
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# API test helpers
# ---------------------------------------------------------------------------


class FixtureEmbedder:
    """Stand-in for BGEM3Embedder. Maps every text to the SAME unit vector,
    so FAISS sees N identical vectors and returns them in insertion order
    (deterministic). This lets tests rely on BM25 to differentiate ranking,
    while the vector leg degenerates to a stable tie-break by insertion."""

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray:
        from rag.embedder import EMBEDDING_DIM, _l2_normalize  # noqa: PLC0415

        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        rng = np.random.default_rng(42)
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        out = np.tile(v, (len(texts), 1))
        return _l2_normalize(out) if normalize else out


class FixtureReranker:
    """Stand-in for CrossEncoderReranker — word-overlap on lowercased token sets,
    deterministic and zero-cost. Adversarial queries with no overlap to any
    candidate get max sigmoid 0, so the §3.4 rejection gate (threshold 0.4)
    correctly returns matched_via='rejected' in tests.

    Quacks like CrossEncoderReranker for `rerank_blend_with_rejection`'s
    purposes — only `.score(query, candidates)` is called from the route.
    """

    def score(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        q_tokens = set(query.lower().split())
        if not q_tokens:
            return [0.0 for _ in candidates]
        return [
            len(q_tokens & set(c.lower().split())) / len(q_tokens)
            for c in candidates
        ]


def seed_minimal_corpus(conn: sqlite3.Connection) -> None:
    """3 indexed courses + 1 slang alias. Enough to drive search/course tests.

    Course raw_text is chosen so BM25 can reliably differentiate:
      - "graph algorithms BFS DFS" → CS 5800
      - "neural network backprop" → DS 5220
      - "AI fundamentals search" → AAI 6600
    """
    from db.alias_repository import AliasRepository  # noqa: PLC0415
    from db.repository import CourseRepository  # noqa: PLC0415
    from schemas.alias import Alias, AliasReviewStatus, AliasSource, AliasType  # noqa: PLC0415
    from schemas.course import Course, DeliveryMode  # noqa: PLC0415

    courses = [
        (
            Course(
                course_id="c-aai-6600",
                primary_code="AAI 6600",
                primary_name="Applied AI",
                term="Spring 2026",
                credits=3,
                delivery_mode=DeliveryMode.HYBRID,
            ),
            "AI fundamentals search reasoning planning",
        ),
        (
            Course(
                course_id="c-cs-5800",
                primary_code="CS 5800",
                primary_name="Algorithms",
                term="Spring 2026",
                credits=4,
                delivery_mode=DeliveryMode.IN_PERSON,
            ),
            "graph algorithms BFS DFS shortest paths NP completeness",
        ),
        (
            Course(
                course_id="c-ds-5220",
                primary_code="DS 5220",
                primary_name="Supervised ML",
                term="Fall 2025",
                credits=4,
                delivery_mode=DeliveryMode.IN_PERSON,
            ),
            "neural network training backpropagation gradient descent",
        ),
    ]
    course_repo = CourseRepository(conn)
    for c, raw in courses:
        course_repo.insert(c, raw_text=raw)
        course_repo.mark_indexed(c.course_id)

    AliasRepository(conn).add(
        Alias(
            alias_text="Algo",
            alias_type=AliasType.SLANG,
            primary_course_id="c-cs-5800",
            confidence=1.0,
            source=AliasSource.MANUAL,
            review_status=AliasReviewStatus.APPROVED,
        )
    )


def build_test_app(conn: sqlite3.Connection, *, seed: bool = True):
    """Build an API app with state populated for tests (no real model load).

    Lifespan is skipped via create_app(run_startup=False); we set
    app.state.{embedder, faiss_index, bm25_corpus} ourselves and override
    get_db_conn to use the test connection rather than opening the real
    SQLite path from settings.
    """
    from api.dependencies import get_db_conn  # noqa: PLC0415
    from api.main import create_app  # noqa: PLC0415
    from db.repository import CourseRepository  # noqa: PLC0415
    from rag.hybrid import BM25Corpus  # noqa: PLC0415
    from rag.index import FaissIndex  # noqa: PLC0415

    if seed:
        seed_minimal_corpus(conn)

    app = create_app(run_startup=False)

    embedder = FixtureEmbedder()
    index = FaissIndex()
    course_repo = CourseRepository(conn)
    indexed = course_repo.list_by_status("indexed")
    if indexed:
        vecs = embedder.encode([f"raw_{c.course_id}" for c in indexed], normalize=True)
        index.add(vecs, [c.course_id for c in indexed])

    bm25 = BM25Corpus.from_db(conn)

    app.state.embedder = embedder
    app.state.faiss_index = index
    app.state.bm25_corpus = bm25
    app.state.reranker = FixtureReranker()
    app.state.ready = True

    app.dependency_overrides[get_db_conn] = lambda: conn

    return app


@pytest.fixture
def api_client(empty_db: sqlite3.Connection):
    """TestClient over a seeded in-memory app. Yields after lifespan is
    skipped; closes itself when the test exits."""
    from fastapi.testclient import TestClient  # noqa: PLC0415

    app = build_test_app(empty_db, seed=True)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def api_client_unseeded(empty_db: sqlite3.Connection):
    """For tests that want to control seeding manually (e.g. visibility tier)."""
    from fastapi.testclient import TestClient  # noqa: PLC0415

    app = build_test_app(empty_db, seed=False)
    with TestClient(app) as client:
        yield client
