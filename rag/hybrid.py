"""BM25 + vector hybrid retrieval via Reciprocal Rank Fusion (RRF).

Why hybrid: Week 4 smoke test (docs/rag_smoke_results.md §6) showed
adversarial query "quantum cryptography" got vector score 0.485,
HIGHER than legitimate match "graph algorithms" at 0.463. Absolute
score thresholds don't work — bge-m3 compresses STEM-text similarities
into a narrow 0.4-0.7 band.

为什么用混合检索:第 4 周冒烟测试(docs/rag_smoke_results.md §6)显示,
对抗性查询 "quantum cryptography" 的向量得分 0.485,竟然高于正确匹配
"graph algorithms" 的 0.463。绝对分数阈值行不通 —— bge-m3 把 STEM
文本相似度压缩在 0.4-0.7 的狭窄区间里。

BM25 contributes lexical matching (exact term hits) which the vector
embedder under-weights. RRF combines the two rankings without needing
to normalize their score scales:

    rrf_score(item) = sum over rankings of  1 / (k + rank_in_ranking)

with default k=60 (standard RRF parameter from Cormack et al. 2009).
This makes top-1 in each list contribute the most, with diminishing
returns. Robust to scale differences.

BM25 提供词面精确匹配信号,正好补上向量嵌入器低估的部分。RRF 只用
名次融合两路排名,无需把分数归一到同一尺度:每路第 1 名贡献最大,
名次越靠后贡献衰减越快(k=60 为 Cormack et al. 2009 的标准参数),
因此对两路分数尺度差异天然鲁棒。

Tokenization: ASCII alnum tokens (whitespace + lowercase) with English
stopwords filtered, PLUS CJK character bigrams (ADR-0020). Stopword
filter widens the inversion gap reported in docs/rag_smoke_results.md §7
(vector-only inversion was -0.022; hybrid without stopwords was +0.001 —
borderline). Adversarial queries like "ancient roman history" otherwise
gain BM25 mass from "and"/"of" appearing in every course's raw_text.

分词策略:ASCII 字母数字 token(小写化)并过滤英文停用词,再加上
CJK 字符二元组(ADR-0020)。停用词过滤拉大了 docs/rag_smoke_results.md
§7 报告的"反转差距"(纯向量为 -0.022;不滤停用词的混合检索是 +0.001,
几乎贴边)。否则 "ancient roman history" 这类对抗查询会因 "and"/"of"
出现在每门课的 raw_text 里而白得 BM25 分数。

CJK bigrams (no jieba dependency — char bigrams are the standard
segmentation-free CJK indexing trick): Chinese queries previously got
ZERO lexical signal against the English corpus. With the doc-expansion
field adding 中文 keywords per course (scripts/generate_doc_expansion.py),
bigrams give both sides a shared vocabulary, opening the BM25 leg for
the bilingual half of the user base.

CJK 二元组(不依赖 jieba —— 字符 bigram 是免分词 CJK 索引的标准做法):
以前中文查询对英文语料拿到的词面信号是零。配合文档扩展字段为每门课
注入中文关键词(scripts/generate_doc_expansion.py),bigram 让查询和
文档两侧共享同一套词表,为双语用户群打开了 BM25 这条腿。
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Protocol

from rank_bm25 import BM25Okapi

from db.repository import CourseRepository
from rag.retriever import ELIGIBLE_STATUS, SearchHit

DEFAULT_RRF_K = 60

# ASCII alnum tokens (lowercased) + CJK runs handled separately as bigrams.
# 中文:ASCII 字母数字 token(已小写);CJK 连续段单独提取,后续切成字符 bigram。
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")

# English stopwords. Hardcoded (rather than nltk.download('stopwords')) so
# `tokenize` works offline / in CI / on first checkout. Sourced from NLTK's
# English list; words that could plausibly carry signal in a course-search
# context (e.g. "again" → repeat-able? "before"/"after" → pre/co-req hints)
# are kept conservatively. If you change this list, re-run
# scripts/smoke_hybrid_compare.py to confirm the real-min vs adv-max gap.
# 中文:英文停用词表。硬编码(而非 nltk.download('stopwords'))是为了让
# `tokenize` 在离线 / CI / 首次 checkout 时开箱即用。词表取自 NLTK 英文表;
# 在选课场景下可能带信息量的词(如 "again" → 可重修?"before"/"after" →
# 先修/并修暗示)被保守地保留。改动此表后必须重跑
# scripts/smoke_hybrid_compare.py,确认"真实查询最低分 vs 对抗查询最高分"的差距。
STOPWORDS: frozenset[str] = frozenset({
    "a", "about", "all", "also", "am", "an", "and", "any", "are", "as",
    "at", "be", "been", "being", "both", "but", "by", "can", "could",
    "did", "do", "does", "doing", "down", "during", "each", "few", "for",
    "from", "further", "had", "has", "have", "having", "he", "her",
    "here", "hers", "herself", "him", "himself", "his", "how", "i", "if",
    "in", "into", "is", "it", "its", "itself", "just", "me", "more",
    "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on",
    "once", "only", "or", "other", "our", "ours", "ourselves", "out",
    "over", "own", "s", "same", "she", "should", "so", "some", "such",
    "t", "than", "that", "the", "their", "theirs", "them", "themselves",
    "then", "there", "these", "they", "this", "those", "through", "to",
    "too", "under", "until", "up", "very", "was", "we", "were", "what",
    "when", "where", "which", "while", "who", "whom", "why", "will",
    "with", "would", "you", "your", "yours", "yourself", "yourselves",
})


def tokenize(text: str) -> list[str]:
    """Lowercase ASCII-alnum tokens (stopword-filtered) + CJK char bigrams.

    Bigrams over each contiguous CJK run ("机器学习" → 机器/器学/学习);
    a lone CJK char is kept as-is. Bag-of-words downstream, so ordering
    between the ASCII and CJK groups is irrelevant.

    中文:输出小写 ASCII 字母数字 token(滤停用词)+ CJK 字符 bigram。
    对每段连续 CJK 文本取相邻二元组("机器学习" → 机器/器学/学习);
    单个 CJK 字符原样保留。下游是词袋模型,所以 ASCII 组与 CJK 组
    之间的先后顺序无关紧要。
    """
    out = [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            out.append(run)
        else:
            out.extend(run[i : i + 2] for i in range(len(run) - 1))
    return out


class _RetrieverLike(Protocol):
    """The vector retriever interface we depend on (Retriever or fake).

    中文:本模块依赖的向量检索器接口(真实 Retriever 或测试替身均可)。
    """

    def search(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = ...,
        k: int = ...,
    ) -> list[SearchHit]: ...


class BM25Corpus:
    """In-memory BM25 index over courses.raw_text. Rebuilt on every restart
    (cheap: tokenize + score for ≤ 1000 docs is ~10ms).

    Construct via BM25Corpus.from_db(conn) for the standard path. The
    constructor takes a {course_id: raw_text} dict for tests.

    中文:基于 courses.raw_text 的内存 BM25 索引,每次重启重建
    (代价很小:≤1000 篇文档的分词 + 打分约 10ms)。标准路径用
    BM25Corpus.from_db(conn) 构造;构造函数直接接受
    {course_id: raw_text} 字典,便于测试。
    """

    def __init__(self, course_texts: dict[str, str]) -> None:
        self._course_ids: list[str] = list(course_texts.keys())
        self._vocab: set[str] = set()
        if not self._course_ids:
            self._bm25: BM25Okapi | None = None
            self._doc_tokens: list[frozenset[str]] = []
            return

        tokenized = [tokenize(course_texts[cid]) for cid in self._course_ids]
        # Replace any all-empty tokenization with a single sentinel so BM25Okapi
        # doesn't crash on empty docs (e.g. raw_text=null edge case).
        # 中文:全空的分词结果用单个哨兵 token 顶替,避免 BM25Okapi 在空文档上
        # 崩溃(例如 raw_text=null 的边界情况)。
        tokenized = [toks if toks else ["__empty__"] for toks in tokenized]
        self._bm25 = BM25Okapi(tokenized)
        # Per-doc token sets: search() needs "does this doc contain ANY query
        # token" as a membership test. Score>0 can't serve that — BM25 IDF
        # degenerates to 0 for terms in half the corpus (e.g. N=2, n=1), so a
        # genuine token match can legitimately score 0.0.
        # 中文:预存每篇文档的 token 集合:search() 需要"该文档是否包含任一
        # 查询 token"这个成员判断。用 分数>0 替代不行 —— 词项出现在半数语料
        # 时 BM25 的 IDF 退化为 0(如 N=2, n=1),真实命中也可能合法地得 0.0 分。
        self._doc_tokens = [frozenset(toks) for toks in tokenized]
        for toks in tokenized:
            self._vocab.update(toks)

    @classmethod
    def from_db(
        cls,
        conn: sqlite3.Connection,
        *,
        status_filter: str | None = ELIGIBLE_STATUS,
    ) -> BM25Corpus:
        """Build a BM25 corpus from courses.raw_text + search_expansion.

        Default status_filter='indexed' matches what the retriever returns —
        BM25 + vector see the same eligible row set, otherwise rankings
        could diverge.

        search_expansion (ADR-0020, doc2query + zh keywords) joins the BM25
        document ONLY — dense embeddings stay computed from raw_text, so
        expansion can widen lexical recall but never perturbs the vector
        leg. Column may be absent on pre-migration DBs → plain raw_text.

        中文:用 courses.raw_text + search_expansion 构建 BM25 语料。
        默认 status_filter='indexed' 与向量检索器返回的行集保持一致 ——
        BM25 与向量两路必须看到同一批合格行,否则排名可能分叉。
        search_expansion(ADR-0020,doc2query + 中文关键词)只拼进 BM25
        文档 —— 稠密向量仍只由 raw_text 计算,因此扩展只会拓宽词面召回,
        绝不扰动向量那一路。迁移前的旧库可能没有该列 → 退回纯 raw_text。
        """
        cols = {row[1] for row in conn.execute("PRAGMA table_info(courses)")}
        text_expr = "COALESCE(raw_text, '')"
        if "search_expansion" in cols:
            text_expr += " || ' ' || COALESCE(search_expansion, '')"
        sql = f"SELECT course_id, {text_expr} AS raw_text FROM courses"
        params: list[Any] = []
        if status_filter is not None:
            sql += " WHERE status = ?"
            params.append(status_filter)
        rows = conn.execute(sql, params).fetchall()
        return cls({r["course_id"]: r["raw_text"] for r in rows})

    def search(
        self,
        query: str,
        *,
        k: int = 10,
        allowed_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Top-k BM25 hits as [(course_id, score), ...] sorted desc.

        Returns [] if NO query token appears in the corpus vocab. This is
        a stronger "no match" signal than score==0, which can also occur
        for tiny corpora where BM25 IDF degenerates (N=2, n=1 → log(1)=0).

        Only docs sharing ≥1 token with the query are returned — argsort
        alone would pad the result with zero-overlap docs up to k, and those
        then siphon RRF mass from genuine hits during fusion.

        `allowed_ids` (optional) restricts the ranking to that course-id set
        BEFORE the top-k cut — used when hard filters narrowed the corpus,
        so a doc that passes the filter but ranks #61 globally still makes
        the within-filter top-k.

        中文:返回 BM25 前 k 名 [(course_id, score), ...],按分数降序。
        若查询没有任何 token 出现在语料词表中,返回 [] —— 这比 score==0
        是更强的"无匹配"信号:小语料下 BM25 IDF 会退化
        (N=2, n=1 → log(1)=0),真命中也可能得 0 分。
        只返回与查询至少共享 1 个 token 的文档 —— 若只靠 argsort,会用
        零重叠文档凑满 k 个,融合时它们会从真命中那里抽走 RRF 质量。
        `allowed_ids`(可选)在截取 top-k 之前先把排名限制在该 course-id
        集合内 —— 用于硬过滤缩小语料的场景:某文档过了过滤、但全局只排
        第 61,仍应进入过滤范围内的 top-k。
        """
        if self._bm25 is None or not self._course_ids:
            return []

        tokens = tokenize(query)
        if not tokens:
            return []

        # Vocab-overlap check: distinguishes "no match possible" from
        # "match exists but BM25 IDF happens to score it zero".
        # 中文:词表重叠检查:区分"根本不可能匹配"与"有匹配、只是 BM25 IDF
        # 恰好打了 0 分"两种情况。
        if not any(t in self._vocab for t in tokens):
            return []

        token_set = set(tokens)
        scores = self._bm25.get_scores(tokens)
        eligible = [
            i
            for i in range(len(self._course_ids))
            if self._doc_tokens[i] & token_set
            and (allowed_ids is None or self._course_ids[i] in allowed_ids)
        ]
        eligible.sort(key=lambda i: -scores[i])
        return [
            (self._course_ids[i], float(scores[i]))
            for i in eligible[:k]
        ]

    @property
    def count(self) -> int:
        return len(self._course_ids)


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    *,
    k: int = DEFAULT_RRF_K,
) -> dict[str, float]:
    """Combine N ranked id-lists via RRF. `k` damps the contribution of
    low-rank items; default 60 is from the original RRF paper.

    中文:用 RRF 融合 N 个有序 id 列表。`k` 抑制低名次条目的贡献;
    默认 60 出自 RRF 原始论文。只看名次不看分数,天然免疫两路分数
    尺度不一致的问题。
    """
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            fused[item_id] = fused.get(item_id, 0.0) + 1.0 / (k + rank)
    return fused


