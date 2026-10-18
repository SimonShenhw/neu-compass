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
TOPICS = ({"graph", "graphs", "algorithms", "paths", "traversal"}, {"database", "databases", "sql", "storage", "durability"},
          {"neural", "learning", "backprop", "backpropagation"}, {"planning", "reasoning", "search"},
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
    ("CS", 9011, "Graph Proofs", "graph proofs connectivity trees", 4, "Fall 2026"),
    ("CS", 9012, "Query Engines", "database query optimization sql", 4, "Fall 2026"),
    ("DS", 9013, "Neural Optimization", "neural gradients optimization", 4, "Fall 2026"),
    ("AAI", 9014, "Decision Search", "planning heuristic reasoning", 3, "Fall 2026"),
    ("CS", 9015, "Packet Transport", "network packet transport protocols", 3, "Fall 2026"),
    ("CS", 9016, "Applied Encryption", "security encryption cryptography", 4, "Fall 2026"),
    ("DS", 9017, "Probability Models", "statistics probability estimators", 3, "Fall 2026"),
    ("AAI", 9018, "Motion Models", "robotics motion sensors", 4, "Fall 2026"),
    ("DS", 9019, "Image Geometry", "vision image geometry recognition", 4, "Fall 2026"),
    ("CS", 9020, "Graph Systems", "graph distributed algorithms", 4, "Fall 2026"),
    ("CS", 9021, "Transaction Systems", "database transactions storage", 4, "Fall 2026"),
    ("DS", 9022, "Neural Architectures", "neural architecture learning", 4, "Fall 2026"),
    ("AAI", 9023, "Search Systems", "planning search reasoning", 3, "Fall 2026"),
    ("CS", 9024, "Routing Systems", "network routing protocols", 3, "Fall 2026"),
    ("CS", 9025, "Secure Systems", "security authentication crypto", 4, "Fall 2026"),
    ("DS", 9026, "Inference Systems", "statistics inference probability", 3, "Fall 2026"),
    ("AAI", 9027, "Control Systems", "robotics control motion", 4, "Fall 2026"),
    ("DS", 9028, "Visual Systems", "vision images classification", 4, "Fall 2026"),
)
SETTING_NAMES = ("rejection_mode", "hyde_rescue", "acronym_expansion", "fusion_mode", "fusion_weight", "rerank_pool_size",
                 "enable_reranker", "rescue_min_probability")
# The repository's production compose file documents the deployed values of some of these; the profile measured here
# is the code defaults, and every difference is reported. 中文：仓库的生产 compose 写了部署值；这里测的是代码默认值，
# 差异逐项写进报告。
COMPOSE_ENV = {name: name.upper() for name in SETTING_NAMES}
SYNTHETIC_GLOSSARY = {"GPH": ("graph algorithms",)}


def _yaml_block(lines, path):
    """The stripped lines nested under a key path of a block-style YAML file (indentation only: no flow style, anchors
    or multi-line values). Keys may be quoted, and the last block may be a list at its key's own indentation.
    中文：按缩进取出块格式 YAML 里某个键路径下的各行；键可以带引号，最后一层可以是和键同缩进的列表。"""
    parent, child, depth, found = -1, None, 0, []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        level = len(line) - len(line.lstrip())
        if level < parent or (level == parent and not (depth == len(path) and stripped.startswith("-"))):
            break
        if child is None:
            child = level
        if depth == len(path):
            found.append(stripped)
        elif level == child and re.fullmatch(rf"([\"']?){re.escape(path[depth])}\1:\s*(?:#.*)?", stripped):
            parent, child, depth = level, None, depth + 1
    return found if depth == len(path) else []


def _unquote(text):
    text = re.split(r"\s+#", text, maxsplit=1)[0].strip()
    return text[1:-1] if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"" else text


def _interpolate(text):
    """`${VAR:-default}` / `${VAR-default}` is its default; an empty default, `$VAR` and any other `${...}` leave the
    value to the host environment (None); `$$` is a literal dollar sign."""
    if (match := re.fullmatch(r"\$\{\w+:?-([^}]*)\}", text)) and match[1]:
        return match[1]
    return None if re.search(r"(?<!\$)\$(?:\{|[A-Za-z_])", text.replace("$$", "")) else text.replace("$$", "$")


def documented_deployment():
    """Deployed values as written for the api service in docker-compose.yml (text only; never the NAS, never .env).

    Reads `services.api.environment` in map form (`KEY: value`) or list form (`- KEY=value`, also at the key's own
    indentation); quotes, comments and a byte-order mark are stripped. A name the api service does not set, or leaves
    to the host environment (`KEY:`, `KEY: null`, `KEY: ~`, `- KEY`, `$VAR`), is None; `- KEY=` is an empty string.
    中文：只读 compose 文本里 api 服务的 environment（映射或列表写法），去掉引号、注释和 BOM；没写、或留给宿主环境的
    （映射写法的空值、null、~、$VAR）是 None；列表写法的 `- KEY=` 是空字符串。
    """
    lines = (ROOT / "docker-compose.yml").read_text(encoding="utf-8-sig").splitlines()
    written = {}
    for item in _yaml_block(lines, ("services", "api", "environment")):
        key, sep, value = _unquote(item[1:]).partition("=") if item.startswith("-") else item.partition(":")
        raw = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        listed = item.startswith("-")  # "- KEY=" sets an empty string; "KEY:" leaves the value to the host
        empty = not sep or (not raw and not listed) or (not listed and raw in ("null", "Null", "NULL", "~"))
        written[_unquote(key.strip())] = None if empty else _interpolate(_unquote(raw))
    return {name: written.get(env) for name, env in COMPOSE_ENV.items()}


