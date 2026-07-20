"""Follow-up (anaphora) detection for conversational retrieval.

The /chat endpoint is stateless per request; the UI sends the previous
turn's evidence as `context_course_ids`. This module decides whether the
NEW query is a follow-up about those courses ("这门课作业量大吗?",
"what does it cover?") versus a fresh query that should run the normal
alias → program → hybrid pipeline.

/chat 端点每个请求都是无状态的;UI 会把上一轮的证据当作
`context_course_ids` 传回来。本模块判断新查询是在追问这些课程
("这门课作业量大吗?","what does it cover?"),还是应该走正常的
alias → program → hybrid 流水线的全新查询。

Design: cheap deterministic tier first (house style — same philosophy as
the alias tier and the regex Layer-2 filter). A query is a follow-up iff
it contains a referent expression AND carries no course signal of its own
(no course-code-shaped token). An LLM query-rewrite fallback is a known
upgrade path once query_log shows real follow-ups this heuristic misses
(mine for: matched_via in (rejected, hybrid-noise) where the previous
turn had evidence).

设计:先走廉价确定性的一层(项目一贯风格 —— 与别名层、正则 Layer-2
过滤器同样的思路)。当且仅当查询包含指代表达、且自身不携带任何课程
信号(没有形似课程代码的 token)时,才判定为追问。一旦 query_log 显示
这个启发式漏掉了真实的追问案例,引入 LLM 改写查询作为兜底是已知的升级
路径(可以从 matched_via 属于 (rejected, hybrid-noise) 且上一轮有证据的
记录里挖掘这类案例)。

Pure functions, no I/O — mirror query_normalizer's testing story.

纯函数,没有 I/O —— 测试思路与 query_normalizer 一致。
"""

from __future__ import annotations

import re

# Course-code-shaped token = the query names its own course; never treat
# as a follow-up even if a referent word also appears ("AAI 6620 和这门课
# 比怎么样" names a NEW course — let retrieval handle it; history still
# reaches the answer prompt for the comparison).
# 2-4 letters + 3-4 digits, space optional — matches the alias tier's
# tolerance for "cs5800" / "CS 5800" / "AAI6620".
# 中文:形似课程代码的 token = 查询点名了自己的课程;即使同时出现指代词,
# 也绝不当作追问处理("AAI 6620 和这门课比怎么样" 点名的是一门 NEW 课程——
# 交给检索处理即可;对比所需的历史记录仍会传到回答 prompt 里)。
# 2-4 个字母 + 3-4 位数字,空格可选 —— 与别名层对 "cs5800" / "CS 5800" /
# "AAI6620" 的容忍度一致。
_CODE_RE = re.compile(r"[A-Za-z]{2,4}\s?\d{3,4}", re.ASCII)

# Referent expressions that point at the previous turn's course(s).
# Conservative on purpose: bare "它"/"it" appears in compound words and
# idioms less often than 这门课-style noun phrases, but the surrounding
# no-code requirement keeps false positives cheap (worst case: context
# courses get fed to the LLM alongside an answerable query).
# 中文:指向上一轮课程的指代表达。故意保守:光秃秃的 "它"/"it" 出现在
# 复合词和习语里的频率,比 这门课 这类名词短语要低,但周围"无课程代码"
# 的要求让误判的代价很低(最坏情况:上下文课程连同一个本可回答的查询
# 一起被喂给了 LLM)。
_REFERENT_RE = re.compile(
    r"(?:这门课|那门课|这课|该课|这门|此课|这[个两三]课|它|"
    r"上面(?:这|那|的)|刚才(?:这|那|的)|前面(?:这|那|的)|"
    r"\bthis (?:course|class|one)\b|\bthat (?:course|class|one)\b|"
    r"\bthe (?:course|class)\b|\bit\b|\bthem\b|\bthese\b|\bboth\b)",
    re.IGNORECASE,
)


def is_followup_query(query: str) -> bool:
    """True iff `query` references the previous turn's course(s) and names
    no course of its own. Caller must also require non-empty context ids —
    a referent with nothing to refer to is just a vague query for the
    normal pipeline (whose gate will handle it).

    中文:当且仅当 `query` 指代上一轮的课程、且自身不点名任何课程时返回
    True。调用方还必须要求 context ids 非空 —— 有指代词但无所指,只是
    一个交给正常流水线处理的模糊查询(自有其拒答门会处理)。
    """
    if not query or not query.strip():
        return False
    if _CODE_RE.search(query):
        return False
    return bool(_REFERENT_RE.search(query))


__all__ = ["is_followup_query"]
