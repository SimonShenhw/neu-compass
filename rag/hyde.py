"""HyDE — Hypothetical Document Embeddings query expansion.

Pattern from Gao et al. 2022. The LLM generates a hypothetical course
description that *would* answer the user's query; we then embed THAT
description (not the query itself) before vector search.

模式来自 Gao et al. 2022。LLM 生成一段"假设性"的课程描述,这段描述本应
能回答用户的查询;然后我们 embed 的是这段描述本身(而不是原始查询),
再去做向量检索。

Why it helps:
  - User queries are short + interrogative ("hard NLP class")
  - Course descriptions are long + declarative ("This course covers...")
  - Embedding spaces don't perfectly align across these two distributions
  - Embedding a hypothetical description nudges the query vector closer
    to the document distribution

为什么有效:
  - 用户查询短、是疑问句("hard NLP class")
  - 课程描述长、是陈述句("This course covers...")
  - 这两种分布的 embedding 空间并不完全对齐
  - embed 一段假设性描述,能把查询向量往文档分布的方向拉近

Cost: 1 extra LLM call per query (~$0.0001 on Gemini 2.5 Flash). Caller
decides whether to apply HyDE always or only when the cheap path returns
weak results (PLAN §8 budget discipline).

成本:每次查询多一次 LLM 调用(在 Gemini 2.5 Flash 上约 $0.0001)。
调用方自行决定是始终应用 HyDE,还是只在廉价路径返回弱结果时才用
(PLAN §8 的预算纪律)。
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from llm.gemini_client import generate_text
from rag.retriever import SearchHit

DEFAULT_TEMPERATURE = 0.3  # mild creativity; too high invents non-existent topics
# 中文:温和的创造性;温度太高会编造出不存在的主题。

# The HyDE expansion prompt (the Gao et al. 2022 pattern described above).
# 中文:HyDE 扩写用的 prompt(即上文所述 Gao et al. 2022 的方法)。
HYDE_PROMPT_TEMPLATE = """Generate a 2-3 sentence hypothetical course description \
that would directly answer a graduate student's question about a Northeastern \
University course. Write the description as if you were the course catalog. \
Output ONLY the description, no preamble, no quoting back the question.

Student question: {query}

Course description:"""


class _RetrieverLike(Protocol):
    # The retriever interface HydeRetriever wraps (Retriever/HybridRetriever
    # or a test fake) — same shape as rag.hybrid's _RetrieverLike Protocol.
    # 中文:HydeRetriever 包装的检索器接口(Retriever/HybridRetriever 或
    # 测试替身均可)—— 形状与 rag.hybrid 的 _RetrieverLike Protocol 相同。
    def search(
        self, query: str, *, hard_filters: dict[str, Any] | None = ..., k: int = ...,
    ) -> list[SearchHit]: ...


# ADR-0019: second-opinion prompt for the rescue pass. One call does BOTH
# jobs — intent judgment (keeps the adversarial wall: garbage gets no
# second chance) and HyDE expansion (gives real-but-evidence-poor queries
# like "VC dimension PAC learning" / "CRM 认知偏差" a retrieval retry).
# 中文(ADR-0019):rescue 环节的第二意见 prompt。一次调用同时完成两件事——
# 意图判断(守住对抗性防线:垃圾查询得不到第二次机会)和 HyDE 扩写
# (给"真实但证据稀少"的查询,如 "VC dimension PAC learning" /
# "CRM 认知偏差",一次重新检索的机会)。
RESCUE_PROMPT_TEMPLATE = """A university course-search engine rejected the \
query below as "no matching course". You are the second-opinion judge.

Decide: is this a plausible query a student would type to find an EXISTING \
university course or course topic? The query may be in Chinese or mixed \
Chinese/English; technical jargon, theory terms, and field acronyms (expand \
them from context) are all plausible course topics.

- If NO — gibberish, homework/assignment requests, campus services or \
admin questions, chit-chat, jokes, or fictional/speculative topics that no \
real university teaches as a course today (e.g. time travel, teleportation, \
magic) — output exactly: REJECT
- If YES — output a 2-3 sentence hypothetical course description (in \
English) that would answer it, written as if from the course catalog. \
Spell out any acronyms using the query's context. No preamble.