# How pydantic reads a boolean setting from the environment. 中文：pydantic 从环境变量读布尔值的方式。
_BOOL_TEXT = {"1": True, "true": True, "yes": True, "on": True, "t": True, "y": True,
              "0": False, "false": False, "no": False, "off": False, "f": False, "n": False}


def _same_value(default, written):
    if written is None:
        return True
    if isinstance(default, bool):
        return _BOOL_TEXT.get(written.strip().lower()) is default
    if isinstance(default, (int, float)):
        try:
            return float(written) == float(default)
        except ValueError:
            return False
    return written == str(default)


def topic_vector(text):
    import numpy as np
    from rag.hybrid import tokenize

    tokens = set(tokenize(text))
    vector = np.array([bool(tokens & topic) for topic in TOPICS], dtype=np.float32)
    return vector / np.linalg.norm(vector) if vector.any() else vector


class TopicEmbedder:
    def __init__(self, mode="normal"):
        self.mode = mode

    def encode(self, texts, *, normalize=True):
        import numpy as np

        vectors = []
        for text in texts:
            from rag.hybrid import tokenize
            tokens = set(tokenize(text))
            vector = np.array([bool(tokens & topic) for topic in TOPICS], dtype=np.float32)
            if not vector.any():
                vector[:] = 1
            vector = vector / np.linalg.norm(vector) if normalize else vector
            if self.mode == "constant":
                vector = np.ones(len(TOPICS), dtype=np.float32) / len(TOPICS) ** 0.5
            elif self.mode == "anti_topic":
                vector = -vector
            vectors.append(vector)
        return np.array(vectors, dtype=np.float32).reshape((-1, len(TOPICS)))


