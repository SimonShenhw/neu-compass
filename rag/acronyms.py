"""Corpus-derived acronym expansion at query time (ADR-0020 §3).

The failure this fixes: "CRM 认知偏差 团队决策" means Crisis Resource
Management (the healthcare-teamwork course defines it that way), but
embeddings read CRM as Customer Relationship Management — the dominant
web sense. The corpus itself disambiguates: the glossary is mined from
course texts by scripts/generate_doc_expansion.py + aggregated by
scripts/apply_doc_expansion.py, so an acronym only ever expands to senses
that actually exist in the catalog.

这个模块修复的问题:"CRM 认知偏差 团队决策" 里的 CRM 指的是 Crisis
Resource Management(危机资源管理 —— 医疗团队协作课程正是这样定义的),
但 embedding 会把 CRM 读成 Customer Relationship Management(客户关系
管理)—— 这是网络上占主导的含义。语料本身就能消歧:词汇表由
scripts/generate_doc_expansion.py 从课程文本中挖掘、再经
scripts/apply_doc_expansion.py 聚合而成,所以一个缩写只会展开成目录里
真实存在的含义。

Multi-sense handling: append ALL in-corpus senses to the query (union
retrieval); the cross-encoder reranker sees the surrounding query context
("认知偏差 团队决策") and ranks the right sense's course up. No LLM call,
no sense-picking error possible at this layer.

多义处理:把语料内的所有含义都追加到查询里(并集检索);交叉编码器
重排器会看到查询周围的上下文("认知偏差 团队决策"),把正确含义对应的
课程排上去。这一层不需要 LLM 调用,也不可能出现选错含义的问题。

Wiring: HybridRetriever applies `expand_query` to its retrieval legs only
— the reranker and the rejection gate still see the ORIGINAL query, so
expansion can only ADD recall, never change what relevance is judged
against. Disabled cleanly when the glossary file is absent.

接入方式:HybridRetriever 只对它的检索两路应用 `expand_query` —— 重排器
和拒答门看到的仍是原始查询,所以扩写只能增加召回,绝不会改变相关性
判断的依据。词汇表文件缺失时会干净地自动关闭这个功能。
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from rag.hybrid import STOPWORDS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GLOSSARY_PATH = PROJECT_ROOT / "data" / "acronym_glossary.json"

# Tokens that pass the shape test but are ordinary words in course-search
# queries — expanding them would inject noise. STOPWORDS already covers
# the function words ("is", "it", ...).
# 中文:符合"缩写形状"测试、但在选课查询里其实是普通词的 token ——
# 展开它们只会引入噪声。STOPWORDS 已经覆盖了虚词("is"、"it" 等)。
_DENYLIST = frozenset({
    "info", "data", "lab", "labs", "intro", "core", "exam", "fall", "gpa",
    "online", "hybrid", "course", "class", "unit", "term",
})

_ACRO_TOKEN_RE = re.compile(r"\b[A-Za-z]{2,6}\b", re.ASCII)

MAX_SENSES_PER_ACRONYM = 3  # query-bloat guard; apply script also caps
# 中文:防止查询膨胀的上限;apply 脚本那边也有同样的上限。


@functools.lru_cache(maxsize=1)
def load_glossary(path: str | None = None) -> dict[str, tuple[str, ...]]:
    """Load {ACRONYM: (sense, ...)} from JSON. Missing/corrupt file → {}
    (feature silently off). lru_cache: one disk read per process.

    中文:从 JSON 加载 {缩写: (含义, ...)}。文件缺失/损坏 → 返回 {}
    (功能静默关闭)。lru_cache:每个进程只读一次磁盘。
    """
    p = Path(path) if path else DEFAULT_GLOSSARY_PATH
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        # Per-entry type check: a structurally-valid JSON with a non-string
        # sense (nested list, number) would otherwise pass load and crash
        # expand_query's sense.lower() on EVERY non-alias request — one bad
        # glossary regeneration = total search outage.
        # 中文:逐条做类型检查:结构上合法的 JSON,如果某个含义不是字符串
        # (嵌套列表、数字),不检查的话就能蒙混过加载,却会在每一个非别名
        # 请求上让 expand_query 的 sense.lower() 崩溃 —— 一次词汇表生成
        # 出错就等于整个搜索服务宕机。
        return {
            k.upper(): tuple(v)[:MAX_SENSES_PER_ACRONYM]
            for k, v in raw.items()
            if isinstance(v, list) and v
            and all(isinstance(s, str) for s in v)
        }
    except Exception:  # noqa: BLE001 — bad glossary must not kill the API
        # 中文:词汇表损坏也不能拖垮 API。
        return {}


def expand_query(
    query: str,
    *,
    glossary: dict[str, tuple[str, ...]] | None = None,
) -> str:
    """Append in-corpus long forms for acronym-shaped tokens in the query.

    Lookup is case-insensitive for tokens of length ≥3; 2-letter tokens
    must be uppercase in the query (lowercase "is"/"ml" prose ambiguity —
    same conservatism as the Layer-2 AMBIGUOUS_PREFIXES rule). Senses
    already present verbatim in the query are skipped.

    中文:为查询中形似缩写的 token 追加语料内的全称写法。
    长度 ≥3 的 token 大小写不敏感;2 字母 token 必须在查询里就是大写
    (小写 "is"/"ml" 在散文中有歧义 —— 与 Layer-2 的 AMBIGUOUS_PREFIXES
    规则同样保守)。查询里已经逐字出现过的含义会被跳过。
    """
    g = load_glossary() if glossary is None else glossary
    if not g:
        return query

    additions: list[str] = []
    lowered = query.lower()
    for m in _ACRO_TOKEN_RE.finditer(query):
        tok = m.group(0)
        if tok.lower() in STOPWORDS or tok.lower() in _DENYLIST:
            continue
        if len(tok) == 2 and not tok.isupper():
            continue
        for sense in g.get(tok.upper(), ()):
            if sense.lower() not in lowered:
                additions.append(sense)

    if not additions:
        return query
    # dict.fromkeys: dedupe, keep first-seen order (stable for tests/logs).
    # 中文:dict.fromkeys 用于去重,同时保留首次出现的顺序(便于测试/日志)。
    return query + " " + " ".join(dict.fromkeys(additions))


__all__ = [
    "DEFAULT_GLOSSARY_PATH",
    "MAX_SENSES_PER_ACRONYM",
    "expand_query",
    "load_glossary",
]
