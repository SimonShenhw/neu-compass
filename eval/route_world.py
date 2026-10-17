"""A bounded synthetic /chat world: real routing/FAISS/BM25, scripted models, memory-only DB.

All records are invented fixtures, not official course/program facts. Call serially in a
directory without .env; patches and the connection are owned by this context manager.
中文：真实路由与检索算法＋主题向量／词重叠替身。只用内存合成数据，不代表官方课程或生产质量。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXED = datetime(2026, 10, 1, tzinfo=timezone.utc)
TOPICS = ({"graph", "graphs", "algorithms", "paths"}, {"database", "databases", "sql", "storage"},
          {"neural", "learning", "backprop"}, {"planning", "reasoning", "search"},
          {"network", "networks", "protocols"}, {"security", "crypto", "cryptography"},
          {"statistics", "probability", "inference"}, {"robotics", "control", "motion"},
          {"vision", "image", "images"})
ROWS = (
    ("CS", 9001, "Graph Algorithms", "graph algorithms BFS DFS shortest paths", 4, "Spring 2026"),
    ("CS", 9002, "Database Storage", "database sql storage transactions", 4, "Fall 2026"),
    ("DS", 9003, "Neural Learning", "neural learning backprop gradient", 4, "Fall 2026"),
    ("AAI", 9004, "Planning", "planning reasoning heuristic search", 3, "Spring 2026"),
    ("CS", 9005, "Networks", "network protocols routing packets", 3, "Fall 2026"),
    ("CS", 9006, "Security", "security crypto cryptography encryption", 4, "Spring 2026"),
    ("DS", 9007, "Statistics", "graph statistics probability inference", 3, "Fall 2026"),
    ("AAI", 9008, "Robotics", "robotics control motion sensors", 4, "Fall 2026"),
    ("CS", 9009, "Advanced Graphs", "graph algorithms advanced complexity", 4, "Fall 2026"),
    ("DS", 9010, "Vision", "vision image images recognition", 4, "Spring 2026"),
)
OFFLINE_CONFIG = {"rejection_mode": "threshold", "hyde_rescue": False, "acronym_expansion": False,
                  "fusion_mode": "rrf", "fusion_weight": 0.5, "rerank_pool_size": 4,
                  "enable_reranker": True, "answer_feedback_enabled": False}


class TopicEmbedder:
    def encode(self, texts, *, normalize=True):
        import numpy as np

        vectors = []
        for text in texts:
            tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
            vector = np.array([bool(tokens & topic) for topic in TOPICS], dtype=np.float32)
            if not vector.any():
                vector[:] = 1
            vectors.append(vector / np.linalg.norm(vector) if normalize else vector)
        return np.array(vectors, dtype=np.float32).reshape((-1, len(TOPICS)))


class OverlapReranker:
    def score(self, query, texts):
        tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        return [len(tokens & set(re.findall(r"[a-z0-9]+", text.lower()))) / max(1, len(tokens)) for text in texts]


def _seed(conn):
    from db.alias_repository import AliasRepository
    from db.catalog_source_repository import CatalogSourceRepository
    from db.course_requisite_repository import CourseRequisiteRepository
    from db.program_plan_repository import ProgramPlanRepository
    from db.program_repository import ProgramRepository
    from db.repository import CourseRepository
    from schemas.alias import Alias
    from schemas.course import Course
    from schemas.course_requisite_document import CourseRequisiteDocument
    from schemas.course_requisite_source import CourseRequisiteSource
    from schemas.program import Program, ProgramRequiredCourse
    from schemas.program_plan import ProgramPlan
    from scrapers.course_requisites import parse_clause
    from scrapers.neu_catalog import CatalogEntry

    repo = CourseRepository(conn)
    for subject, number, name, text, credits, term in ROWS:
        snippets, soft = [], {}
        if number in (9001, 9002, 9006):
            soft["workload_hours_per_week"] = 12.0
            quote = {9001: "About 12 hours a week", 9002: "Heavy weekly homework", 9006: "About 6 hours a week"}[number]
            snippets.append({"field": "workload_hours_per_week", "value": 12.0, "source_id": f"syllabus_synthetic_{number}",
                             "quote": quote, "confidence": 0.8})
        if number in (9001, 9002, 9003):
            soft["difficulty_score"] = 4.0
            snippets.append({"field": "difficulty_score", "value": 4.0, "source_id": f"syllabus_synthetic_{number}",
                             "quote": "Very hard exercises", "confidence": 0.8})
        course = Course(course_id=f"neu-{subject.lower()}-{number}", primary_code=f"{subject} {number}",
                        primary_name=f"Synthetic {name}", credits=credits, term=term, delivery_mode="in_person",
                        created_at=FIXED, updated_at=FIXED, evidence_snippets=snippets,
                        source_review_ids=[f"syllabus_synthetic_{number}"] if snippets else [], **soft)
        repo.insert(course, raw_text=text)
        repo.mark_indexed(course.course_id)
        if number != 9002:  # A missing snapshot makes multi-course context parity non-trivial.
            entry = CatalogEntry(course_code=course.primary_code, course_name=course.primary_name,
                                 description=f"Synthetic fixture: {text}", credits=4 if number == 9005 else credits,
                                 catalog_url=f"https://catalog.northeastern.edu/course-descriptions/{subject.lower()}/")
            snapshot = CatalogSourceRepository.snapshot(entry).model_copy(update={"imported_at": FIXED, "retrieved_at": FIXED})
            CatalogSourceRepository(conn).store(course.course_id, snapshot)
    AliasRepository(conn).add(Alias(alias_text="Graphy", alias_type="slang", primary_course_id="neu-cs-9001",
                                   source="manual", created_at=FIXED))
    source = CourseRequisiteSource(url="https://catalog.northeastern.edu/course-descriptions/cs/",
                                   catalog_year="2026-2027", captured_at=FIXED, sha256="a" * 64, byte_count=10,
                                   page_title="Synthetic Computer Science (CS)")
    CourseRequisiteRepository(conn).store(CourseRequisiteDocument(
        course_id="neu-cs-9001", course_code="CS 9001", course_name="Synthetic Graph Algorithms",
        catalog_year="2026-2027", source=source, imported_at=FIXED,
        requisites={"prerequisite": parse_clause("CS 9002"), "corequisite": parse_clause(None)}))
    programs = ProgramRepository(conn)
    for identifier, subject in (("synthetic-cs-standard", "CS"), ("synthetic-cs-align", "CS"), ("synthetic-ds", "DS")):
        programs.add_program(Program(program_id=identifier, full_name=f"Synthetic {identifier}", prefix=subject))
    for cid in ("neu-cs-9001", "neu-cs-9002"):
        programs.add_required_course(ProgramRequiredCourse(program_id="synthetic-cs-standard", course_id=cid,
                                                           requirement_type="core", semester_recommended=1))
    ProgramPlanRepository(conn).store(ProgramPlan(
        plan_id="synthetic-cs-align-2026", program_id="synthetic-cs-align", campus="boston", catalog_year="2026-2027",
        pathway="align", source_url="https://catalog.northeastern.edu/graduate/synthetic/offline-plan/",
        source_title="Synthetic fixture, not an official plan", source_catalog_year="2026-2027",
        source_excerpt="Synthetic requirement for offline route testing only", captured_on=FIXED.date(),
        notes="Invented test data; not verified official requirements or a semester schedule",
        requirements={"kind": "course", "label": "Synthetic graph requirement", "course_code": "CS 9001"}))
    # Freeze SQL-maintained timestamps too, so the seeded rows have a reproducible identity.
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for (table,) in tables:
        columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        fixed_columns = sorted(columns & {"created_at", "updated_at", "indexed_at", "applied_at", "imported_at"})
        if fixed_columns:
            # Set updated_at in the SAME statement: a later created_at-only update would fire
            # courses_touch_updated_at and put the wall clock back into the seed.
            assignments = ",".join(f'"{column}"=CASE WHEN "{column}" IS NULL THEN NULL ELSE ? END' for column in fixed_columns)
            conn.execute(f'UPDATE "{table}" SET {assignments}', [FIXED.isoformat()] * len(fixed_columns))
    conn.commit()


class SyntheticWorld:
    """Serial, context-owned stand-ins; dependency fallback is fail closed.
    中文：串行使用；依赖接缝遗漏时拒绝连接真实库。"""

    def __enter__(self):
        if Path(".env").exists():
            raise ValueError("run the offline world from a directory without .env")
        self.stack = ExitStack()
        try:
            import api.dependencies as dependencies
            import api.routes.chat as chat
            from api.main import create_app
            from config import settings
            from db.repository import CourseRepository
            from rag.hybrid import BM25Corpus
            from rag.index import FaissIndex

            for name, value in OFFLINE_CONFIG.items():
                self.stack.enter_context(patch.object(settings, name, value))
            self.settings = settings
            for name, value in (("RERANK_POOL_SIZE", 4), ("BLEND_ALPHA", 0.4), ("RERANKER_REJECT_THRESHOLD", 0.05)):
                self.stack.enter_context(patch.object(chat, name, value))
            self.stack.enter_context(patch.object(dependencies, "connect", side_effect=RuntimeError("real DB forbidden")))
            self.conn = sqlite3.connect(":memory:", check_same_thread=False)
            self.stack.callback(self.conn.close)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript((ROOT / "db/init.sql").read_text(encoding="utf-8"))
            _seed(self.conn)
            self.app = create_app(run_startup=False)
            embedder, index = TopicEmbedder(), FaissIndex(dim=len(TOPICS))
            rows = self.conn.execute("SELECT course_id,raw_text FROM courses ORDER BY course_id").fetchall()
            index.add(embedder.encode([row[1] for row in rows]), [row[0] for row in rows])
            self.app.state.embedder, self.app.state.faiss_index = embedder, index
            self.app.state.bm25_corpus = BM25Corpus.from_db(self.conn)
            self.app.state.reranker, self.app.state.ready = OverlapReranker(), True
            self.app.dependency_overrides[dependencies.get_db_conn] = lambda: self.conn
            self.app.dependency_overrides[dependencies.get_chat_stream_fn] = lambda: self.stream
            self.app.dependency_overrides[dependencies.get_hyde_rescue_fn] = lambda: self.rescue if self.script.get("rescue") else None
            self.prompts, self.script = [], {}
            self.real_model_calls = self.real_api_calls = 0
            self.rescue_calls = 0
            self.world_sha256 = hashlib.sha256(self.snapshot().encode()).hexdigest()
            assert len(CourseRepository(self.conn).list_by_status("indexed")) == len(ROWS)
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)

    def snapshot(self):
        tables = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                   "AND name NOT LIKE 'sqlite_%' AND name != 'query_log' ORDER BY name").fetchall()
        records = {name: sorted((list(row) for row in self.conn.execute(f'SELECT * FROM "{name}"')),
                                key=lambda row: json.dumps(row, default=str, sort_keys=True)) for (name,) in tables}
        return json.dumps(records, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False)

    def set_stream(self, script):
        self.script = script
        self.settings.hyde_rescue = bool(script.get("rescue"))

    def stream(self, prompt):
        from llm.gemini_client import GeminiError

        self.prompts.append(prompt)
        yield from self.script.get("chunks", [])
        error = self.script.get("error")
        if error == "non_text":
            yield {"not": "text"}
        elif error:
            raise GeminiError("synthetic scripted failure", kind="empty_stream" if error == "empty_stream" else "timeout")

    def rescue(self, query):
        from llm.gemini_client import GeminiError

        self.rescue_calls += 1
        if self.script["rescue"] == "error":
            raise GeminiError("synthetic rescue failure", kind="timeout")
        return self.script["rescue"]