class SemanticReranker:
    def score(self, query, texts):
        tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        vector = topic_vector(query)
        return [0.5 * len(tokens & set(re.findall(r"[a-z0-9]+", text.lower()))) / max(1, len(tokens))
                + 0.5 * float(vector @ topic_vector(text)) for text in texts]


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

    def __init__(self, *, vector_mode="normal"):
        if vector_mode not in {"normal", "constant", "anti_topic", "disabled"}:
            raise ValueError("unknown synthetic vector mode")
        self.vector_mode = vector_mode
        self._entered = False

    def __enter__(self):
        if self._entered:
            raise RuntimeError("cannot reenter a synthetic world; nesting is forbidden")
        if Path(".env").exists():
            raise ValueError("run the offline world from a directory without .env")
        deployed = documented_deployment()
        from config import settings as configured

        self.stack = ExitStack()
        try:
            from eval.route_guard import OfflineGuard
            # Also guard the configured real database and index paths, wherever SQLITE_PATH / FAISS_INDEX_PATH point.
            # 中文：同时保护配置里真实库和索引的路径，不管环境变量指到哪里。
            self.guard = self.stack.enter_context(OfflineGuard(
                ROOT / "data", protected=(Path(configured.sqlite_path), Path(configured.faiss_index_path))))
            import api.dependencies as dependencies
            import api.routes.chat as chat
            import api.routes.common as common
            import db.connection as connection
            import llm.gemini_client as gemini
            import rag.acronyms as acronyms
            import rag.hybrid as hybrid_module
            import rag.hyde as hyde
            import faiss
            from api.main import create_app
            from config import settings
            from db.repository import CourseRepository
            from rag.hybrid import BM25Corpus
            from rag.index import FaissIndex
            from rag.embedder import BGEM3Embedder
            from rag.reranker import CrossEncoderReranker
            from rag.onnx_backend import OnnxEmbedder, OnnxReranker
            from rag.openvino_backend import OvEmbedder, OvReranker

            fields = type(settings).model_fields
            for name in SETTING_NAMES:
                self.stack.enter_context(patch.object(settings, name, fields[name].default))
            self.stack.enter_context(patch.object(settings, "answer_feedback_enabled", False))
            self.settings = settings
            for name, value in (("RERANK_POOL_SIZE", settings.rerank_pool_size), ("BLEND_ALPHA", common.BLEND_ALPHA),
                                ("RERANKER_REJECT_THRESHOLD", common.RERANKER_REJECT_THRESHOLD)):
                self.stack.enter_context(patch.object(chat, name, value))
            # value = what the route actually uses (read back after patching); code_default = read independently.
            # 中文：value 是路由实际用的值（打补丁后回读）；code_default 另外独立读取，两者不一致就是隐藏的钉值。
            effective = {name: getattr(settings, name) for name in SETTING_NAMES}
            effective["rerank_pool_size"] = chat.RERANK_POOL_SIZE
            self.config = {name: {"value": effective[name], "source": "code_default", "code_default": fields[name].default,
                                  "documented_deployment": deployed[name],
                                  "differs_from_documented_deployment": not _same_value(fields[name].default, deployed[name])}
                           for name in SETTING_NAMES}
            for key, attr in (("blend_alpha", "BLEND_ALPHA"), ("reject_threshold", "RERANKER_REJECT_THRESHOLD")):
                self.config[key] = {"value": getattr(chat, attr), "source": "code_default",
                                    "code_default": getattr(common, attr), "documented_deployment": None,
                                    "differs_from_documented_deployment": False}
            self.config.update({
                "profile": "code_defaults", "deployment_verified": False, "documented_deployment_source": "docker-compose.yml",
                "documented_deployment_differs": sorted(name for name in SETTING_NAMES
                                                        if self.config[name]["differs_from_documented_deployment"]),
                "answer_feedback_enabled": {"value": False, "source": "harness_pin",
                                            "code_default": fields["answer_feedback_enabled"].default},
                "glossary": {"value": SYNTHETIC_GLOSSARY, "source": "harness_pin", "code_default": "external data, not read"}})
            for module in (dependencies, connection):
                self.stack.enter_context(patch.object(module, "connect", side_effect=lambda *a, **k: self.guard.deny("database_attempts")))
            for module, name in ((dependencies, "generate_text_stream"), (gemini, "generate_text_stream"), (hyde, "rescue_expand")):
                self.stack.enter_context(patch.object(module, name, side_effect=lambda *a, **k: self.guard.deny("model_attempts")))
            # Cached imports do not visit MetaPathFinder; block the project's loaders and inference seams too.
            # 中文：已缓存的模型模块不再触发导入钩子；直接封住项目加载／推理入口。
            for target, names in ((BGEM3Embedder, ("_load", "encode")), (CrossEncoderReranker, ("_load", "score")),
                                  (OnnxEmbedder, ("from_path", "encode")), (OnnxReranker, ("from_path", "score")),
                                  (OvEmbedder, ("from_path", "encode")), (OvReranker, ("from_path", "score"))):
                for name in names:
                    self.stack.enter_context(patch.object(target, name, side_effect=lambda *a, **k: self.guard.deny("model_attempts")))
            for name in ("read_index", "read_index_binary", "FileIOReader", "FileIOWriter", "write_index", "write_index_binary"):
                self.stack.enter_context(patch.object(faiss, name, side_effect=lambda *a, **k: self.guard.deny("file_attempts")))
            self.stack.enter_context(patch.object(acronyms, "load_glossary", lambda path=None: SYNTHETIC_GLOSSARY))
            self.retrieval_traces = []
            original_fusion = hybrid_module.reciprocal_rank_fusion

            def capture_fusion(rankings, **kwargs):
                self.retrieval_traces.append({"vector_ids": list(rankings[0]), "bm25_ids": list(rankings[1]) if len(rankings) > 1 else []})
                return original_fusion(rankings, **kwargs)

            self.stack.enter_context(patch.object(hybrid_module, "reciprocal_rank_fusion", capture_fusion))
            # The world's own connection and every other one opened while it is active go through guarded_connect: no
            # ATTACH, and a connection opened any other way is refused (eval/route_guard.py).
            # 中文：世界自己的连接和存续期间新开的连接都走 guarded_connect：不能 ATTACH；用别的方式新开连接会被拒绝。
            from eval.route_guard import guarded_connect

            self.stack.enter_context(patch.object(sqlite3, "connect", guarded_connect(sqlite3.connect)))
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
            if self.vector_mode == "disabled":
                index = FaissIndex(dim=len(TOPICS))
            self.app.state.embedder, self.app.state.faiss_index = TopicEmbedder(self.vector_mode), index
            self.app.state.bm25_corpus = BM25Corpus.from_db(self.conn)
            self.app.state.reranker, self.app.state.ready = SemanticReranker(), True
            self.app.dependency_overrides[dependencies.get_db_conn] = lambda: self.conn
            self.app.dependency_overrides[dependencies.get_chat_stream_fn] = lambda: self.stream
            self.app.dependency_overrides[dependencies.get_hyde_rescue_fn] = lambda: self.rescue if self.script.get("rescue") else None
            self.prompts, self.script = [], {}
            self.rescue_calls = 0
            self.world_sha256 = hashlib.sha256(self.snapshot().encode()).hexdigest()
            if len(CourseRepository(self.conn).list_by_status("indexed")) != len(ROWS):
                raise RuntimeError("synthetic seed count mismatch")
            self._entered = True
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *exc):
        try:
            return self.stack.__exit__(*exc)
        finally:
            self._entered = False

    @property
    def real_model_calls(self):
        return self.guard.counters["model_attempts"]

    @property
    def real_api_calls(self):
        return self.guard.counters["network_attempts"]

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
