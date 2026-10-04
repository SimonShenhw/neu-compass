"""Profile the fixed synthetic kernel only; no real DB/model/HTTP inputs.

Compare identical fixtures with tracing off/on. CPU/FAISS/BM25 arithmetic is
real, embeddings and reranker scores are deterministic test doubles. These
numbers are not production latency, model quality or a release approval.
"""

from pathlib import Path
import json
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_fixture(*, trace=False):
    import numpy as np
    from db.alias_repository import AliasRepository
    from db.repository import CourseRepository
    from eval.profile_eval import profile_eval
    from rag.hybrid import BM25Corpus, HybridRetriever
    from rag.index import FaissIndex
    from rag.profiling import stage
    from rag.query_normalizer import normalize_query_to_course_ids
    from rag.reranker import rerank_blend_with_rejection
    from rag.retriever import Retriever
    from schemas.course import Course

    rows = (
        ('fixture-graph', 'CS 9001', 'Synthetic Graph', 'synthetic graph algorithms paths'),
        ('fixture-sql', 'CS 9002', 'Synthetic SQL', 'synthetic database sql storage'),
        ('fixture-neural', 'DS 9003', 'Synthetic Neural', 'synthetic neural learning'),
    )
    queries = {'queries': [
        dict(query_id='alias', query='CS 9001', expected_course_ids=['fixture-graph']),
        dict(query_id='semantic', query='graph algorithms', expected_course_ids=['fixture-graph']),
        dict(query_id='multi', query='synthetic', expected_course_ids=[row[0] for row in rows]),
        dict(query_id='filtered', query='filtered neural', expected_course_ids=['fixture-neural']),
        dict(query_id='negative', query='unknownzz', expected_course_ids=[]),
    ]}

    class Embedder:
        def encode(self, texts):
            out = []
            for text in texts:
                words = set(text.lower().split())
                vector = np.array([bool(words & group) for group in
                    ({'graph', 'algorithms'}, {'database', 'sql'}, {'neural', 'learning'})], dtype=np.float32)
                if not vector.any():
                    vector = np.ones(3, dtype=np.float32)
                out.append(vector / np.linalg.norm(vector))
            return np.array(out)

    class Reranker:
        def score(self, query, texts):
            words = set(query.lower().split())
            return [len(words & set(text.lower().split())) / len(words) for text in texts]

    conn = sqlite3.connect(':memory:')
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript((ROOT / 'db/init.sql').read_text(encoding='utf-8-sig'))
        repo = CourseRepository(conn)
        for cid, code, name, text in rows:
            repo.insert(Course(course_id=cid, primary_code=code, primary_name=name, credits=4), raw_text=text)
            repo.mark_indexed(cid)
        conn.commit()
        index = FaissIndex(dim=3)
        index.add(np.eye(3, dtype=np.float32), [row[0] for row in rows])
        vector = Retriever(embedder=Embedder(), index=index, course_repo=repo, sqlite_conn=conn)
        hybrid = HybridRetriever(vector_retriever=vector, bm25_corpus=BM25Corpus.from_db(conn), course_repo=repo)
        aliases = AliasRepository(conn)
        before = conn.total_changes

        def search(query):
            resolved = normalize_query_to_course_ids(query, alias_repo=aliases)
            if resolved:
                return resolved
            filtered = query == 'filtered neural'
            query = 'neural learning' if filtered else query
            hits = hybrid.search(query, k=5, hard_filters={'primary_code_prefix': 'DS'} if filtered else None)
            with stage('candidate_texts'):
                texts = {row['course_id']: row['raw_text'] for row in conn.execute(
                    'SELECT course_id,raw_text FROM courses WHERE course_id IN (' + ','.join('?' for _ in hits) + ')',
                    [hit.course.course_id for hit in hits])} if hits else {}
            ranked, _ = rerank_blend_with_rejection(query, hits, Reranker(), fetch_text=texts.get,
                blend_alpha=.4, reject_threshold=.05, top_k=5)
            return [hit.course.course_id for hit in ranked]

        report = profile_eval(queries, search, warmup=1, iterations=3, trace=trace)
        if conn.total_changes != before:
            raise ValueError('fixture_query_wrote_data')
        report.update(synthetic_only=True, production_performance_verified=False, release_approved=False,
                      query_dml_changes=0, real_model_calls=0, traffic_scope='no_http_no_query_log')
        return report
    finally:
        conn.close()


def cli(argv=None):
    from scripts.release_preflight import SafeParser
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--trace', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = run_fixture(trace=args.trace)
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 0
    except Exception:
        print(json.dumps(dict(machine_status='failed', release_approved=False, code='offline_profile_failed')))
        return 1


if __name__ == '__main__':
    raise SystemExit(cli())
