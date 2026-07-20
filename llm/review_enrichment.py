"""Bridge: RmpProfessorSummary → SourceDocument list for the LLM extractor.

Per PLAN_v2.0 §4 Q2=B, RMP reviews flow into Course.evidence_snippets via the
existing extract_v1 LLM pipeline (rather than a parallel Course-mutating
helper). Each review becomes one `<source id="rmp_review_X" type="rmp_review">`
chunk; the LLM can then cite that id when populating soft fields like
difficulty_score / workload_hours_per_week / controversial_signals, and
schemas.course's model_validator enforces the evidence_snippet ↔ source_id
correspondence (PLAN §3.3 / §2.1).

根据 PLAN_v2.0 §4 Q2=B,RMP 评论通过已有的 extract_v1 LLM 流水线流入
Course.evidence_snippets(而不是另建一条并行的、直接修改 Course 的
辅助路径)。每条评论变成一个 `<source id="rmp_review_X" type="rmp_review">`
片段;LLM 在填写 difficulty_score / workload_hours_per_week /
controversial_signals 这类软字段时可以引用这个 id,而 schemas.course 的
model_validator 会强制校验 evidence_snippet 与 source_id 的对应关系
(PLAN §3.3 / §2.1)。

This module is pure data-shaping — no LLM calls. Caller (e.g. an ingestion
script that wants to enrich a Course with RMP reviews) packages the output
together with the syllabus into a single LLM extraction request.

这个模块只做纯粹的数据整形 —— 不发起 LLM 调用。调用方(比如想用 RMP
评论来丰富某门课程的入库脚本)把这里的输出和教学大纲一起打包进单次
LLM 抽取请求里。
"""

from __future__ import annotations

from typing import Callable

from llm.formatter import SourceDocument, format_sources
from llm.gemini_client import generate_structured
from llm.prompts.extract_v1_1 import build_prompt
from schemas.course import Course
from scrapers.rmp import RmpProfessorSummary, RmpReview

# source_id prefix matches the convention in schemas.course evidence_snippets.
# 中文:source_id 前缀与 schemas.course 的 evidence_snippets 约定保持一致。
RMP_SOURCE_ID_PREFIX = "rmp_review_"
RMP_SOURCE_TYPE = "rmp_review"
CATALOG_SOURCE_TYPE = "catalog"

# LLM-callable shape: accept a prompt string + Course schema, return a Course.
# `generate_structured` matches via partial application; tests pass a mock.
# 中文:LLM 可调用对象的形状:接受一个 prompt 字符串 + Course schema,
# 返回一个 Course。`generate_structured` 通过部分应用来匹配这个形状;
# 测试会传入一个 mock。
LlmFn = Callable[[str, type[Course]], Course]


def _default_llm_fn(prompt: str, schema: type[Course]) -> Course:
    return generate_structured(prompt, schema=schema)


def reviews_to_source_documents(
    summary: RmpProfessorSummary,
) -> list[SourceDocument]:
    """One SourceDocument per RmpReview in the summary.

    Empty list if the professor has no reviews. Skips reviews with empty
    review_id (defensive; _parse_review_node should already drop those).

    The content is a structured plain-text dump rather than JSON — the LLM
    extractor (extract_v1.py) reads each <source> as free-form prose, and
    structured fields here help it ground numeric soft fields.

    中文:summary 里每条 RmpReview 对应一个 SourceDocument。
    教授没有评论时返回空列表。跳过 review_id 为空的评论(防御性的;
    _parse_review_node 理应已经过滤掉这些)。
    content 是结构化的纯文本转储,而不是 JSON —— LLM 抽取器
    (extract_v1.py)把每个 <source> 当自由格式的散文来读,这里的
    结构化字段能帮它为数值型软字段找到依据。
    """
    docs: list[SourceDocument] = []
    for r in summary.reviews:
        if not r.review_id:
            continue
        docs.append(_review_to_source(r, professor_name=summary.name))
    return docs


def _review_to_source(review: RmpReview, *, professor_name: str) -> SourceDocument:
    """Single review → one SourceDocument.

    中文:单条评论 → 一个 SourceDocument。
    """
    header_lines: list[str] = []
    header_lines.append(f"professor: {professor_name}")
    if review.course_code_mentioned:
        header_lines.append(f"course: {review.course_code_mentioned}")
    if review.overall_rating is not None:
        header_lines.append(f"quality_rating: {review.overall_rating}/5")
    if review.difficulty_rating is not None:
        header_lines.append(f"difficulty_rating: {review.difficulty_rating}/5")
    if review.created_date:
        header_lines.append(f"date: {review.created_date}")
    if review.rating_tags:
        header_lines.append(f"tags: {', '.join(review.rating_tags)}")

    metadata = {"professor": professor_name}
    if review.course_code_mentioned:
        metadata["course_code"] = review.course_code_mentioned

    content = "\n".join(header_lines) + "\n---\n" + (review.comment or "")
    return SourceDocument(
        source_id=f"{RMP_SOURCE_ID_PREFIX}{review.review_id}",
        source_type=RMP_SOURCE_TYPE,
        content=content,
        metadata=metadata,
    )


