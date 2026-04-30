"""RAG retrieval pipeline.

Layered architecture (PLAN §1.2):
  1. Query normalization (alias-aware) — query_normalizer.py
  2. SQLite hard filter on metadata (term/credits/delivery_mode) — retriever.py
  3. FAISS vector search restricted to candidate ids — index.py + retriever.py
  4. SQLite rehydration of full Course JSON — retriever.py

Embedder is pluggable: BGEM3Embedder for production, FakeEmbedder for tests.
ADR-0013 invariant: retriever only returns courses with status='indexed'.
"""

from rag.embedder import BGEM3Embedder, EmbedderProtocol, EMBEDDING_DIM
from rag.index import FaissIndex
from rag.query_normalizer import normalize_query_to_course_ids
from rag.retriever import Retriever, SearchHit

__all__ = [
    "EMBEDDING_DIM",
    "BGEM3Embedder",
    "EmbedderProtocol",
    "FaissIndex",
    "Retriever",
    "SearchHit",
    "normalize_query_to_course_ids",
]
