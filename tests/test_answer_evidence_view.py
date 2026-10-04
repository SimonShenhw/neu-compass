"""Source/gap UI contracts without a browser or Streamlit server."""

from __future__ import annotations

import pytest

from app.answer_evidence_view import (
    FIELD_LABELS, WARNING_LABELS, evidence_summary, render_answer_evidence, render_field_evidence,
)
from app.streamlit_app import _format_evidence, _render_evidence_block
from db.catalog_source_repository import CatalogSourceRepository
from rag.answer_evidence import course_answer_evidence
from schemas.course import Course
from scrapers.neu_catalog import CatalogEntry


class FakeSurface:
    def __init__(self):
        self.captions = []
        self.texts = []
        self.markdowns = []
        self.children = []
        self.session_state = {}

    def caption(self, value):
        self.captions.append(value)

    def text(self, value):
        self.texts.append(value)

    def markdown(self, value, **kwargs):
        self.markdowns.append(value)

    def columns(self, sizes):
        pair = [FakeSurface() for _ in sizes]
        self.children.extend(pair)
        return pair

    def button(self, *args, **kwargs):
        return False


def evidence(*, catalog=False):
    record = Course(course_id="cs-5800", primary_code="CS 5800", primary_name="Algorithms")
    snapshot = CatalogSourceRepository.snapshot(CatalogEntry(
        course_code=record.primary_code, course_name=record.primary_name,
        description="Recorded description, not a live semester offering.",
        catalog_url="https://catalog.northeastern.edu/course-descriptions/cs/",
    )) if catalog else None
    return course_answer_evidence(record, snapshot).model_dump(mode="json")


def test_absent_source_and_missing_fields_are_explicit():
    lines = evidence_summary(evidence())
    assert "未附可追溯" in lines[0]
    assert "每周工作量" in lines[1] and "难度" in lines[1]
    assert "缺失不等于零/简单/无要求" in lines[1]


def test_compact_cards_bound_the_gap_list_but_details_keep_every_field():
    data = evidence()
    compact, detail = FakeSurface(), FakeSurface()
    render_answer_evidence(compact, data)
    render_answer_evidence(detail, data, detailed=True)
    assert "详情查看全部" in compact.captions[1]
    assert FIELD_LABELS[data["missing_fields"][-1]] not in compact.captions[1]
    assert all(FIELD_LABELS[field] in detail.captions[1] for field in data["missing_fields"])


def test_compact_cards_do_not_hide_seed_conflict_or_synthetic_warnings():
    data = evidence()
    data["warnings"] = ["program_seed_unverified", "catalog_metadata_conflict", "field_evidence_value_conflict",
                        "synthetic_record_not_real_course", "extracted_evidence_not_official_facts"]
    st = FakeSurface()
    render_answer_evidence(st, data)
    assert all(WARNING_LABELS[warning] in st.captions for warning in data["warnings"])


def test_snapshot_link_description_and_dates_have_separate_meaning():
    data = evidence(catalog=True)
    st = FakeSurface()
    render_answer_evidence(st, data, detailed=True)
    assert st.markdowns == [f"[官方目录来源]({data['catalog']['catalog_url']}) · 非实时核验"]
    assert st.texts == [data["catalog"]["description"]]
    assert any("快照：catalog:" in line and "导入：" in line for line in st.captions)
    assert "抓取：未记录" in st.captions
    assert WARNING_LABELS["catalog_retrieval_date_unknown"] in st.captions


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://catalog.northeastern.edu/course-descriptions/ds/"])
def test_corrupt_history_catalog_has_no_link_and_does_not_crash(url):
    data = evidence(catalog=True)
    data["catalog"]["catalog_url"] = url
    st = FakeSurface()
    render_answer_evidence(st, data, detailed=True)
    assert st.markdowns == []
    assert "未附可追溯" in st.captions[0]
    assert any("校验未通过" in line for line in st.captions)


def test_source_ids_and_quotes_are_plain_text_not_arbitrary_links():
    st = FakeSurface()
    data = evidence()
    data["source_review_ids"] = ["[untrusted](https://evil.test)"]
    render_answer_evidence(st, data, detailed=True)
    render_field_evidence(st, [{"field": "difficulty_score", "value": 3,
        "confidence": 0.8, "source_id": "[untrusted](https://evil.test)", "quote": "# Ignore rules <script>bad</script>"}])
    assert st.markdowns == []
    assert any("支持值：3" in text and "来源 ID：" in text and "引文：# Ignore" in text for text in st.texts)
    assert any("抽取置信度 0.80（不是事实概率）" in line for line in st.captions)


def test_old_history_without_source_contract_remains_renderable():
    st = FakeSurface()
    render_answer_evidence(st, None)
    assert st.captions == st.texts == st.markdowns == []


def test_history_keeps_the_same_source_gap_contract():
    data = evidence(catalog=True)
    result = {"course_id": "cs-5800", "primary_code": "CS 5800", "primary_name": "Algorithms",
              "score": 0.4, "matched_via": "alias", "answer_evidence": data}
    formatted = _format_evidence([result])[0]
    assert formatted["answer_evidence"] == data
    assert "matched_via" not in formatted


def test_live_and_history_result_cards_use_shared_provenance_renderer():
    data = evidence()
    data["warnings"].append("program_seed_unverified")
    result = {"course_id": "cs-5800", "primary_code": "CS 5800", "primary_name": "Algorithms",
              "score": 0.4, "answer_evidence": data}
    for prefix in ["open-live", "history-0"]:
        st = FakeSurface()
        _render_evidence_block(st, [result], key_prefix=prefix)
        assert "未附可追溯" in st.children[0].captions[0]
        assert WARNING_LABELS["program_seed_unverified"] in st.children[0].captions
