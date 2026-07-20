"""Query -> [course_id] via alias resolution.

Used by the API layer (Week 6) BEFORE semantic search. If the user types
'5800' or 'Applied AI', we resolve directly via v_course_lookup and can
return that course without LLM/vector cost. Falls through to retriever
when no alias match.

由 API 层(第 6 周)在语义搜索之前调用。如果用户输入 '5800' 或
'Applied AI',我们直接通过 v_course_lookup 解析,不花 LLM/向量的开销
就能返回那门课。没有别名命中时,落回到 retriever。

Three extraction patterns:
  1. Full code 'CS 5800' / 'AAI6600' (regex normalized to canonical)
  2. Bare 4-digit '5800' (slang for course number)
  3. Whole-query exact match (for 'Applied AI', 'Algo', '应用 AI')

三种提取模式:
  1. 完整代码 'CS 5800' / 'AAI6600'(正则归一化为规范形式)
  2. 裸 4 位数字 '5800'(课程号的口语说法)
  3. 整个查询精确匹配(用于 'Applied AI'、'Algo'、'应用 AI')
"""

from __future__ import annotations

import re

from db.alias_repository import AliasRepository

# Same as schemas.course COURSE_CODE_PATTERN but case-insensitive + free in text.
# `re.ASCII` makes \b respect ASCII word boundaries only — without it Python 3
# treats CJK characters as word chars, so '那aai' has no boundary between '那'
# and 'a' and the regex misses 'aai 6640' inside Chinese-mixed NL queries like
# '那aai 6640这门课能给我说说吗'. (Bilingual NEU users hit this constantly.)
# 中文:与 schemas.course 的 COURSE_CODE_PATTERN 相同,但大小写不敏感、
# 且可以出现在文本任意位置。`re.ASCII` 让 \b 只按 ASCII 词边界处理 ——
# 不加这个,Python 3 会把 CJK 字符也当作词字符,于是 '那aai' 里 '那' 和
# 'a' 之间没有边界,导致正则在 '那aai 6640这门课能给我说说吗' 这类中英
# 混排的自然语言查询里漏掉 'aai 6640'。(双语 NEU 用户经常踩到这个坑。)
_FULL_CODE_RE = re.compile(r"\b([A-Za-z]{2,4})\s?(\d{4}[A-Za-z]?)\b", re.ASCII)
_NUMERIC_CODE_RE = re.compile(r"\b(\d{4})\b", re.ASCII)

# Cap candidate-text length so we don't try to resolve "the entire essay" against aliases.
# 中文:限制候选文本长度,避免把"整篇作文"都拿去和别名做匹配。
MAX_WHOLE_QUERY_LEN = 30


def normalize_query_to_course_ids(
    query: str,
    *,
    alias_repo: AliasRepository,
) -> list[str]:
    """Extract course mentions from a user query and resolve via aliases.

    Returns deduplicated course_ids in the order they were resolved (stable
    enough for tests; production callers should treat as a set).

    中文:从用户查询里提取课程提及,再通过别名解析。
    按解析顺序返回去重后的 course_id 列表(顺序足够稳定、可用于测试;
    生产环境的调用方应当把它当作集合来看待)。
    """
    if not query or not query.strip():
        return []

    candidates = _extract_candidates(query)

    seen: set[str] = set()
    result: list[str] = []
    for cand in candidates:
        for cid in alias_repo.resolve(cand):
            if cid not in seen:
                seen.add(cid)
                result.append(cid)
    return result


def _extract_candidates(query: str) -> list[str]:
    """Return ordered candidate strings worth probing against the alias view.

    Order matters: more specific (full code) before less (bare number) before
    least (whole query). Caller's resolve() is case-insensitive so we don't
    bother lowercasing here.

    中文:按顺序返回值得拿去别名视图里试探的候选字符串。
    顺序有讲究:最具体的(完整代码)在前,其次是裸数字,最后才是整个
    查询。调用方的 resolve() 大小写不敏感,所以这里不用费心转小写。
    """
    candidates: list[str] = []
    seen: set[str] = set()

    # 1. Full course code patterns
    # 中文:1. 完整课程代码模式
    for m in _FULL_CODE_RE.finditer(query):
        normalized = f"{m.group(1).upper()} {m.group(2).upper()}"
        if normalized not in seen:
            seen.add(normalized)
            candidates.append(normalized)

    # 2. Bare 4-digit numbers (skip if already covered by full-code match)
    # 中文:2. 裸 4 位数字(如果已被完整代码匹配覆盖,则跳过)
    for m in _NUMERIC_CODE_RE.finditer(query):
        num = m.group(0)
        # Skip if this number was already part of a full-code match
        # 中文:如果这个数字已经是某个完整代码匹配的一部分,就跳过
        if any(num in c for c in candidates):
            continue
        if num not in seen:
            seen.add(num)
            candidates.append(num)

    # 3. Whole query (after stripping). Effective for short queries like
    #    "应用 AI", "Algo", "Hema's AI class" that don't match the regexes.
    # 中文:3. 整个查询(去除首尾空白后)。对不匹配上述正则的短查询
    #    (如 "应用 AI"、"Algo"、"Hema's AI class")有效。
    stripped = query.strip()
    if 1 < len(stripped) <= MAX_WHOLE_QUERY_LEN and stripped not in seen:
        candidates.append(stripped)

    return candidates


__all__ = ["MAX_WHOLE_QUERY_LEN", "normalize_query_to_course_ids"]
