"""Extract structured filters (QueryFilters) from a natural-language query.

Layer 2 of the v3.0 RAG quality plan. Two paths:

v3.0 RAG 质量计划的 Layer 2。两条路径:

1. **Regex (fast, free)**: detect explicit program-prefix tokens like
   `AAI`, `CS`, `DS`, `EECE`, `INFO`, `MATH`, ... when they appear as a
   bare word in the query. Catches the common case where a bilingual user
   types "我是 aai 专业 第一学期选啥" or "what should I take for CS major".
   Zero LLM cost, ~microseconds.

1. **正则(快、免费)**:当 `AAI`、`CS`、`DS`、`EECE`、`INFO`、`MATH` 等
   以独立单词形式出现在查询里时,检测这些显式的专业前缀 token。覆盖了
   双语用户常见的写法,如 "我是 aai 专业 第一学期选啥" 或
   "what should I take for CS major"。零 LLM 成本,约微秒级。

2. **LLM (slower, $$)**: when no explicit prefix is in the query but
   the query mentions a program / major name (e.g. "AI 专业", "数据科学",
   "I'm in the data analytics program"), an LLM call maps the program
   name to a prefix. ~200-500ms + Gemini token cost.

2. **LLM(更慢、要花钱)**:当查询里没有显式前缀、但提到了专业/主修
   名称(如 "AI 专业"、"数据科学"、"I'm in the data analytics
   program")时,发起一次 LLM 调用,把专业名称映射到前缀。约
   200-500ms,外加 Gemini token 开销。

`extract_filters_adaptive` tries regex first; only calls the LLM if no
prefix was found AND a "program/major" keyword is present (heuristic gate
that skips the LLM for ~80% of queries that have neither signal).

`extract_filters_adaptive` 先走正则;只有在没找到前缀 且 出现了"专业/
主修"关键词时才调用 LLM(这个启发式门能让约 80% 两种信号都没有的查询
跳过 LLM 调用)。

The LLM hook is `Callable[[str], dict[str, object]]` for testability —
production passes a Gemini-backed extractor; tests pass a fake.

LLM 钩子的类型是 `Callable[[str], dict[str, object]]`,便于测试 ——
生产环境传入一个基于 Gemini 的抽取器;测试传入一个假实现。
"""

from __future__ import annotations

import re
from typing import Callable

from schemas.query_filter import QueryFilters

# NEU graduate program prefixes we recognize. Sourced from the catalog scrape
# (231 unique department codes, but most users only mention these top-level
# prefixes). Add to this list as new programs surface in real query logs.
# 中文:我们识别的 NEU 研究生专业前缀。来自目录抓取(231 个不同系代码,
# 但大多数用户只会提到这些顶层前缀)。有新专业在真实查询日志中出现时,
# 把它加进这个列表。下面各项的英文全称已在行内注释给出:AAI=应用人工
# 智能、CS=计算机科学、CSYE=计算机系统工程(Khoury / IS)、DS=数据
# 科学、EECE=电气与计算机工程、INFO=信息系统、ALY=分析学、
# BINF=生物信息学、MATH=数学、MGSC=管理科学、STAT=统计学(研究生)、
# IE=工业工程。
KNOWN_PROGRAM_PREFIXES: frozenset[str] = frozenset({
    "AAI",   # Applied AI
    "CS",    # Computer Science
    "CSYE",  # Computer Systems Engineering (Khoury / IS)
    "DS",    # Data Science
    "EECE",  # Electrical & Computer Engineering
    "INFO",  # Information Systems
    "ALY",   # Analytics
    "BINF",  # Bioinformatics
    "MATH",  # Mathematics
    "MGSC",  # Management Science
    "STAT",  # Statistics (graduate)
    "IE",    # Industrial Engineering
})

# Prefixes that double as ordinary English words. Case-insensitive matching
# turned "any info on machine learning courses" into program_prefix='INFO'
# (→ hard filter primary_code LIKE 'INFO %', silently hiding everything
# else). For these we only accept the ALL-CAPS spelling — a user naming the
# Information Systems program writes "INFO", prose writes "info".
# 中文:同时也是普通英文单词的前缀。大小写不敏感的匹配曾把 "any info on
# machine learning courses" 误判成 program_prefix='INFO'(→ 硬过滤
# primary_code LIKE 'INFO %',悄悄隐藏了其余所有课程)。对这些前缀,我们
# 只接受全大写拼写 —— 说 Information Systems 专业的用户会写 "INFO",
# 普通行文则写 "info"。
AMBIGUOUS_PREFIXES: frozenset[str] = frozenset({"INFO", "IE"})

