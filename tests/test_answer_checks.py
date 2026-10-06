"""Live-answer checks (eval/answer_checks.py): each check fires on the problem it names and stays
quiet on a good answer.

中文：真实回答检查（eval/answer_checks.py）：每项检查在它针对的问题上报错，在好回答上不报。
"""

from __future__ import annotations

from eval.answer_checks import AnswerContext, check_answer, number_pattern, summarize

CATALOG = "https://catalog.northeastern.edu/course-descriptions/cs/"
ZH = AnswerContext(lang="zh", allowed_urls=frozenset({CATALOG}), has_rmp_data=True, fetch_date_relevant=True,
                   prereq_relevant=True, unstated_values=(12.0,), prompt_keys=frozenset({"field_evidence", "primary_code"}))
GOOD_ZH = (f"CS 5800 讲算法设计与分析。这些内容来自 [NEU 官方课程目录]({CATALOG}) 的存档副本，不是实时核对。"
           "根据 RateMyProfessors 上对任课老师的评价（可能是关于这位老师教的其他课），每周工作量估计约 12 小时。"
           "先修课之间是「都要」还是「任选」，记录里没有说明，需要向学校确认。")
HARD = ("ids_fail", "links_fail", "counts_fail", "rmp_fail")


def test_a_good_answer_passes_every_check():
    checks = check_answer(GOOD_ZH, ZH)
    assert not any(checks[name] for name in HARD)
    assert checks["label_language_ok"] is True and checks["caveats_missing"] == []
    assert checks["rmp"] == "instructor + may be another course"
    assert checks["estimates_as_reported"] == [] and checks["saved_copy_mentions"] == 1


def test_internal_ids_field_names_and_codes_fail():
    for leak in ("catalog:" + "ab12" * 16, "rmp_review_UmF0aW5nLTQy", "recorded_sources",
                 "program_schedule_unverified", "neu-cs-5800", "field_evidence"):
        assert check_answer(GOOD_ZH + leak, ZH)["ids_fail"], leak


def test_links_fail_for_other_targets_programs_labels_and_the_field_name():
    assert check_answer(GOOD_ZH + " [另一个页面](https://elsewhere.example/page)", ZH)["links_fail"]
    assert check_answer(GOOD_ZH + f" [培养方案]({CATALOG})", ZH)["links_fail"]
    assert check_answer(GOOD_ZH + " [NEU 官方课程目录](catalog_url)", ZH)["links_fail"]
    assert check_answer(GOOD_ZH + " 详见 www.elsewhere.example", ZH)["links_fail"]


def test_link_label_must_match_the_question_language():
    assert check_answer(GOOD_ZH.replace("NEU 官方课程目录", "NEU course catalog"), ZH)["label_language_ok"] is False
    en = AnswerContext(lang="en", allowed_urls=frozenset({CATALOG}))
    assert check_answer(f"See the [NEU course catalog]({CATALOG}).", en)["label_language_ok"] is True
    assert check_answer(f"See the [NEU 官方课程目录]({CATALOG}).", en)["label_language_ok"] is False
    assert check_answer("No links here.", en)["label_language_ok"] is None
    mixed = GOOD_ZH + f" 另见 [NEU course catalog]({CATALOG})。"
    assert check_answer(mixed, ZH)["label_language_ok"] is False  # Every label, not just one.


def test_review_counts_fail():
    assert check_answer(GOOD_ZH + "RateMyProfessors 上 50 条评价都说难。", ZH)["counts_fail"]
    en = AnswerContext(lang="en")
    assert check_answer("Twelve reviews say it is hard.", en)["counts_fail"]
    assert not check_answer("It takes about 12 hours a week.", en)["counts_fail"]
    # Naming the single quoted review is accurate, not a total (2026-10-06 live run).
    assert not check_answer("一条评论提到考试太重。", ZH)["counts_fail"]
    assert not check_answer("One review reported a difficulty rating of 5.0.", en)["counts_fail"]
    assert check_answer("两条评论都提到考试太重。", ZH)["counts_fail"]


def test_reviews_need_instructor_attribution_and_the_site_name_is_not_one():
    """'RateMyProfessors' itself must not count as naming the instructor."""
    context = AnswerContext(lang="zh", has_rmp_data=True)
    assert check_answer("RateMyProfessors 上的学生评价说这门课很难。", context)["rmp"] == "UNQUALIFIED"
    assert check_answer("RateMyProfessors reviews say it is hard.", AnswerContext(lang="en"))["rmp"] == "UNQUALIFIED"
    assert check_answer("RateMyProfessors 上对任课老师的评价说很难。", context)["rmp"] == "instructor, no other-course caveat"
    assert check_answer("Reviews of the professor on RateMyProfessors.", AnswerContext(lang="en"))["rmp"] == (
        "instructor, no other-course caveat")
    assert check_answer("这门课讲图算法。", context)["rmp"] == "not used"


def test_missing_caveats_are_listed():
    context = AnswerContext(lang="zh", fetch_date_relevant=True, no_catalog_relevant=True, prereq_relevant=True,
                            program_notice=True)
    assert check_answer("这门课讲图算法。", context)["caveats_missing"] == [
        "fetch_date", "no_catalog", "prereq_logic", "program_caveat", "programs_page_pointer"]


def test_an_unstated_estimate_called_reviewer_reported_is_flagged():
    context = AnswerContext(lang="zh", unstated_values=(12.0,))
    flagged = check_answer("RateMyProfessors 的评价报告每周要 12 小时。", context)["estimates_as_reported"]
    assert [item["value"] for item in flagged] == [12.0]
    assert check_answer("每周工作量估计约 12 小时。", context)["estimates_as_reported"] == []
    assert check_answer("记录里写的是 12 小时。", context)["estimates"][0]["kind"] == "attributed to the record"
    assert check_answer("这门课 4 学分，需要 12.5 小时。", context)["estimates"] == []


def test_number_pattern_ignores_larger_numbers_and_credits():
    pattern = number_pattern(4.0)
    assert pattern.search("难度 4/5") and pattern.search("难度 4.0")
    assert not any(pattern.search(text) for text in ("CS 5400", "4 学分", "14 小时", "4.5"))


def test_saved_copy_sentences_are_counted_per_sentence():
    once = "这些内容来自目录的存档副本，并非实时查询。"
    assert check_answer(once, AnswerContext(lang="zh"))["saved_copy_mentions"] == 1
    assert check_answer(once * 3, AnswerContext(lang="zh"))["saved_copy_mentions"] == 3


def test_summary_counts():
    summary = summarize([check_answer(GOOD_ZH, ZH), check_answer(GOOD_ZH + " neu-cs-5800", ZH),
                         check_answer("同上。这些内容来自存档副本。" * 2, ZH)])
    assert summary["answers"] == 3 and summary["ids_fail"] == 1 and summary["links_fail"] == 0
    assert summary["repeated_saved_copy"] == 1
    assert summary["rmp"] == {"instructor + may be another course": 2, "not used": 1}
