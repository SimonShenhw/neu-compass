"""Calibrate the ADR-0018 rejection gate against the production stack.

What it does:
  1. Builds the SAME inference stack the API runs (via
     api.main._build_inference_stack — honors INFERENCE_BACKEND /
     OPENVINO_* / RERANK_POOL_SIZE env, so on the NAS this measures the
     int8+GPU production configuration).
  2. Synthesizes a labeled calibration set:
       - answerable: queries built from the catalog itself (course names +
         informative raw_text tokens) — guaranteed in-corpus
       - unanswerable: 40 hand-written queries across 8 UAEval4RAG-style
         categories (fake codes / other schools / campus admin / gibberish /
         chitchat / homework admin / off-domain / impossible asks)
     eval/test_set.json is NOT touched — it stays a held-out eval set.
  3. Runs each query through alias → hybrid(k=rerank_pool_size) → reranker,
     collecting the gate features (max_sigmoid, bm25_top, vec_top,
     code_pattern_miss).
  4. Fits a logistic regression (pure numpy, deterministic) on
     [logit(max_sigmoid), log1p(bm25_top), vec_top, code_miss] and reports
     AUC vs the max-sigmoid-only baseline + a threshold trade-off grid.
  5. Prints the coefficient dict to paste into
     rag/rejection.py::DEFAULT_COEFFICIENTS and writes the full run report
     to --out (default /data/rejection_calibration.json when on the NAS).

Run on the NAS (inside the production image, GPU passthrough):
  docker run --rm -v /volume1/docker/neu-compass/runtime-data:/data \
    --device /dev/dri --group-add 44 --group-add 105 \
    --env-file /volume1/docker/neu-compass/.env \
    -e SQLITE_PATH=/data/courses.db -e FAISS_INDEX_PATH=/data/faiss_index \
    -e INFERENCE_BACKEND=openvino -e OPENVINO_MODEL_DIR=/data/openvino_int8 \
    -e OPENVINO_DEVICE=GPU -e OPENVINO_CACHE_DIR=/data/openvino_cache \
    -e RERANK_POOL_SIZE=10 \
    neu-compass:latest python scripts/calibrate_rejection.py
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 8 categories × 5. Hand-written, deterministic, reviewable. None of these
# overlap eval/test_set.json's adversarial queries (q039-q042 stay held out).
UNANSWERABLE_QUERIES: list[tuple[str, str]] = [
    # fake course codes (alias tier misses, gate must catch)
    ("fake_code", "CS 9999"),
    ("fake_code", "AAI 0000"),
    ("fake_code", "CSYE 12345"),
    ("fake_code", "DS 0001 advanced topics"),
    ("fake_code", "INFO 9876 capstone"),
    # other universities' famous courses
    ("other_school", "MIT 6.824 distributed systems"),
    ("other_school", "Stanford CS231n convolutional networks"),
    ("other_school", "CMU 15-445 database systems"),
    ("other_school", "Berkeley CS162 operating systems"),
    ("other_school", "Harvard CS50 introduction"),
    # campus admin, not courses
    ("campus_admin", "how much is a parking permit at northeastern"),
    ("campus_admin", "OPT visa application timeline"),
    ("campus_admin", "dorm laundry machine hours"),
    ("campus_admin", "tuition payment deadline fall semester"),
    ("campus_admin", "where to replace a lost husky card"),
    # gibberish
    ("gibberish", "asdf jkl qwerty uiop"),
    ("gibberish", "zzzz xxxx yyyy wwww"),
    ("gibberish", "blorptang frumious vorpal snicker"),
    ("gibberish", "qpwoeiruty alskdjfhg zmxncbv"),
    ("gibberish", "mxyzptlk gzornenplat fhqwhgads"),
    # chitchat
    ("chitchat", "how are you doing today"),
    ("chitchat", "tell me a joke about cats"),
    ("chitchat", "what's the weather in boston tomorrow"),
    ("chitchat", "who won the world cup"),
    ("chitchat", "what time is it right now"),
    # homework / grading admin
    ("homework_admin", "homework 3 solutions please"),
    ("homework_admin", "when is assignment 2 due"),
    ("homework_admin", "grading rubric for project 1"),
    ("homework_admin", "final exam answer key"),
    ("homework_admin", "extension request for my lab report"),
    # off-domain entirely
    ("off_domain", "best ramen recipe with pork belly"),
    ("off_domain", "NVDA stock price today"),
    ("off_domain", "how to renew a passport quickly"),
    ("off_domain", "iphone battery replacement cost"),
    ("off_domain", "cheap flights to new york this weekend"),
    # impossible / out-of-scope asks
    ("impossible", "course taught by Albert Einstein"),
    ("impossible", "class that guarantees a job at google"),
    ("impossible", "free course with no tuition and no prerequisites ever"),
    ("impossible", "undergraduate kindergarten math"),
    ("impossible", "PhD defense scheduling for chemistry"),
    # Chinese unanswerable — the ASCII-only BM25 leg yields bm25_top=0 for
    # these, same as for answerable Chinese queries; the cjk_dominant
    # feature + these samples teach the gate to separate the two regimes
    # on vec/sigmoid evidence instead of missing lexical evidence.
    ("zh_campus_admin", "停车证多少钱一个学期"),
    ("zh_campus_admin", "学费什么时候交截止日期"),
    ("zh_campus_admin", "宿舍洗衣机几点开门"),
    ("zh_chitchat", "今天天气怎么样啊"),
    ("zh_chitchat", "给我讲个笑话吧"),
    ("zh_off_domain", "波士顿哪家火锅最好吃"),
    ("zh_off_domain", "怎么续签护照最快"),
    ("zh_homework", "第三次作业的答案给我看看"),
    ("zh_fake_code", "CS 八千八百八十八 这门课"),
    ("zh_impossible", "保证毕业就进谷歌的课程"),
]


def _informative_tokens(raw_text: str, *, n: int = 3) -> list[str]:
    """Pick n mid-document informative tokens (len>4, non-stopword) —
    approximates the 'theory jargon' answerable class that the sigmoid
    threshold false-rejects."""
    from rag.hybrid import STOPWORDS, tokenize  # noqa: PLC0415

    toks = [t for t in tokenize(raw_text) if len(t) > 4 and t not in STOPWORDS]
    if not toks:
        return []
    # Skip the first few (usually title words the embedder already nails);
    # stride through the middle for variety. Deterministic.
    body = toks[3:] or toks
    stride = max(1, len(body) // n)
    return [body[min(i * stride, len(body) - 1)] for i in range(n)]


def build_answerable_zh_queries(conn, *, limit: int = 15) -> list[tuple[str, str]]:
    """Gemini-generated Chinese answerable queries from sampled courses.
    Best-effort: any LLM failure just yields fewer samples (the script
    prints the final count; aim for ≥10 so w_cjk has signal)."""
    from llm.gemini_client import GeminiError, generate_text  # noqa: PLC0415

    rows = conn.execute(
        "SELECT primary_name, raw_text FROM courses "
        "WHERE status='indexed' AND length(COALESCE(raw_text,'')) > 200 "
        "ORDER BY course_id"
    ).fetchall()
    stride = max(1, len(rows) // limit)
    out: list[tuple[str, str]] = []
    for r in rows[::stride][:limit]:
        prompt = (
            "你在模拟一个中国研究生用中文搜索大学选课系统。根据下面的课程"
            "描述,写一条自然的中文搜索 query(8-20 个字,可夹杂英文术语,"
            "不要出现课程编号和完整课程名)。只输出 query 本身。\n\n"
            f"课程名: {r['primary_name']}\n描述: {r['raw_text'][:500]}"
        )
        try:
            q = generate_text(prompt, temperature=0.8, max_output_tokens=2048)
        except GeminiError as e:
            print(f"   ! zh-query LLM failed: {e}")
            continue
        line = q.strip().splitlines()[0].strip().strip('"').strip()
        if 4 <= len(line) <= 60:
            out.append(("zh_answerable", line))
    return out


def build_hard_answerable_queries(conn, bm25, *, limit: int = 15) -> list[tuple[str, str]]:
    """Rare-jargon answerable queries — the q013/q018 evidence profile the
    easy synthesized set lacks (low cross-encoder sigmoid, mid vector
    cosine, HIGH lexical evidence). Without these the LR collapses onto a
    vector-dominant solution and regresses exactly the queries BM25 was
    rescuing. Tokens are picked by max IDF from each course's own raw_text
    (answerable by construction)."""
    from rag.hybrid import tokenize  # noqa: PLC0415

    idf = getattr(getattr(bm25, "_bm25", None), "idf", {}) or {}
    rows = conn.execute(
        "SELECT primary_name, raw_text FROM courses "
        "WHERE status='indexed' AND length(COALESCE(raw_text,'')) > 150 "
        "ORDER BY course_id"
    ).fetchall()
    stride = max(1, len(rows) // limit)
    out: list[tuple[str, str]] = []
    for r in rows[::stride][:limit]:
        toks = [t for t in set(tokenize(r["raw_text"])) if len(t) > 3]
        if len(toks) < 3:
            continue
        rare = sorted(toks, key=lambda t: -idf.get(t, 0.0))[:3]
        out.append(("jargon_style", " ".join(rare)))
    return out


def build_answerable_queries(conn, *, limit: int = 50) -> list[tuple[str, str]]:
    """Two query styles per sampled course: course-name and topic-token.
    Deterministic sample: ORDER BY course_id with a fixed stride."""
    rows = conn.execute(
        "SELECT course_id, primary_name, COALESCE(raw_text,'') AS raw_text "
        "FROM courses WHERE status='indexed' AND length(COALESCE(raw_text,'')) > 80 "
        "ORDER BY course_id"
    ).fetchall()
    if not rows:
        return []
    stride = max(1, len(rows) // (limit // 2))
    sampled = [rows[i] for i in range(0, len(rows), stride)][: limit // 2]

    out: list[tuple[str, str]] = []
    for r in sampled:
        out.append(("name_style", r["primary_name"]))
        toks = _informative_tokens(r["raw_text"])
        if toks:
            out.append(("topic_style", " ".join(toks)))
    return out[:limit]


def collect_features(args) -> list[dict]:
    """Run every calibration query through the production retrieval path
    and record the gate features."""
    import structlog  # noqa: PLC0415

    from api.main import _build_inference_stack  # noqa: PLC0415
    from config import settings  # noqa: PLC0415
    from db.alias_repository import AliasRepository  # noqa: PLC0415
    from db.connection import connect  # noqa: PLC0415
    from db.repository import CourseRepository  # noqa: PLC0415
    from rag.hybrid import BM25Corpus, HybridRetriever  # noqa: PLC0415
    from rag.index import FaissIndex  # noqa: PLC0415
    from rag.query_normalizer import normalize_query_to_course_ids  # noqa: PLC0415
    from rag.rejection import (  # noqa: PLC0415
        query_has_code_pattern,
        query_is_cjk_dominant,
    )
    from rag.retriever import Retriever  # noqa: PLC0415

    log = structlog.get_logger("calibrate_rejection")
    pool = settings.rerank_pool_size
    print(f"=> backend={settings.inference_backend} pool={pool}")

    embedder, reranker = _build_inference_stack(log)
    if reranker is None:
        print("ERROR: reranker disabled — gate calibration is meaningless")
        sys.exit(1)

    index = FaissIndex.load(settings.faiss_index_path)
    conn = connect(settings.sqlite_path)
    try:
        alias_repo = AliasRepository(conn)
        course_repo = CourseRepository(conn)
        bm25 = BM25Corpus.from_db(conn)
        vector = Retriever(
            embedder=embedder, index=index,
            course_repo=course_repo, sqlite_conn=conn,
        )
        hybrid = HybridRetriever(
            vector_retriever=vector, bm25_corpus=bm25, course_repo=course_repo,
        )

        zh_answerable = build_answerable_zh_queries(conn, limit=15)
        print(f"=> zh answerable generated: {len(zh_answerable)}")
        hard_answerable = build_hard_answerable_queries(conn, bm25, limit=15)
        print(f"=> hard (jargon) answerable: {len(hard_answerable)}")
        queries = [
            {"label": 1, "category": cat, "query": q}
            for cat, q in (
                build_answerable_queries(conn, limit=args.n_answerable)
                + hard_answerable
                + zh_answerable
            )
        ] + [
            {"label": 0, "category": cat, "query": q}
            for cat, q in UNANSWERABLE_QUERIES
        ]

        rows: list[dict] = []
        for i, item in enumerate(queries):
            q = item["query"]
            # Mirror production tiering: alias hits never reach the gate.
            if normalize_query_to_course_ids(q, alias_repo=alias_repo):
                rows.append({**item, "path": "alias", "skipped": True})
                continue
            hits = hybrid.search(q, k=pool)
            if not hits:
                rows.append({**item, "path": "empty", "skipped": True})
                continue
            texts = []
            for h in hits:
                r = conn.execute(
                    "SELECT raw_text FROM courses WHERE course_id = ?",
                    (h.course.course_id,),
                ).fetchone()
                texts.append(
                    (r["raw_text"] if r else None) or h.course.primary_name
                )
            sigmoids = reranker.score(q, texts)
            diag = hybrid.last_diagnostics or {}
            rows.append({
                **item,
                "path": "gate",
                "skipped": False,
                "max_sigmoid": float(max(sigmoids)),
                "bm25_top": float(diag.get("bm25_top", 0.0)),
                "vec_top": float(diag.get("vec_top", 0.0)),
                "code_miss": bool(query_has_code_pattern(q)),
                "cjk": bool(query_is_cjk_dominant(q)),
            })
            if (i + 1) % 10 == 0:
                print(f"   {i + 1}/{len(queries)} queries scored")
        return rows
    finally:
        conn.close()


# === numpy logistic regression (no sklearn dependency in the image) ===


def _design(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    eps = 1e-6
    feats, labels = [], []
    for r in rows:
        s = min(max(r["max_sigmoid"], eps), 1 - eps)
        cjk = 1.0 if r.get("cjk") else 0.0
        feats.append([
            math.log(s / (1 - s)),
            # Interaction: lexical evidence only counts when the ASCII
            # tokenizer actually saw the query (mirrors gate.probability).
            math.log1p(max(r["bm25_top"], 0.0)) * (1.0 - cjk),
            r["vec_top"],
            1.0 if r["code_miss"] else 0.0,
            cjk,
        ])
        labels.append(r["label"])
    return np.asarray(feats, dtype=np.float64), np.asarray(labels, dtype=np.float64)


def fit_logreg(
    x: np.ndarray, y: np.ndarray, *, l2: float = 1e-2, iters: int = 8000,
    lr: float = 0.05,
) -> tuple[np.ndarray, float]:
    """Full-batch GD on standardized features; returns raw-space (w, b)."""
    mu, sd = x.mean(axis=0), x.std(axis=0)
    sd = np.where(sd < 1e-9, 1.0, sd)
    xs = (x - mu) / sd
    n, d = xs.shape
    w = np.zeros(d)
    b = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(xs @ w + b)))
        grad_w = xs.T @ (p - y) / n + l2 * w
        grad_b = float(np.mean(p - y))
        w -= lr * grad_w
        b -= lr * grad_b
    # Fold standardization back into raw-space coefficients.
    w_raw = w / sd
    b_raw = b - float((w * mu / sd).sum())
    return w_raw, b_raw


def auc(scores: np.ndarray, y: np.ndarray) -> float:
    """Rank-based AUC (Mann-Whitney)."""
    order = np.argsort(scores)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(scores) + 1)
    pos = y == 1
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="/data/rejection_calibration.json")
    ap.add_argument("--n-answerable", type=int, default=50)
    args = ap.parse_args()

    rows = collect_features(args)
    fit_rows = [r for r in rows if not r["skipped"]]
    skipped = [r for r in rows if r["skipped"]]
    print(f"=> {len(fit_rows)} gate-path rows ({len(skipped)} skipped: "
          f"{[r['path'] for r in skipped][:6]}...)")

    x, y = _design(fit_rows)
    w, b = fit_logreg(x, y)

    p_full = 1.0 / (1.0 + np.exp(-(x @ w + b)))
    auc_full = auc(p_full, y)
    auc_sigmoid_only = auc(x[:, 0], y)

    coefficients = {
        "bias": round(float(b), 4),
        "w_logit_sigmoid": round(float(w[0]), 4),
        "w_log1p_bm25": round(float(w[1]), 4),
        "w_vec_top": round(float(w[2]), 4),
        "w_code_miss": round(float(w[3]), 4),
        "w_cjk": round(float(w[4]), 4),
    }

    grid = []
    for t in (0.3, 0.4, 0.5, 0.6, 0.7):
        rej = p_full < t
        false_rej = int(((y == 1) & rej).sum())
        caught = int(((y == 0) & rej).sum())
        grid.append({
            "threshold": t,
            "false_reject_answerable": f"{false_rej}/{int((y == 1).sum())}",
            "caught_unanswerable": f"{caught}/{int((y == 0).sum())}",
        })

    report = {
        "n_fit": len(fit_rows),
        "auc_max_sigmoid_only": round(auc_sigmoid_only, 4),
        "auc_full_gate": round(auc_full, 4),
        "coefficients": coefficients,
        "threshold_grid": grid,
        "rows": rows,
    }
    Path(args.out).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    print(f"\n=== calibration result (n={len(fit_rows)}) ===")
    print(f"  AUC max-sigmoid only : {auc_sigmoid_only:.4f}")
    print(f"  AUC full gate        : {auc_full:.4f}")
    print(f"  coefficients → paste into rag/rejection.py DEFAULT_COEFFICIENTS:")
    print(json.dumps(coefficients, indent=4))
    print("  threshold grid:")
    for g in grid:
        print(f"    p<{g['threshold']}: false-rej {g['false_reject_answerable']}, "
              f"caught {g['caught_unanswerable']}")
    print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