Query: {query}
"""


def rescue_expand(
    query: str,
    *,
    generate_fn: Callable[[str], str] | None = None,
    temperature: float = 0.0,
) -> str | None:
    """Second-opinion expansion for the rejection rescue pass (ADR-0019).

    Returns the hypothetical description, or None when the LLM judges the
    query not course-seeking (REJECT) — caller keeps the original rejection.

    temperature=0.0 (not DEFAULT_TEMPERATURE): the REJECT-vs-expand verdict
    is a judgment call and must be as deterministic as possible — at 0.3,
    borderline fictional queries ("time travel paradox engineering")
    flipped verdicts between runs (observed on the v0.3 eval).

    中文:拒答 rescue 环节(ADR-0019)的第二意见扩写。
    返回假设性描述;当 LLM 判定该查询并非在找课程(REJECT)时返回 None ——
    调用方保留原本的拒答结果。
    temperature=0.0(而不是 DEFAULT_TEMPERATURE):REJECT-vs-expand 是一个
    判断题,必须尽可能确定性 —— 在 0.3 温度下,边界性的虚构查询
    ("time travel paradox engineering")在多次运行间会翻转判断结果
    (在 v0.3 评测中观察到)。
    """
    prompt = RESCUE_PROMPT_TEMPLATE.format(query=query)
    if generate_fn is None:
        # Short HTTP budget: this call runs INSIDE a /search request; the
        # 120s default would let one slow Gemini response hold the user
        # (and a threadpool worker) for two minutes. On timeout the caller
        # keeps the original rejection — rescue is best-effort by contract.
        # 12s, NOT lower: Gemini rejects deadlines under 10s with a 400
        # ("Minimum allowed deadline is 10s") — an 8s budget killed every
        # rescue instantly and cost R@5 1.25pts before eval caught it.
        # 中文:HTTP 预算故意设短:这次调用运行在一个 /search 请求内部;
        # 120 秒的默认值会让一次缓慢的 Gemini 响应把用户(和一个线程池
        # worker)拖住两分钟。超时后调用方保留原本的拒答 —— rescue 按
        # 合同就是尽力而为。12 秒,不能再低:Gemini 对低于 10 秒的
        # deadline 会直接拒绝并返回 400("Minimum allowed deadline is
        # 10s")—— 8 秒的预算曾让每一次 rescue 瞬间失败,在被评测发现
        # 之前拖累了 R@5 达 1.25 分。
        out = generate_text(prompt, temperature=temperature, timeout_ms=12_000)
    else:
        out = generate_fn(prompt)
    text = out.strip()
    if not text or text.upper().startswith("REJECT"):
        return None
    return text


def expand_query_via_hyde(
    query: str,
    *,
    generate_fn: Callable[[str], str] | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    """Generate a hypothetical course description for the query.

    Default uses llm.gemini_client.generate_text; tests inject a fake.
    Returns the LLM output stripped of leading/trailing whitespace.

    中文:为查询生成一段假设性的课程描述。
    默认使用 llm.gemini_client.generate_text;测试会注入一个假实现。
    返回值是去除首尾空白后的 LLM 输出。
    """
    prompt = HYDE_PROMPT_TEMPLATE.format(query=query)
    if generate_fn is None:
        return generate_text(prompt, temperature=temperature).strip()
    return generate_fn(prompt).strip()


class HydeRetriever:
    """Wraps a base retriever; expands query via LLM before passing through.

    Drop-in interface compatible with Retriever / HybridRetriever — same
    .search(query, hard_filters=..., k=...) signature returning list[SearchHit].

    中文:包装一个基础检索器;先经 LLM 扩写查询,再传给基础检索器。
    接口可直接替换 Retriever / HybridRetriever —— 同样的
    .search(query, hard_filters=..., k=...) 签名,返回 list[SearchHit]。
    """

    def __init__(
        self,
        *,
        base_retriever: _RetrieverLike,
        expand_fn: Callable[[str], str] | None = None,
        prepend_original: bool = True,
    ) -> None:
        self._base = base_retriever
        self._expand_fn = expand_fn
        # When True, the expanded text is "<original>\n\n<hypothetical>" so the
        # base retriever sees BOTH the user's original phrasing (good for term
        # matches) and the LLM expansion (good for distribution alignment).
        # 中文:为 True 时,扩写后的文本是 "<原始查询>\n\n<假设性描述>",
        # 这样基础检索器能同时看到用户的原始措辞(有利于词项匹配)和 LLM
        # 扩写(有利于分布对齐)。
        self._prepend_original = prepend_original

    def search(
        self,
        query: str,
        *,
        hard_filters: dict[str, Any] | None = None,
        k: int = 10,
    ) -> list[SearchHit]:
        expanded = self._expand_query(query)
        if self._prepend_original:
            combined = f"{query}\n\n{expanded}"
        else:
            combined = expanded
        return self._base.search(combined, hard_filters=hard_filters, k=k)

    def _expand_query(self, query: str) -> str:
        if self._expand_fn is None:
            return expand_query_via_hyde(query)
        return expand_query_via_hyde(query, generate_fn=self._expand_fn)


__all__ = [
    "DEFAULT_TEMPERATURE",
    "HYDE_PROMPT_TEMPLATE",
    "RESCUE_PROMPT_TEMPLATE",
    "HydeRetriever",
    "expand_query_via_hyde",
    "rescue_expand",
]
