"""Cross-encoder reranker (bge-reranker-v2-m3) — Week 6 PLAN §4.4 P1.

Why a cross-encoder on top of vector + BM25:
  Vector + BM25 (RRF) gives broad recall but ranking accuracy degrades
  on STEM-heavy text where bge-m3 dense scores cluster in 0.4-0.7 (see
  docs/rag_smoke_results.md §6). A cross-encoder scores each (query,
  candidate) pair jointly through one transformer pass, producing a
  much sharper ranking signal — at ~50ms/batch latency cost.

为什么在 向量 + BM25 之上再加交叉编码器:
  向量 + BM25(RRF)召回面广,但在 STEM 密集文本上排序精度下降 ——
  bge-m3 稠密分数挤在 0.4-0.7(见 docs/rag_smoke_results.md §6)。
  交叉编码器把每个 (query, candidate) 对拼接后过同一遍 transformer
  联合打分,排序信号锐利得多 —— 代价是每批约 50ms 的延迟。

Pipeline insertion (caller decides):
    candidates = hybrid_retriever.search(query, k=20)   # broad recall
    reranked   = reranker.rerank_search_hits(           # narrow precision
        query, candidates, fetch_text=fetch_raw_text, top_k=10,
    )

管线插入位置(由调用方决定):如上例,先宽召回(k=20)、再窄精排
(top_k=10)。

The pure scoring API is `score(query, candidates: list[str]) -> list[float]`
— testable without the SQLite layer. `rerank_search_hits` is a
SearchHit-aware wrapper that pulls raw_text via a caller-provided
fetch_text callable; tests pass a dict-backed fetcher.

纯打分 API 是 `score(query, candidates) -> list[float]` —— 不碰 SQLite
层即可测试。`rerank_search_hits` 是感知 SearchHit 的包装,通过调用方
提供的 fetch_text 可调用对象拉取 raw_text;测试传一个字典实现的
fetcher 即可。

Lazy load: the FlagReranker model (~600MB on disk, ~1.5s GPU init) is
NOT loaded at import time. First .score() call triggers it.

懒加载:FlagReranker 模型(磁盘约 600MB,GPU 初始化约 1.5s)不在
import 时加载,首次 .score() 调用才触发。

Z-score blending (PLAN v2.2 §3.5):
  `rerank_blend_hits` linearly combines the upstream RRF score with the
  reranker sigmoid after standardizing each leg per call. α picks a point
  on the {pure-RRF, pure-reranker} continuum. Z-score over Min-Max because
  the reranker's bimodal sigmoid distribution would otherwise be compressed
  at the top of the pool, exactly where ranking discrimination matters.

Z-score 混合(PLAN v2.2 §3.5):
  `rerank_blend_hits` 先把两路信号各自按本次调用做标准化,再把上游
  RRF 分数与重排器 sigmoid 线性组合。α 在 {纯 RRF, 纯重排器} 连续谱
  上取点。选 Z-score 而非 Min-Max:重排器 sigmoid 分布是双峰的,
  Min-Max 会把候选池顶部压扁 —— 而顶部恰恰是排序区分度最要紧的位置。
"""

from __future__ import annotations

import threading
from typing import Callable, TypeVar

from rag.retriever import SearchHit

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"

T = TypeVar("T")