# `re.ASCII` so CJK chars don't act as word chars (same fix we made in
# query_normalizer for the '那aai' case). The {2,5} bound covers the
# longest known prefix (CSYE, BINF, MGSC = 4 chars; STAT = 4; we leave 5
# of headroom).
# 中文:`re.ASCII` 让 CJK 字符不被当作词字符(与我们在 query_normalizer
# 里修复 '那aai' 问题时用的方法相同)。{2,5} 的范围覆盖了已知最长的前缀
# (CSYE、BINF、MGSC 都是 4 个字符;STAT 也是 4 个;留了 5 作为余量)。
_PREFIX_RE = re.compile(
    r"\b(" + "|".join(sorted(KNOWN_PROGRAM_PREFIXES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE | re.ASCII,
)

# Heuristic that signals "user is talking about a program / major". When a
# regex-prefix scan misses but one of these words is present, it's worth
# spending an LLM call to try mapping a free-form program name. When NEITHER
# the prefix NOR these keywords are present, skip extraction entirely.
# 中文:标志"用户在谈论专业/主修"的启发式。当正则前缀扫描没有命中、
# 但出现了这些词之一时,就值得花一次 LLM 调用去尝试映射自由格式的专业
# 名称。当前缀和这些关键词都不存在时,直接跳过整个抽取。
_PROGRAM_KEYWORDS_RE = re.compile(
    r"(?:专业|major|program|主修|课程方向|track|concentration|degree)",
    re.IGNORECASE,
)


def extract_filters_regex(query: str) -> QueryFilters:
    """Pure regex pass — no LLM. Returns a QueryFilters with program_prefix
    set if a known prefix appears as a word in the query, else None.

    Sanitized query: the matched prefix word is removed (case-preserving
    by index removal), and surrounding whitespace is collapsed. This keeps
    the BM25 / vector embeddings focused on the rest of the query.

    中文:纯正则处理 —— 不调用 LLM。当查询中以单词形式出现已知前缀时,
    返回一个 program_prefix 已设置的 QueryFilters;否则为 None。
    净化后的查询:命中的前缀词会被移除(按索引删除,不影响大小写),
    并折叠周围的空白。这样 BM25 / 向量 embedding 就能专注于查询剩下的
    部分。
    """
    if not query or not query.strip():
        return QueryFilters(sanitized_query="")

    match = next(
        (
            m
            for m in _PREFIX_RE.finditer(query)
            if m.group(1).upper() not in AMBIGUOUS_PREFIXES or m.group(1).isupper()
        ),
        None,
    )
    if not match:
        return QueryFilters(sanitized_query=query)

    prefix = match.group(1).upper()
    # Strip the matched prefix from the query for the sanitized form.
    # 中文:从查询中去掉命中的前缀,得到净化后的形式。
    sanitized = (query[: match.start()] + query[match.end():]).strip()
    sanitized = re.sub(r"\s+", " ", sanitized)
    return QueryFilters(program_prefix=prefix, sanitized_query=sanitized)


def extract_filters_adaptive(
    query: str,
    *,
    llm_fn: Callable[[str], dict[str, object]] | None = None,
) -> QueryFilters:
    """Adaptive extraction — fast path first, LLM fallback only when needed.

    Decision tree:
      1. Regex finds an explicit prefix → return that, skip LLM.
      2. No prefix BUT program-keyword present (`专业`, `major`, ...) AND
         `llm_fn` is provided → call the LLM to map the program name.
      3. Otherwise → no filter (passthrough). Saves the LLM call when the
         user's query has no program intent at all.

    `llm_fn(query) -> dict` must return a dict with keys 'program_prefix'
    (str | None) and 'sanitized_query' (str). The dict is fed to
    QueryFilters; Pydantic validates. Caller decides Gemini / Claude / etc.

    中文:自适应抽取 —— 先走快路径,只在需要时才用 LLM 兜底。
    决策树:
      1. 正则找到了显式前缀 → 直接返回,跳过 LLM。
      2. 没有前缀,但出现了专业关键词(`专业`、`major` 等)且提供了
         `llm_fn` → 调用 LLM 来映射专业名称。
      3. 否则 → 不加过滤(透传)。当用户查询完全没有专业意图时,省下
         这次 LLM 调用。
    `llm_fn(query) -> dict` 必须返回一个带有 'program_prefix'
    (str | None) 和 'sanitized_query'(str)两个键的 dict。这个 dict 会
    喂给 QueryFilters,由 Pydantic 校验。调用方自行决定用 Gemini /
    Claude 等。
    """
    regex_result = extract_filters_regex(query)
    if not regex_result.is_empty():
        return regex_result

    # No explicit prefix. Worth an LLM call only if a program keyword is in
    # the query — otherwise the LLM would be guessing in a vacuum.
    # 中文:没有显式前缀。只有查询里出现了专业关键词才值得调用 LLM ——
    # 否则 LLM 只是在真空里瞎猜。
    if llm_fn is None or not _PROGRAM_KEYWORDS_RE.search(query):
        return regex_result  # passthrough (program_prefix=None)
        # 中文:透传(program_prefix=None)。

    try:
        raw = llm_fn(query)
    except Exception:
        # LLM failed — degrade to passthrough rather than blocking the request.
        # Caller log captures the trace; user still gets retrieval.
        # 中文:LLM 调用失败 —— 降级为透传,而不是卡住整个请求。调用方的
        # 日志会记录这次异常;用户依然能拿到检索结果。
        return regex_result

    # Validate via Pydantic; missing/extra fields => fall back to regex result.
    # 中文:交给 Pydantic 校验;字段缺失/多余 => 回退到正则结果。
    try:
        return QueryFilters(**raw)
    except Exception:
        return regex_result


__all__ = [
    "AMBIGUOUS_PREFIXES",
    "KNOWN_PROGRAM_PREFIXES",
    "extract_filters_adaptive",
    "extract_filters_regex",
]
