"""Render the same explicit evidence and gaps used by the answer prompt.

中文：与回答共用来源与缺失字段；检索分数不表示事实可信度。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re

from pydantic import ValidationError

from rag.answer_evidence import source_kind
from schemas.answer_evidence import OFFICIAL_CATALOG_URL, CatalogSnapshot

SOURCE_KIND_LABELS = {
    "rmp_review": "RateMyProfessors 教师评价", "reddit": "Reddit 讨论", "syllabus": "课程大纲",
    "synthetic": "合成测试数据", "catalog_derived": "抽取时用的课程文本", "other": "其他来源",
}
FIELD_LABELS = {
    "catalog_description": "官方描述", "credits": "学分", "term": "开课学期", "delivery_mode": "授课方式",
    "professor": "教师", "prereqs": "结构化先修信息", "topics_covered": "结构化主题",
    "skill_tags": "技能标签", "workload_hours_per_week": "每周工作量", "difficulty_score": "难度",
    "grading_components": "考核构成", "career_relevance": "职业方向",
}
WARNING_LABELS = {
    "catalog_source_unavailable": "未附可追溯的目录快照，不能将检索文本当作官方描述。",
    "catalog_retrieval_date_unknown": "目录抓取日期未记录；导入时间不是抓取时间，也不证明当前开课。",
    "extracted_evidence_not_official_facts": "软字段是来源支持的抽取/评价，不是官方事实；抽取置信度不等于事实概率。",
    "topics_source_unavailable": "结构化主题未附来源，需核实。",
    "prerequisite_logic_unavailable": "先修代码未保留 AND/OR 语义，不能据此判断所有/任一必需。",
    "program_seed_unverified": "培养方案关系来自未核验 seed，不是正式 Plan of Study 或选课资格保证。",
    "catalog_metadata_conflict": "目录快照与课程记录的学分不一致，需向官方核实，不能静默合并。",
    "field_evidence_value_conflict": "数值估计与证据支持值不一致，需核验，不能当作已确定事实。",
    "synthetic_record_not_real_course": "此记录为合成测试数据，不是实际课程推荐。",
}
# Per-answer retrieval notices from /chat meta. Only KNOWN codes render;
# anything else is dropped (never echoed as markdown).
# 中文：/chat meta 里的回答级检索提示码。只渲染已知代码；其余一律丢弃
# （绝不作为 markdown 原样回显）。
RETRIEVAL_NOTICE_LABELS = {
    "program_schedule_unverified": (
        "该项目已有版本化培养方案规则，但没有经过核验的学期安排；以上只是检索到的相关课程，"
        "不是官方的第一学期/基础课方案。具体规则请到「培养方案」页查看。"
    ),
}


def render_retrieval_notices(st, notices) -> None:
    if not isinstance(notices, list):
        return
    for code in notices:
        if code in RETRIEVAL_NOTICE_LABELS:
            st.caption("ℹ️ " + RETRIEVAL_NOTICE_LABELS[code])


COMPACT_WARNINGS = {
    "catalog_metadata_conflict", "field_evidence_value_conflict", "program_seed_unverified",
    "synthetic_record_not_real_course", "prerequisite_logic_unavailable",
    "extracted_evidence_not_official_facts",
}


def _catalog_snapshot(evidence: dict) -> CatalogSnapshot | None:
    try:
        return CatalogSnapshot.model_validate(evidence.get("catalog"))
    except ValidationError:
        return None  # An old/corrupt history entry must not crash or produce a link.


def source_summary(source_ids: list[str]) -> str:
    """'RateMyProfessors 教师评价 50 条' instead of fifty opaque IDs; a repeated ID counts once.
    中文：按来源类型汇总条数，重复的 ID 只算一次。"""
    counts = Counter(source_kind(source) for source in dict.fromkeys(str(source) for source in source_ids))
    return "、".join(f"{SOURCE_KIND_LABELS[kind]} {count} 条" for kind, count in counts.most_common())


def snapshot_digest(snapshot_id: str) -> str | None:
    """The 64-hex digest of a well-formed 'catalog:<sha256>' ID; None for anything else."""
    match = re.fullmatch(r"catalog:([0-9a-f]{64})", snapshot_id)
    return match.group(1) if match else None


def _when(value: datetime) -> str:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return value.strftime("%Y-%m-%d %H:%M")


# Model answers are untrusted Markdown (catalog descriptions and review quotes reach the
# prompt). answer_markdown() keeps only links whose target is an official catalog department
# page. Any other inline-link destination is dropped (the label stays), images become links,
# reference definitions are disabled, and other autolinks / bare URLs lose their scheme so no
# Markdown rule can make them clickable. Code spans get the same treatment on purpose: guessing
# where CommonMark puts code boundaries is how filters get bypassed, and a scheme-less URL in
# code is merely less exact. An email address may still render as a mail link (it opens a
# mail client, not a web page).
# 中文：模型回答是不可信的 Markdown（目录描述与评价引文都会进提示词）。只保留指向官方目录
# 院系页的链接；其余行内链接去掉目标（保留文字），图片改为链接，引用式定义失效，其余自动
# 链接和裸 URL 去掉协议头，任何 Markdown 规则都无法再让它们可点。代码片段同样处理，这是
# 有意的：去猜 CommonMark 的代码边界正是过滤被绕过的常见原因，代码里的 URL 少了协议头只是
# 不够精确。邮箱地址仍可能显示成邮件链接（只会打开邮件客户端，不会打开网页）。
# \x00 marks placeholders, so no pattern below may match across one.
_DESTINATION = re.compile(
    r"\]\(\s*(<[^>\n\x00]*>|[^)\s\x00]*)(?:\s+(?:\"[^\"\n\x00]*\"|'[^'\n\x00]*'|\([^)\n\x00]*\)))?\s*\)")
_AUTOLINK = re.compile(r"<([A-Za-z][A-Za-z0-9+.\-]{1,31}:[^<>\s\x00]*)>")
_BARE_URL = re.compile(r"(?i:https?://|www\.)[^\s<>()\[\]`\"'\x00]+")
_SCHEME_OR_WWW = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.\-]*:/*|www\.)", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?。，；：！？、）」』》】”’"


def _inert(url: str) -> str:
    # One prefix per call; the fixed-point loop below handles "https://https://x" and "www.https://x".
    return _SCHEME_OR_WWW.sub("", url, count=1)


def answer_markdown(text: str) -> str:
    kept: list[str] = []

    def keep(fragment: str) -> str:
        kept.append(fragment)
        return f"\x00{len(kept) - 1}\x00"

    def autolink(match: re.Match[str]) -> str:
        url = match.group(1)
        return keep(f"<{url}>") if OFFICIAL_CATALOG_URL.fullmatch(url) else _inert(url)

    def bare(match: re.Match[str]) -> str:
        url = match.group(0)
        core = url.rstrip(_TRAILING_PUNCTUATION)
        return (keep(f"<{core}>") if OFFICIAL_CATALOG_URL.fullmatch(core) else _inert(core)) + url[len(core):]

    text = text.replace("\x00", "")
    # Repeat to a fixed point: removing one construct can splice its neighbours into a new one
    # ("[a](x)(//evil)" -> "[a](//evil)"). Each pass only shortens text or swaps a URL for a
    # placeholder, so this terminates. An allowed URL is a placeholder by the time
    # _DESTINATION runs, which leaves "[label](<allowed>)" intact and drops every other target.
    while True:
        before = text
        text = text.replace("![", "[")  # An image would fetch its URL on render.
        text = _AUTOLINK.sub(autolink, text)
        text = _BARE_URL.sub(bare, text)
        text = _DESTINATION.sub("]", text)
        if text == before:
            break
    text = text.replace("]:", "]\\:")  # "\:" renders as ":" but can never start a definition.
    # No kept fragment contains a placeholder, so a single restore pass suffices.
    return re.sub("\x00(\\d+)\x00", lambda match: kept[int(match.group(1))], text)


def render_streamed_answer(st, chunks) -> str:
    """Live counterpart of answer_markdown(): each partial render is filtered as a whole, so a
    link split across tokens is never shown raw. Returns the raw text for chat history.
    中文：流式输出时每次都对已到达的全文过滤，跨 token 的链接也不会以原样出现；返回原文存历史。"""
    placeholder = st.empty()
    text = ""
    for chunk in chunks:
        text += chunk
        placeholder.markdown(answer_markdown(text))
    return text


def evidence_summary(evidence: dict, *, missing_limit: int | None = None) -> list[str]:
    lines = []
    catalog = _catalog_snapshot(evidence)
    if catalog:
        lines.append("来源：已存目录快照（非实时核验）")
    else:
        lines.append("来源：未附可追溯目录快照")
    missing = [FIELD_LABELS.get(field, field) for field in evidence.get("missing_fields", [])]
    if missing:
        visible = missing if missing_limit is None else missing[:missing_limit]
        remainder = len(missing) - len(visible)
        suffix = f"等 {len(missing)} 项（详情查看全部）" if remainder else ""
        lines.append("缺失：" + "、".join(visible) + suffix + "；缺失不等于零/简单/无要求。")
    return lines


def render_answer_evidence(st, evidence: dict | None, *, detailed: bool = False) -> None:
    if evidence is None:
        return  # Backward-compatible history entries may predate this contract.
    for line in evidence_summary(evidence, missing_limit=None if detailed else 5):
        st.caption(line)
    for warning in evidence.get("warnings", []):
        if detailed or warning in COMPACT_WARNINGS:
            st.caption(WARNING_LABELS.get(warning, warning))
    if not detailed:
        return
    snapshot = _catalog_snapshot(evidence)
    if snapshot:
        st.markdown(f"[官方目录来源]({snapshot.catalog_url}) · 非实时核验")
        if snapshot.description:
            st.text(snapshot.description)
        # A 64-hex digest is unreadable: show its head, keep the whole ID one hover away.
        # Captions and tooltips render Markdown, so a malformed ID is never echoed.
        digest = snapshot_digest(snapshot.snapshot_id)
        st.caption(f"快照：{digest[:12] + '…' if digest else '格式异常'} · 导入：{_when(snapshot.imported_at)}",
                   help=f"完整快照 ID：{snapshot.snapshot_id}" if digest else None)
        st.caption(f"抓取：{_when(snapshot.retrieved_at) if snapshot.retrieved_at else '未记录'}")
    elif evidence.get("catalog"):
        st.caption("目录快照格式或来源校验未通过；未显示链接。")
    sources = list(dict.fromkeys(str(source) for source in evidence.get("source_review_ids") or []))
    if sources:
        st.caption(f"记录来源（非全文核验）：{source_summary(sources)}")
        # Write into the expander itself, so the IDs stay folded even when `st` is a container.
        # 中文：直接写进折叠区本身；即使传进来的 `st` 是某个容器，ID 也仍在折叠区里。
        st.expander(f"来源 ID（{len(sources)}）").text("、".join(sources))


def render_field_evidence(st, snippets: list[dict]) -> None:
    """Render supplied quotes/IDs as text, not user-controlled Markdown links."""
    for item in snippets:
        field = FIELD_LABELS.get(item["field"], item["field"])
        kind = SOURCE_KIND_LABELS[source_kind(str(item["source_id"]))]
        st.caption(f"{field} · 抽取置信度 {item['confidence']:.2f}（不是事实概率）")
        st.text(f"支持值：{item['value']}\n来源：{kind} · {item['source_id']}\n引文：{item['quote']}")
