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

`resolve_course_ref` is the deep-link (`?course=`) sibling of the query
path: same alias tier, but the input is a SHARED REFERENCE rather than a
sentence, so it tries the internal course_id first and undoes the
separator mangling a URL inflicts on a code.

`resolve_course_ref` 是查询路径在深链(`?course=`)场景下的兄弟函数:
用的是同一套别名层,但输入是一个被分享出去的引用而非一句话,因此它
先试内部 course_id,并还原 URL 对课程代码造成的分隔符改写。
"""

from __future__ import annotations

import re

from db.alias_repository import AliasRepository
from db.repository import CourseRepository
from rag.profiling import profiled

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

# Separators a URL leaves where a course code has a space. '+' is the
# form-encoded space; '-' and '_' are what a human types when hand-writing a
# link. Undone before the alias tier sees the ref (v_course_lookup stores
# the canonical 'CS 5800', so 'CS-5800' would miss).
# 中文:URL 里代替课程代码中空格的分隔符。'+' 是表单编码的空格;'-' 和 '_'
# 是人手写链接时的习惯写法。在别名层看到这个 ref 之前先还原它们
# (v_course_lookup 存的是规范形式 'CS 5800',所以 'CS-5800' 会查不到)。
_REF_SEPARATOR_RE = re.compile(r"[-_+]+")

# "courses like CS 5800" / "和 CS 5800 类似的课": the code is an ANCHOR for
# OTHER courses, not the course being asked about. Used to stop an explicit
# filter that excludes the anchor from turning such a question into an empty
# answer (the retrieval routes fall back to hybrid instead).
# 中文:"courses like CS 5800" / "和 CS 5800 类似的课":这里的课号是寻找
# 其他课程的锚点,而不是被询问的那门课。用来避免"显式筛选恰好排除了锚点课"
# 时把这类问题变成空结果(检索路由会改为回退到 hybrid)。
_ALTERNATIVES_RE = re.compile(
    r"\blike\b|\bsimilar\b|\balternatives?\b|\binstead of\b|\bbesides\b|\bother than\b|\bexcept\b|"
    r"类似|相似|相近|差不多|替代|代替|平替|除了|别的|其他|其它|同类",
    re.IGNORECASE | re.ASCII,
)


def asks_for_alternatives(query: str) -> bool:
    """True when a mentioned course is an anchor for OTHER courses.
    中文:提到的课程是用来找"其他课程"的锚点时返回 True。"""
    return bool(_ALTERNATIVES_RE.search(query or ""))


# Deep-link refs are codes/slang, not prose. Longer than this and it's junk
# (or someone probing) — reject before touching the DB.
# 中文:深链 ref 是代码或俗称,不是散文。超过这个长度就是垃圾输入
# (或有人在探测)—— 碰数据库之前直接拒掉。
MAX_COURSE_REF_LEN = 64


@profiled('alias_resolution')
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


def resolve_course_ref(
    ref: str,
    *,
    alias_repo: AliasRepository,
    course_repo: CourseRepository,
) -> list[str]:
    """Resolve a deep-link `?course=` reference to course_ids.

    Two tiers, most-specific first:
      0. The ref IS an internal course_id ('neu-cs-5800') — someone copied
         it out of an API response or a log. Catalog ids are lowercase, so
         a ref that only differs in case still lands.
      1. The alias tier, same v_course_lookup the query path uses. Handles
         'CS-5800' / 'CS_5800' / 'cs5800' / 'CS 5800' via separator
         normalization, and slang ('Algo') via the whole-query candidate.

    Returns [] for junk, over-length, and never-matched refs — a bad deep
    link is an ordinary outcome the caller renders as a notice, not an
    error. Multiple ids come back as a list (a ref can be ambiguous, e.g.
    a slang term shared by two cross-listed courses); the caller decides
    whether to auto-pick the first or disambiguate.

    中文:把深链 `?course=` 的引用解析为 course_id。

    两层,从最具体开始:
      0. ref 本身就是内部 course_id('neu-cs-5800')—— 有人从 API 响应或
         日志里复制出来的。目录里的 id 都是小写,所以只是大小写不同的
         ref 依然能命中。
      1. 别名层,与查询路径用的是同一个 v_course_lookup。通过分隔符归一化
         覆盖 'CS-5800' / 'CS_5800' / 'cs5800' / 'CS 5800',通过整串候选
         覆盖俗称('Algo')。

    垃圾输入、超长、以及查无此项的 ref 都返回 [] —— 一条失效的深链是很
    普通的结果,调用方渲染成一句提示即可,不是错误。命中多个 id 时按列表
    返回(ref 可能有歧义,例如两门交叉列课共用的俗称);由调用方决定是
    自动选第一个还是让用户消歧。
    """
    cleaned = (ref or "").strip()
    if not cleaned or len(cleaned) > MAX_COURSE_REF_LEN:
        return []

    # Tier 0 — raw internal id.
    # 中文:第 0 层 —— 原始内部 id。
    for candidate in (cleaned, cleaned.lower()):
        if course_repo.exists(candidate):
            return [candidate]

    # Tier 1 — alias tier. The de-separated form is tried first; the raw
    # form is a fallback for aliases that legitimately contain a hyphen.
    # 中文:第 1 层 —— 别名层。先试去分隔符的形式;原始形式作为兜底,
    # 用于那些本身就含连字符的别名。
    for candidate in _ref_candidates(cleaned):
        ids = normalize_query_to_course_ids(candidate, alias_repo=alias_repo)
        if ids:
            return ids
    return []


def _ref_candidates(cleaned: str) -> list[str]:
    """Ordered alias-tier probes for a deep-link ref (de-separated first).
    中文:深链 ref 在别名层的候选探测串(去分隔符的形式排在前面)。"""
    spaced = _REF_SEPARATOR_RE.sub(" ", cleaned).strip()
    return [spaced] if spaced == cleaned else [spaced, cleaned]


__all__ = [
    "MAX_COURSE_REF_LEN",
    "MAX_WHOLE_QUERY_LEN",
    "asks_for_alternatives",
    "normalize_query_to_course_ids",
    "resolve_course_ref",
]