def convex_combination(
    vec_pairs: list[tuple[str, float]],
    bm25_pairs: list[tuple[str, float]],
    *,
    weight_vec: float,
) -> dict[str, float]:
    """Score-aware fusion: weight_vec·minmax(vec) + (1-weight_vec)·minmax(bm25).

    Bruch et al. (TOIS 2023, arXiv:2210.11934): a tuned convex combination
    of NORMALIZED scores beats RRF in- and out-of-domain — RRF's rank-only
    view throws away the score magnitudes that distinguish a confident
    dense match from barely-made-the-cutoff noise. Min-max is per leg per
    query (intra-pool); a doc missing from one leg contributes 0 from that
    leg (it wasn't competitive there). Degenerate one-item / all-equal legs
    normalize to 1.0 — top of a leg is full evidence, however small the
    pool.

    中文:分数感知的凸组合融合:weight_vec·minmax(向量) +
    (1-weight_vec)·minmax(BM25)。Bruch et al.(TOIS 2023,
    arXiv:2210.11934)表明:调好权重、对"归一化分数"做凸组合,在域内
    和域外都优于 RRF —— RRF 只看名次,丢掉了能区分"高置信稠密命中"与
    "勉强挤进候选的噪声"的分数幅度信息。Min-max 按单路、按本次查询做
    (池内归一);某文档在一路缺席,则该路贡献 0(它在那一路本就没有
    竞争力)。单元素 / 全相等的退化情形归一为 1.0 —— 一路的榜首就是
    该路的全部证据,候选池再小也算数。
    """
    if not 0.0 <= weight_vec <= 1.0:
        raise ValueError(f"weight_vec must be in [0, 1], got {weight_vec}")

    def _minmax(pairs: list[tuple[str, float]]) -> dict[str, float]:
        # Per-leg per-query min-max to [0, 1]; the epsilon guard routes
        # degenerate (all-equal) legs to the 1.0 branch instead of 0/0.
        # 中文:单路池内 min-max 归一到 [0, 1];epsilon 防护把全相等的退化
        # 输入导向 1.0 分支,避免 0 除以 0。
        if not pairs:
            return {}
        vals = [s for _, s in pairs]
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-12:
            return {cid: 1.0 for cid, _ in pairs}
        return {cid: (s - lo) / (hi - lo) for cid, s in pairs}

    n_vec = _minmax(vec_pairs)
    n_bm25 = _minmax(bm25_pairs)
    # Union over both legs; .get(cid, 0.0) implements the "missing leg
    # contributes zero" rule from the docstring.
    # 中文:对两路候选取并集;.get(cid, 0.0) 实现 docstring 里"缺席的一路
    # 贡献 0"的规则。
    return {
        cid: weight_vec * n_vec.get(cid, 0.0)
        + (1.0 - weight_vec) * n_bm25.get(cid, 0.0)
        for cid in n_vec.keys() | n_bm25.keys()
    }


