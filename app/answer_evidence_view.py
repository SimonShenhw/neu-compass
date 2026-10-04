"""Render the same explicit evidence and gaps used by the answer prompt.

中文：与回答共用来源与缺失字段；检索分数不表示事实可信度。
"""

from __future__ import annotations

from pydantic import ValidationError

from schemas.answer_evidence import CatalogSnapshot

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
        st.caption(f"快照：{snapshot.snapshot_id} · 导入：{snapshot.imported_at.isoformat()}")
        st.caption(f"抓取：{snapshot.retrieved_at.isoformat() if snapshot.retrieved_at else '未记录'}")
    elif evidence.get("catalog"):
        st.caption("目录快照格式或来源校验未通过；未显示链接。")
    if evidence.get("source_review_ids"):
        st.caption("记录来源 ID（非全文核验）：")
        st.text("、".join(evidence["source_review_ids"]))


def render_field_evidence(st, snippets: list[dict]) -> None:
    """Render supplied quotes/IDs as text, not user-controlled Markdown links."""
    for item in snippets:
        field = FIELD_LABELS.get(item["field"], item["field"])
        st.caption(f"{field} · 抽取置信度 {item['confidence']:.2f}（不是事实概率）")
        st.text(f"支持值：{item['value']}\n来源 ID：{item['source_id']}\n引文：{item['quote']}")