class CrossEncoderReranker:
    """bge-reranker-v2-m3 wrapper. Lazy-loaded; caller manages threading.

    `compile_mode` (Week 9 Day 2 hook): when set (e.g. "default",
    "reduce-overhead"), the inner transformers model is wrapped with
    torch.compile after load. Roughly 10-25% latency reduction on RTX 5090
    in our 20-pair rerank batch; compilation cost (~5-30s) is paid once
    during lifespan warmup. NO effect when caller goes through OnnxReranker
    instead — torch.compile is PyTorch-only.

    中文:bge-reranker-v2-m3 包装类。懒加载;线程使用方式由调用方决定。
    `compile_mode`(第 9 周 Day 2 的挂钩):设置后(如 "default"、
    "reduce-overhead"),加载完成会用 torch.compile 包住内部 transformers
    模型。RTX 5090 上对 20 对重排批次约有 10-25% 延迟收益;编译成本
    (约 5-30s)在 lifespan 预热时一次付清。调用方走 OnnxReranker 时
    无效 —— torch.compile 只作用于 PyTorch。
    """

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        *,
        device: str = "cuda",
        use_fp16: bool = True,
        compile_mode: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.use_fp16 = use_fp16
        self.compile_mode = compile_mode
        self._model: object | None = None
        # Routes run in FastAPI's threadpool (sync def) — concurrent requests
        # may call score() in parallel. One inference at a time per model:
        # protects lazy _load() and the forward pass itself.
        # 中文:路由跑在 FastAPI 线程池里(sync def)—— 并发请求可能同时调
        # score()。每个模型同一时刻只允许一次推理:锁同时保护懒加载
        # _load() 和前向传播本身。
        self._lock = threading.Lock()

    def _load(self) -> tuple[object, object]:
        """Load tokenizer + model via raw transformers (HuggingFace).

        We bypass FlagEmbedding.FlagReranker because its older code path
        calls `tokenizer.prepare_for_model` which has been removed from
        transformers >= 4.30. Going through AutoModelForSequenceClassification
        gives us the same bge-reranker-v2-m3 weights without that coupling.

        中文:直接用原生 transformers(HuggingFace)加载 tokenizer + 模型。
        绕开 FlagEmbedding.FlagReranker 的原因:其旧代码路径会调用
        `tokenizer.prepare_for_model`,而该方法在 transformers >= 4.30 中
        已被移除。改走 AutoModelForSequenceClassification,拿到的是同一份
        bge-reranker-v2-m3 权重,却没有那层版本耦合。
        """
        if self._model is not None:
            return self._tokenizer, self._model  # type: ignore[return-value]

        import torch  # noqa: PLC0415
        from transformers import (  # noqa: PLC0415
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        model.eval()
        if self.device == "cuda" and torch.cuda.is_available():
            model = model.to("cuda")
            if self.use_fp16:
                model = model.half()

        if self.compile_mode:
            try:
                model = torch.compile(model, mode=self.compile_mode)
            except Exception as e:  # noqa: BLE001 — best-effort wrap
                # 中文:编译失败只降级为未编译模型并打警告,不阻断服务。
                print(f"warning: torch.compile failed for reranker: {e}")

        self._model = model
        self._torch = torch  # cache for score()
        # 中文:缓存 torch 模块引用,score() 里免于重复 import。
        return self._tokenizer, self._model

    def score(self, query: str, candidates: list[str]) -> list[float]:
        """Score each candidate against the query. Higher = more relevant.

        Empty input → empty output. Output is sigmoid-normalized to [0, 1]
        so absolute thresholds become meaningful (a future "no clear match"
        rejection layer can use ~0.5 as the cut).

        中文:给每个候选相对 query 打分,分数越高越相关。
        空输入 → 空输出。输出经 sigmoid 归一到 [0, 1],绝对阈值因此有
        意义(将来的"无明确匹配"拒答层可拿约 0.5 作切点)。
        """
        if not candidates:
            return []
        with self._lock:
            # Tokenization happens INSIDE the lock: tokenizer + model live
            # as shared mutable state on self, and fast tokenizers are not
            # guaranteed thread-safe; serializing the whole pass also keeps
            # GPU memory usage bounded to one batch at a time.
            # 中文:分词也放在锁内:tokenizer 和模型是 self 上的共享可变
            # 状态,fast tokenizer 不保证线程安全;整段推理串行化还能把
            # GPU 显存占用限制在同一时刻一个批次。
            tokenizer, model = self._load()
            torch = self._torch  # type: ignore[attr-defined]

            inputs = tokenizer(
                [query] * len(candidates),
                candidates,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512,
            )
            if self.device == "cuda" and torch.cuda.is_available():
                inputs = {k: v.to("cuda") for k, v in inputs.items()}

            with torch.no_grad():
                logits = model(**inputs).logits.view(-1).float()
                probs = torch.sigmoid(logits)
            return [float(p) for p in probs.cpu().tolist()]


def rerank_pairs(
    query: str,
    pairs: list[tuple[T, str]],
    reranker: CrossEncoderReranker,
    *,
    top_k: int | None = None,
) -> list[tuple[T, float]]:
    """Score (payload, text) pairs and return them sorted by reranker
    score desc. Pure utility — keeps the reranker generic over payload type.

    `top_k=None` keeps all input pairs; otherwise truncates after sort.

    中文:给 (payload, text) 对打分,按重排分数降序返回。纯工具函数 ——
    让重排器对 payload 类型保持泛型。`top_k=None` 保留全部输入;
    否则先排序后截断。
    """
    if not pairs:
        return []
    payloads, texts = zip(*pairs)
    scores = reranker.score(query, list(texts))
    scored = list(zip(payloads, scores))
    scored.sort(key=lambda t: -t[1])
    if top_k is not None:
        scored = scored[:top_k]
    return scored


def rerank_search_hits(
    query: str,
    hits: list[SearchHit],
    reranker: CrossEncoderReranker,
    *,
    fetch_text: Callable[[str], str | None],
    top_k: int | None = None,
) -> list[SearchHit]:
    """Rerank SearchHits using each hit's raw_text (resolved via
    `fetch_text(course_id)`). Hits whose fetch_text returns None or empty
    fall back to `course.primary_name` so they still get scored.

    Returns SearchHits with the cross-encoder score in `.score` (replacing
    the upstream RRF fused score). Caller relies on this score going
    forward, e.g. for absolute-threshold "no clear match" decisions.

    中文:用每条命中的 raw_text(经 `fetch_text(course_id)` 解析)重排
    SearchHit。fetch_text 返回 None 或空串时退回 `course.primary_name`,
    保证仍能被打分。返回的 SearchHit 中 `.score` 已换成交叉编码器分数
    (覆盖上游 RRF 融合分)。调用方后续依赖这个分数,例如做绝对阈值的
    "无明确匹配"判定。
    """
    if not hits:
        return []

    pairs: list[tuple[SearchHit, str]] = []
    for hit in hits:
        text = fetch_text(hit.course.course_id) or hit.course.primary_name
        pairs.append((hit, text))

    scored = rerank_pairs(query, pairs, reranker, top_k=top_k)
    return [SearchHit(course=hit.course, score=score) for hit, score in scored]


def zscore_blend(
    rrf_scores: list[float],
    rerank_scores: list[float],
    alpha: float,
) -> list[float]:
    """Linearly blend two scoring signals after Z-score normalization.

    Returns per-item blended score in input order. Higher = more relevant.

    Args:
      rrf_scores: upstream fusion scores (e.g. HybridRetriever .score)
      rerank_scores: cross-encoder sigmoid scores in [0, 1]
      alpha: weight on the RRF leg. α=1.0 → pure RRF ordering;
             α=0.0 → pure reranker ordering. Must be in [0, 1].

    Standardization is per call (mean+std over the input pool), not against
    any global distribution — the blend is intra-pool. If a leg has zero
    variance (all equal), its Z-score is 0 and the other leg drives ordering.

    PLAN v2.2 §3.5 locks Z-score over Min-Max: Min-Max compresses the
    bge-reranker bimodal sigmoid distribution at the top of the pool
    (where discrimination matters most) and amplifies RRF's narrow score
    range arbitrarily. Z-score gives clean α semantics: α=0.5 strictly
    means "equal weight on both standardized signals".

    中文:两路信号各自做 Z-score 标准化后按 α 线性混合;按输入顺序返回
    每项的混合分,越高越相关。α 是 RRF 一路的权重:α=1.0 → 纯 RRF 排序;
    α=0.0 → 纯重排器排序。
    标准化按本次调用做(对输入池求均值+标准差),不参照任何全局分布 ——
    混合是池内的。某一路方差为零(全相等)时其 Z-score 记 0,排序由另
    一路驱动。
    为什么选 Z-score 而非 Min-Max(PLAN v2.2 §3.5 定论):Min-Max 会把
    bge-reranker 的双峰 sigmoid 分布在候选池顶部压扁(恰是区分度最重要
    的位置),又会任意放大 RRF 狭窄的分数区间。Z-score 让 α 语义干净:
    α=0.5 严格等于"两路标准化信号等权"。
    """
    if len(rrf_scores) != len(rerank_scores):
        raise ValueError(
            f"score list length mismatch: "
            f"rrf={len(rrf_scores)} rerank={len(rerank_scores)}"
        )
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha must be in [0, 1], got {alpha}")
    if not rrf_scores:
        return []

    import numpy as np  # noqa: PLC0415  — local import keeps import-time cost low
    # 中文:函数内局部 import,保持模块导入时的开销低。

    rrf = np.asarray(rrf_scores, dtype=np.float64)
    rer = np.asarray(rerank_scores, dtype=np.float64)

    # Variance floor avoids amplifying float64 round-off into spurious z-scores.
    # Example: [0.1, 0.1, 0.1].std() is ~1e-17 (not exactly 0) because 0.1 isn't
    # exactly representable; a strict `> 0` check would divide noise by noise
    # and yield z-scores of magnitude 1 from a constant input.
    # 中文:方差下限防止把 float64 舍入误差放大成假 z-score。例如
    # [0.1, 0.1, 0.1].std() 约为 1e-17(并非精确 0),因为 0.1 无法被二进制
    # 精确表示;若只检查 `> 0`,就成了"噪声除以噪声",常数输入会凭空得出
    # 量级为 1 的 z-score。
    _STD_EPSILON = 1e-12

    rrf_std = float(rrf.std())
    rer_std = float(rer.std())
    rrf_z = (rrf - rrf.mean()) / rrf_std if rrf_std > _STD_EPSILON else np.zeros_like(rrf)
    rer_z = (rer - rer.mean()) / rer_std if rer_std > _STD_EPSILON else np.zeros_like(rer)

    blended = alpha * rrf_z + (1.0 - alpha) * rer_z
    return [float(b) for b in blended]


def rerank_blend_hits(
    query: str,
    hits: list[SearchHit],
    reranker: CrossEncoderReranker,
    *,
    fetch_text: Callable[[str], str | None],
    blend_alpha: float,
    top_k: int | None = None,
) -> list[SearchHit]:
    """Z-score blend the upstream score in `hits[i].score` with the reranker
    sigmoid, then sort desc.

    Caller responsibilities:
      - hits MUST come from HybridRetriever (or anything where .score is the
        upstream fusion score). Blending is meaningless if .score is already
        a reranker score.
      - For PLAN §3.4 rejection layer, use `rerank_blend_with_rejection`
        instead — it shares the single reranker pass with the rejection
        gate, avoiding a redundant scoring call.

    Returns SearchHits with `.score` set to the blended Z-score (typically
    -2 to +2; centered on 0; not in [0, 1]). Use the raw reranker sigmoid
    for absolute-threshold decisions.

    中文:把 `hits[i].score` 里的上游分数与重排器 sigmoid 做 Z-score
    混合,再降序排序。
    调用方须知:
      - hits 必须来自 HybridRetriever(或任何 .score 是上游融合分的来源);
        若 .score 已经是重排分,混合就没有意义。
      - 需要 PLAN §3.4 拒答层时,请改用 `rerank_blend_with_rejection` ——
        它与拒答门共享同一次重排打分,避免重复推理。
    返回的 SearchHit 中 `.score` 是混合后的 Z 分(通常在 -2 到 +2、以 0
    为中心、不落在 [0, 1] 内)。绝对阈值判定请用原始重排 sigmoid。
    """
    if not hits:
        return []

    pairs: list[tuple[SearchHit, str]] = []
    for hit in hits:
        text = fetch_text(hit.course.course_id) or hit.course.primary_name
        pairs.append((hit, text))

    rrf_scores = [hit.score for hit, _ in pairs]
    texts = [text for _, text in pairs]
    rerank_scores = reranker.score(query, texts)

    blended = zscore_blend(rrf_scores, rerank_scores, alpha=blend_alpha)

    indexed = list(zip([hit for hit, _ in pairs], blended))
    indexed.sort(key=lambda t: -t[1])
    if top_k is not None:
        indexed = indexed[:top_k]
    return [SearchHit(course=hit.course, score=score) for hit, score in indexed]


def rerank_blend_with_rejection(
    query: str,
    hits: list[SearchHit],
    reranker: CrossEncoderReranker,
    *,
    fetch_text: Callable[[str], str | None],
    blend_alpha: float,
    reject_threshold: float,
    top_k: int | None = None,
    gate_fn: Callable[[list[float]], tuple[bool, str]] | None = None,
) -> tuple[list[SearchHit], dict[str, object]]:
    """Combined rejection-and-blend pass for PLAN v2.2 §3.4 + §3.5.

    Two questions in one reranker call:
      1. **Reject?** Default gate: `max(raw_sigmoid) < reject_threshold`
         (ADR-0016). When `gate_fn` is provided (ADR-0018 calibrated gate),
         it receives the full sigmoid list and returns (reject, reason) —
         the threshold parameter is then ignored. Rejection is decided on
         RAW sigmoids (not blended z-scores) because it's an
         absolute-confidence question, not a ranking question.
      2. **Order?** If accepted, Z-score blend the upstream RRF score with
         the same raw sigmoid (alpha = blend_alpha), sort desc, truncate
         to top_k, return as SearchHits with blended z-score in `.score`.

    Returns:
      (hits, meta) where meta is one of:
        {"rejected": True, "reason": str, "max_sigmoid": float,
         "n_candidates": int}
        {"rejected": False, "max_sigmoid": float,
         "n_above_threshold": int, "n_candidates": int}

    Single reranker pass — score(query, texts) is called once. The
    rejection gate and the blend share the same sigmoid output.

    中文:PLAN v2.2 §3.4 + §3.5 的"拒答 + 混合"合并流程。
    一次重排调用回答两个问题:
      1. 拒答吗?默认门:`max(原始 sigmoid) < reject_threshold`
         (ADR-0016)。提供 gate_fn 时(ADR-0018 校准门),由它接收完整
         sigmoid 列表并返回 (reject, reason),此时阈值参数被忽略。拒答
         基于原始 sigmoid 而非混合 z 分 —— 这是"绝对置信度"问题,
         不是排序问题。
      2. 怎么排?若通过,用同一批原始 sigmoid 与上游 RRF 分做 Z-score
         混合(alpha = blend_alpha),降序、截断到 top_k,`.score` 里放
         混合 z 分。
    只跑一次重排 —— score(query, texts) 仅调用一次,拒答门与混合共享
    同一份 sigmoid 输出。
    """
    n = len(hits)
    if n == 0:
        return [], {
            "rejected": False,
            "reason": "no_candidates",
            "max_sigmoid": 0.0,
            "n_candidates": 0,
            "n_above_threshold": 0,
        }

    pairs: list[tuple[SearchHit, str]] = []
    for hit in hits:
        text = fetch_text(hit.course.course_id) or hit.course.primary_name
        pairs.append((hit, text))

    rrf_scores = [hit.score for hit, _ in pairs]
    texts = [text for _, text in pairs]
    rerank_scores = reranker.score(query, texts)

    max_sig = max(rerank_scores) if rerank_scores else 0.0
    n_above = sum(1 for s in rerank_scores if s >= reject_threshold)

    if gate_fn is not None:
        rejected, reason = gate_fn(rerank_scores)
    else:
        rejected = max_sig < reject_threshold
        reason = f"max_reranker_sigmoid {max_sig:.3f} < threshold {reject_threshold}"

    if rejected:
        return [], {
            "rejected": True,
            "reason": reason,
            "max_sigmoid": float(max_sig),
            "n_candidates": n,
            "n_above_threshold": 0,
        }

    blended = zscore_blend(rrf_scores, rerank_scores, alpha=blend_alpha)
    indexed = list(zip([hit for hit, _ in pairs], blended))
    indexed.sort(key=lambda t: -t[1])
    if top_k is not None:
        indexed = indexed[:top_k]

    return (
        [SearchHit(course=hit.course, score=score) for hit, score in indexed],
        {
            "rejected": False,
            "max_sigmoid": float(max_sig),
            "n_candidates": n,
            "n_above_threshold": n_above,
        },
    )


__all__ = [
    "DEFAULT_RERANKER_MODEL",
    "CrossEncoderReranker",
    "rerank_blend_hits",
    "rerank_blend_with_rejection",
    "rerank_pairs",
    "rerank_search_hits",
    "zscore_blend",
]