def assemble_sources(
    course: Course,
    raw_text: str | None,
    rmp_summaries: list[RmpProfessorSummary],
) -> list[SourceDocument]:
    """Build the SourceDocument list for an enrichment LLM call.

    Order: catalog/syllabus first (source of truth for hard fields), then
    RMP reviews (which feed soft fields). Empty raw_text → no catalog entry.

    中文:为一次 enrichment LLM 调用构建 SourceDocument 列表。
    顺序:catalog/教学大纲在前(硬字段的真相来源),RMP 评论在后
    (为软字段提供依据)。raw_text 为空 → 不生成 catalog 条目。
    """
    docs: list[SourceDocument] = []
    if raw_text:
        docs.append(
            SourceDocument(
                source_id=f"catalog_{course.course_id}",
                source_type=CATALOG_SOURCE_TYPE,
                content=raw_text,
                metadata={"course_code": course.primary_code},
            )
        )
    for summary in rmp_summaries:
        docs.extend(reviews_to_source_documents(summary))
    return docs


# Fields the LLM extraction is ALLOWED to write. Everything else keeps the
# incoming course's value. Rationale (data-quality review, 2026-06): the
# extraction prompt only sees raw_text (description) + reviews, so hard
# fields the catalog parsed separately (credits from the title line,
# prereq codes from anchor tags) come back null from the LLM — and the old
# return-the-LLM-object-wholesale behavior CLOBBERED them on upsert.
# CS 5800 lost its credits exactly this way, which then broke the
# credits=4 filter on the flagship demo course.
# 中文:LLM 抽取被允许写入的字段。其余字段一律保留传入 course 的原值。
# 依据(2026-06 数据质量复盘):抽取 prompt 只看得到 raw_text(描述)+
# 评论,所以目录单独解析出来的硬字段(标题行里的学分、锚标签里的先修
# 代码)会从 LLM 那边拿回 null —— 而旧版"整体返回 LLM 对象"的做法在
# upsert 时把这些字段直接覆盖清空了。CS 5800 正是这样丢了学分信息,
# 进而弄坏了旗舰演示课程上的 credits=4 过滤器。
ENRICHMENT_FIELDS: tuple[str, ...] = (
    "professor",
    "workload_hours_per_week",
    "difficulty_score",
    "grading_components",
    "topics_covered",
    "skill_tags",
    "career_relevance",
    "controversial_signals",
    "ai_policy",
    "evidence_snippets",
    "extraction_confidence",
    "source_review_ids",
)


def enrich_course(
    course: Course,
    raw_text: str | None,
    rmp_summaries: list[RmpProfessorSummary],
    *,
    llm_fn: LlmFn = _default_llm_fn,
) -> Course:
    """Run the LLM extraction pipeline on (course, syllabus, RMP reviews)
    and MERGE the soft fields onto the incoming Course.

    Merge, not replace: only ENRICHMENT_FIELDS are taken from the LLM
    output (and only when non-empty) — hard catalog facts (credits, term,
    prereqs, cross-listings, code/name) always keep the incoming values,
    because the LLM never saw the sources they came from.

    Tests pass `llm_fn` to bypass the live Gemini call. Production uses
    the default which delegates to `gemini_client.generate_structured`.

    Raises whatever GeminiError / ValidationError the LLM call surfaces —
    caller decides whether to retry / log / fail loud.

    中文:在 (course, 教学大纲, RMP 评论) 上跑 LLM 抽取流水线,并把软
    字段合并回传入的 Course。
    是合并,不是替换:只从 LLM 输出里取 ENRICHMENT_FIELDS 里的字段(且
    仅当非空时才取)—— 硬性的目录事实(学分、学期、先修课、跨列课程、
    代码/名称)永远保留传入值,因为 LLM 从未见过这些字段的原始来源。
    测试会传入 `llm_fn` 来绕开真实的 Gemini 调用。生产环境用默认值,
    委托给 `gemini_client.generate_structured`。
    LLM 调用抛出的任何 GeminiError / ValidationError 都会原样抛出 ——
    由调用方决定是重试、记录日志,还是直接失败。
    """
    docs = assemble_sources(course, raw_text, rmp_summaries)
    sources_xml = format_sources(docs)
    prompt = build_prompt(sources_xml)

    extracted = llm_fn(prompt, Course)

    updates: dict[str, object] = {}
    for field in ENRICHMENT_FIELDS:
        value = getattr(extracted, field)
        # None / empty list = the LLM found nothing in its sources; keep
        # whatever the course already had rather than erasing it.
        # 中文:None / 空列表 = LLM 在其来源里什么也没找到;保留 course
        # 已有的值,而不是把它清空。
        if value is None or value == []:
            continue
        updates[field] = value
    # model_copy(update=...) skips validators; re-validate so the
    # soft-field-requires-evidence invariant still holds on the merge.
    # 中文:model_copy(update=...) 会跳过校验器;这里重新校验,确保
    # "软字段必须有证据支撑"这条不变量在合并后依然成立。
    return Course.model_validate(
        {**course.model_dump(), **updates},
    )


__all__ = [
    "CATALOG_SOURCE_TYPE",
    "ENRICHMENT_FIELDS",
    "LlmFn",
    "RMP_SOURCE_ID_PREFIX",
    "RMP_SOURCE_TYPE",
    "assemble_sources",
    "enrich_course",
    "reviews_to_source_documents",
]