class HybridRetriever:
    """RRF combination of vector + BM25 retrieval.

    Mirrors Retriever.search interface (returns list[SearchHit]) so it's a
    drop-in replacement. hard_filters apply to both legs:
      - vector leg: pushed through to underlying retriever's SQLite filter
      - BM25 leg: scoped to the same SQLite-filtered id set (via the
        retriever's filter_ids when available; intersection with the vector
        candidate set as fallback for fakes)

    中文:向量 + BM25 的 RRF 融合检索器。接口与 Retriever.search 完全一致
    (返回 list[SearchHit]),可直接替换。hard_filters 同时作用于两路:
      - 向量路:透传给底层检索器的 SQLite 过滤
      - BM25 路:限定在同一 SQLite 过滤后的 id 集合内(检索器提供
        filter_ids 时优先用它;测试替身没有时,退回与向量候选集求交)
    """

    def __init__(
        self,
        *,
        vector_retriever: _RetrieverLike,
        bm25_corpus: BM25Corpus,
        course_repo: CourseRepository,
        rrf_k: int = DEFAULT_RRF_K,
        candidate_multiplier: int = 3,
        query_expander: Any | None = None,
        fusion_mode: str = "rrf",
        fusion_weight: float = 0.5,
    ) -> None:
        self._vector = vector_retriever
        self._bm25 = bm25_corpus
        self._course_repo = course_repo
        self._rrf_k = rrf_k
        self._candidate_multiplier = candidate_multiplier
        # ADR-0022: "rrf" (rank-only, ADR-0001 era default) or "convex"
        # (score-aware min-max combination; weight = vector leg's share).
        # 中文(ADR-0022):"rrf" = 只看名次(ADR-0001 时代的默认);
        # "convex" = 分数感知的 min-max 凸组合,weight 是向量路的份额。
        self._fusion_mode = fusion_mode
        self._fusion_weight = fusion_weight
        # ADR-0020: optional Callable[[str], str] applied to the query for
        # the RETRIEVAL legs only (e.g. rag.acronyms.expand_query). Caller's
        # reranker + rejection gate keep seeing the original query, so the
        # expander can only add recall, never shift relevance judgment.
        # 中文(ADR-0020):可选 Callable[[str], str],只作用于"检索"两路的
        # 查询(如 rag.acronyms.expand_query)。调用方的重排器 + 拒答门看到
        # 的仍是原始查询,因此扩写只能增加召回,绝不会改变相关性判断。
        self._query_expander = query_expander
        # Per-leg top scores from the LAST search() call. The calibrated
        # rejection gate (rag/rejection.py, ADR-0018) reads these — the
        # fused RRF score deliberately erases score magnitudes, but the
        # gate needs the raw lexical/dense evidence the cross-encoder
        # doesn't see. Instance attribute is safe: routes get a fresh
        # HybridRetriever per request (api/dependencies.py).
        # 中文:上一次 search() 中两路各自的最高分。校准拒答门
        # (rag/rejection.py,ADR-0018)会读取它 —— 融合后的 RRF 分数刻意
        # 抹掉了分数幅度,而拒答门需要交叉编码器看不到的原始词面/稠密证据。
        # 放实例属性是安全的:每个请求都会拿到全新的 HybridRetriever
        # (api/dependencies.py)。
        self.last_diagnostics: dict[str, float] | None = None

    def search(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = None,
        k: int = 10,
    ) -> list[SearchHit]:
        candidate_k = k * self._candidate_multiplier
        if self._query_expander is not None:
            query = self._query_expander(query)

        # Leg 1: vector. Prefer the ID-only path (no per-candidate SQLite
        # rehydration — fusion only needs IDs; hydration happens once on the
        # fused top-k below). Fall back to .search() for retriever fakes
        # that only implement the SearchHit interface.
        # 中文:第 1 路:向量。优先走只返回 ID 的路径(免去逐候选的 SQLite
        # 回填 —— 融合只需要 ID,回填在下方对融合后的 top-k 一次完成)。
        # 只实现 SearchHit 接口的测试替身退回 .search()。
        search_ids = getattr(self._vector, "search_ids", None)
        if callable(search_ids):
            vec_pairs = search_ids(query, hard_filters=hard_filters, k=candidate_k)
        else:
            vec_pairs = [
                (h.course.course_id, h.score)
                for h in self._vector.search(
                    query, hard_filters=hard_filters, k=candidate_k,
                )
            ]
        vec_ids = [cid for cid, _ in vec_pairs]

        # Leg 2: BM25, scoped to the SAME filtered set as the vector leg when
        # hard_filters are active. The old approach intersected BM25 output
        # with the vector top-(k*3) — which silently dropped a course that
        # passes the filter and ranks #1 on BM25 but #61 on vector. Fakes
        # without filter_ids keep the old (lossier) intersection behavior.
        # 中文:第 2 路:BM25。hard_filters 生效时,限定在与向量路完全相同的
        # 过滤集合内。旧做法是拿 BM25 输出与向量 top-(k*3) 求交 —— 会悄悄
        # 丢掉"过了过滤、BM25 第 1 名但向量第 61 名"的课程。没有 filter_ids
        # 的测试替身沿用旧的(有损)交集行为。
        allowed: set[str] | None = None
        if hard_filters:
            filter_ids = getattr(self._vector, "filter_ids", None)
            allowed = (
                set(filter_ids(hard_filters)) if callable(filter_ids) else set(vec_ids)
            )
        bm25_hits = self._bm25.search(query, k=candidate_k, allowed_ids=allowed)
        bm25_ids = [cid for cid, _ in bm25_hits]

        # Record each leg's raw top-1 evidence for the calibrated rejection
        # gate (ADR-0018) before fusion erases the magnitudes.
        # 中文:在融合抹掉分数幅度之前,先记录两路各自的原始 top-1 证据,
        # 供校准拒答门(ADR-0018)使用。
        self.last_diagnostics = {
            "vec_top": float(vec_pairs[0][1]) if vec_pairs else 0.0,
            "bm25_top": float(bm25_hits[0][1]) if bm25_hits else 0.0,
        }

        if not vec_ids and not bm25_ids:
            return []

        if self._fusion_mode == "convex":
            # ADR-0022: score-aware convex fusion keeps score magnitudes.
            # 中文:ADR-0022 分数感知凸组合 —— 保留分数幅度信息。
            fused = convex_combination(
                vec_pairs, bm25_hits, weight_vec=self._fusion_weight,
            )
        else:
            # Default RRF: rank-only fusion, immune to score-scale mismatch.
            # 中文:默认 RRF:只看名次融合,对两路分数尺度错配免疫。
            fused = reciprocal_rank_fusion(
                [vec_ids, bm25_ids],
                k=self._rrf_k,
            )

        top_k = sorted(fused, key=lambda c: -fused[c])[:k]
        if not top_k:
            return []
        # Batch fetch — avoids N+1 (was k SELECTs in a list comprehension).
        # 中文:批量取课 —— 避免 N+1 查询(旧版在列表推导里发 k 条 SELECT)。
        courses = self._course_repo.get_batch(top_k)
        return [
            SearchHit(course=courses[cid], score=fused[cid])
            for cid in top_k
            if cid in courses  # skip dangling refs (alias points at vanished course)
            # 中文:跳过悬空引用(alias 指向已消失的课程)。
        ]


__all__ = [
    "DEFAULT_RRF_K",
    "BM25Corpus",
    "HybridRetriever",
    "convex_combination",
    "reciprocal_rank_fusion",
    "tokenize",
]
